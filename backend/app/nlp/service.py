"""Business logic for NLP pipeline: search queries, sentence processing, jobs."""

import logging
from datetime import timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationPrediction
from app.common.crud import get_scoped, list_scoped, soft_delete
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.engine import parse_query, process_note
from app.nlp.models import NlpJob, NlpJobStatus, SearchQuery, Sentence

logger = logging.getLogger(__name__)


# ── Search Query CRUD ────────────────────────────────────────────


async def create_search_query(
    session: AsyncSession,
    project_id: str,
    query: str,
    name: str = "",
    created_by: str | None = None,
    *,
    nlp_apply: bool = True,
    hide_duplicates: bool = True,
    skip_after_event: bool = True,
    exclude_negated: bool = True,
    commit: bool = True,
) -> SearchQuery:
    # Enforce one active query per project: deactivate the current active
    # query (if any) before inserting the new active row.
    await session.execute(
        update(SearchQuery)
        .where(
            SearchQuery.project_id == project_id,
            SearchQuery.deleted_at.is_(None),
            SearchQuery.is_active.is_(True),
        )
        .values(is_active=False)
    )
    sq = SearchQuery(
        project_id=project_id,
        name=name,
        query=query,
        created_by=created_by,
        nlp_apply=nlp_apply,
        hide_duplicates=hide_duplicates,
        skip_after_event=skip_after_event,
        exclude_negated=exclude_negated,
    )
    session.add(sq)
    if commit:
        await session.commit()
        await session.refresh(sq)
    else:
        await session.flush()
    return sq


async def activate_search_query(
    session: AsyncSession, project_id: str, query_id: str
) -> SearchQuery | None:
    """Set a query as the active one for the project (deactivates others)."""
    sq = await get_search_query(session, project_id, query_id)
    if not sq:
        return None

    # Deactivate all others via an immediate UPDATE so it executes before
    # the flush-time UPDATE below (the partial unique index is checked per
    # statement; deactivating first avoids a spurious violation).
    await session.execute(
        update(SearchQuery)
        .where(
            SearchQuery.project_id == project_id,
            SearchQuery.deleted_at.is_(None),
            SearchQuery.is_active.is_(True),
            SearchQuery.id != query_id,
        )
        .values(is_active=False)
    )

    sq.is_active = True
    session.add(sq)
    await session.commit()
    await session.refresh(sq)
    return sq


async def list_search_queries(
    session: AsyncSession, project_id: str
) -> list[SearchQuery]:
    return await list_scoped(session, SearchQuery, project_id)


async def get_search_query(
    session: AsyncSession, project_id: str, query_id: str
) -> SearchQuery | None:
    return await get_scoped(session, SearchQuery, project_id, query_id)


# A review lock older than this belongs to an abandoned session and no longer blocks reprocessing.
STALE_LOCK_AGE = timedelta(hours=1)

_QUERY_UPDATE_FIELDS = {
    "query", "name", "nlp_apply", "hide_duplicates",
    "skip_after_event", "exclude_negated",
}


async def update_search_query(
    session: AsyncSession, project_id: str, query_id: str, updates: dict
) -> SearchQuery | None:
    sq = await get_search_query(session, project_id, query_id)
    if not sq:
        return None
    for key, value in updates.items():
        if key in _QUERY_UPDATE_FIELDS and value is not None:
            setattr(sq, key, value)
    session.add(sq)
    await session.commit()
    await session.refresh(sq)
    return sq


async def delete_search_query(
    session: AsyncSession, project_id: str, query_id: str
) -> bool:
    sq = await get_search_query(session, project_id, query_id)
    if not sq:
        return False
    await soft_delete(session, sq)
    return True


# ── NLP Processing ───────────────────────────────────────────────


async def dispatch_nlp_job(
    session: AsyncSession,
    project_id: str,
    user_id: str,
    *,
    confirmed: bool = False,
) -> dict:
    """Dispatch keyword production processing through the production coordinator."""
    from app.production.service import start_run

    try:
        config = await _active_production_config(session, project_id)
    except ValueError as exc:
        if str(exc) != "No active search query configured for this project":
            raise
        stats = await _process_notes_into_sentences(
            session, project_id, create_annotations=False, rebuild=True
        )
        bg_job = BackgroundJob(
            project_id=project_id,
            job_type=JobType.NLP,
            status=JobStatus.COMPLETED,
            progress=100,
            created_by=user_id,
            result_summary=stats,
            started_at=now_utc(),
            completed_at=now_utc(),
        )
        session.add(bg_job)
        await session.commit()
        await session.refresh(bg_job)
        return {
            "job_id": bg_job.id,
            "status": bg_job.status.value,
            "progress": bg_job.progress,
        }

    production_run = await start_run(
        session, project_id, user_id, config, confirmed=confirmed
    )
    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.NLP,
        status=JobStatus.PENDING,
        created_by=user_id,
        result_summary={"production_run_id": production_run.id},
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(session.bind, class_=_AsyncSession, expire_on_commit=False)
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        try:
            await redis.enqueue_job("run_nlp_job", project_id, bg_job.id)
        finally:
            await redis.aclose()
    except Exception:
        logger.info("ARQ unavailable; executing production NLP job synchronously")
        await _execute_production_nlp_job(
            project_id, bg_job.id, production_run.id, factory
        )
        await session.refresh(bg_job)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


async def _active_production_config(session: AsyncSession, project_id: str) -> dict:
    result = await session.execute(
        select(SearchQuery).where(
            SearchQuery.project_id == project_id,
            SearchQuery.deleted_at.is_(None),
            SearchQuery.is_active.is_(True),
        )
    )
    query = result.scalar_one_or_none()
    if query is None:
        raise ValueError("No active search query configured for this project")
    return {
        "query": query.query,
        "hide_duplicates": query.hide_duplicates,
        "skip_after_event": query.skip_after_event,
        "exclude_negated": query.exclude_negated,
    }


async def _execute_production_nlp_job(project_id, job_id, run_id, session_factory) -> None:
    from app.production.models import ProductionRun
    from app.production.service import cancel_run, execute_run, get_stats

    async with session_factory() as session:
        job = await session.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = now_utc()
        await session.commit()
        try:
            await _process_notes_into_sentences(
                session, project_id, create_annotations=False, rebuild=True
            )
            run = await execute_run(session, run_id)
            stats = await get_stats(session, run_id)
            job.status = (
                JobStatus.FAILED if run.status == "failed" else JobStatus.COMPLETED
            )
            job.progress = 100 if run.status in {"completed", "failed"} else 0
            job.result_summary = {**(job.result_summary or {}), **stats}
        except Exception as exc:
            await session.rollback()
            run = await session.get(ProductionRun, run_id)
            if run is not None and run.status in {"queued", "running"}:
                try:
                    await cancel_run(session, run_id)
                except Exception:
                    await session.rollback()
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
        job.completed_at = now_utc()
        session.add(job)
        await session.commit()


async def get_nlp_job_status(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Get the latest NLP background job status for a project."""
    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type == JobType.NLP,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    bg_job = result.scalar_one_or_none()
    if not bg_job:
        return None

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
        "result_summary": bg_job.result_summary,
        "error_message": bg_job.error_message,
    }


async def cancel_nlp_job(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Cancel a running or pending NLP job for a project."""
    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type == JobType.NLP,
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    bg_job = result.scalar_one_or_none()
    if not bg_job:
        return None

    run_id = (bg_job.result_summary or {}).get("production_run_id")
    if run_id:
        from app.production.service import cancel_run

        await cancel_run(session, run_id)
    bg_job.is_cancelled = True
    bg_job.status = JobStatus.CANCELLED
    bg_job.completed_at = now_utc()
    session.add(bg_job)
    await session.commit()

    return {"job_id": bg_job.id, "cancelled": True}


async def _process_notes_into_sentences(
    session: AsyncSession,
    project_id: str,
    progress_callback=None,
    *,
    create_annotations: bool = True,
    rebuild: bool = False,
) -> dict:
    """Cache sentence processing without writing production annotations."""
    if rebuild:
        await session.execute(delete(Sentence).where(Sentence.project_id == project_id))

    # Get active search queries
    queries = await list_search_queries(session, project_id)
    active_queries = [q for q in queries if q.is_active]

    all_query_groups = []
    for q in active_queries:
        groups = parse_query(q.query)
        all_query_groups.extend(groups)
    # Single active query per project is enforced at the DB level; negation
    # exclusion follows that query's setting.

    # Get notes that haven't been processed yet (no sentences exist)
    notes_stmt = (
        select(Note)
        .outerjoin(Sentence, Sentence.note_id == Note.id)
        .where(
            Note.project_id == project_id,
            Note.deleted_at.is_(None),
            Sentence.id.is_(None),
        )
        .order_by(Note.created_at)
    )
    result = await session.execute(notes_stmt)
    notes = list(result.scalars().all())

    total = len(notes)
    if not notes and not create_annotations and not rebuild:
        return {
            "total_notes": 0,
            "processed_notes": 0,
            "annotations_created": 0,
            "patients_with_matches": 0,
            "patients_auto_completed": 0,
        }

    for i, note in enumerate(notes):
        sentences = process_note(note.text, all_query_groups)
        for sent_data in sentences:
            sentence = Sentence(
                note_id=note.id,
                project_id=project_id,
                sentence_number=sent_data["sentence_number"],
                text=sent_data["text"],
                start_pos=sent_data["start_pos"],
                end_pos=sent_data["end_pos"],
                is_negated=sent_data["is_negated"],
                is_target=sent_data["is_target"],
                matched_tokens=sent_data["matched_tokens"],
            )
            session.add(sentence)

        if (i + 1) % 50 == 0 or i == total - 1:
            if progress_callback:
                await progress_callback(i + 1, total)

    await session.commit()

    if create_annotations:
        from app.production.service import execute_run, get_stats, start_run

        production_run = await start_run(
            session,
            project_id,
            None,
            await _active_production_config(session, project_id),
            confirmed=False,
        )
        await execute_run(session, production_run.id)
        production_stats = await get_stats(session, production_run.id)
        patient_count = await session.scalar(
            select(func.count(func.distinct(Annotation.patient_id))).where(
                Annotation.project_id == project_id,
                Annotation.production_run_id == production_run.id,
            )
        )
        return {
            "total_notes": production_run.total_notes,
            "processed_notes": production_run.completed_notes,
            "annotations_created": production_stats["annotations_total"],
            "patients_with_matches": patient_count or 0,
            "patients_auto_completed": 0,
        }

    return {
        "total_notes": total,
        "processed_notes": total,
        "annotations_created": 0,
        "patients_with_matches": 0,
        "patients_auto_completed": 0,
    }


async def run_nlp_pipeline(
    session: AsyncSession, project_id: str, *, create_annotations: bool = True,
) -> NlpJob:
    """Run production processing, or cache sentences for evaluation-only callers."""
    confirmed_run_id = session.info.pop("confirmed_production_run_id", None)
    if create_annotations and confirmed_run_id is None:
        from app.production.service import start_run

        production_run = await start_run(
            session,
            project_id,
            None,
            await _active_production_config(session, project_id),
            confirmed=False,
        )
        confirmed_run_id = production_run.id

    job = NlpJob(project_id=project_id)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    job_id = job.id

    try:
        job.status = NlpJobStatus.RUNNING
        job.started_at = now_utc()
        session.add(job)
        await session.commit()

        if create_annotations:
            from app.production.service import execute_run

            await _process_notes_into_sentences(
                session, project_id, create_annotations=False, rebuild=True
            )
            run_id = confirmed_run_id
            production_run = await execute_run(session, run_id)
            job.total_notes = production_run.total_notes
            job.processed_notes = production_run.completed_notes
            job.status = (
                NlpJobStatus.FAILED
                if production_run.status == "failed"
                else NlpJobStatus.COMPLETED
            )
            job.error_message = production_run.error_summary
            job.completed_at = now_utc()
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

        async def _progress(processed, total):
            job.total_notes = total
            job.processed_notes = processed
            session.add(job)
            await session.commit()

        stats = await _process_notes_into_sentences(
            session,
            project_id,
            _progress,
            create_annotations=False,
        )

        job.status = NlpJobStatus.COMPLETED
        job.total_notes = stats["total_notes"]
        job.processed_notes = stats["processed_notes"]
        job.completed_at = now_utc()

    except Exception:
        logger.exception("NLP pipeline failed for project %s", project_id)
        await session.rollback()
        job = await session.get(NlpJob, job_id)
        if job is None:
            raise
        job.status = NlpJobStatus.FAILED
        job.error_message = "NLP processing failed. Check server logs for details."
        job.completed_at = now_utc()

    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ── Queries ──────────────────────────────────────────────────────


async def get_nlp_stats(session: AsyncSession, project_id: str) -> dict:
    """Get NLP processing stats for a project."""
    # Query 1: note counts (total + processed via distinct sentence.note_id)
    notes_stmt = (
        select(
            func.count(Note.id).label("total_notes"),
            func.count(func.distinct(Sentence.note_id)).label("processed_notes"),
        )
        .select_from(Note)
        .outerjoin(Sentence, (Sentence.note_id == Note.id) & (Sentence.project_id == project_id))
        .where(Note.project_id == project_id, Note.deleted_at.is_(None))
    )
    notes_row = (await session.execute(notes_stmt)).one()

    # Query 2: sentence counts with conditional aggregation
    sent_stmt = (
        select(
            func.count().label("total_sentences"),
            func.count(case(
                (Sentence.is_target.is_(True), 1),
            )).label("target_sentences"),
            func.count(case(
                (Sentence.is_target.is_(True) & Sentence.is_negated.is_(True), 1),
            )).label("negated_sentences"),
        )
        .select_from(Sentence)
        .where(Sentence.project_id == project_id)
    )
    sent_row = (await session.execute(sent_stmt)).one()

    return {
        "total_notes": notes_row.total_notes,
        "processed_notes": notes_row.processed_notes,
        "total_sentences": sent_row.total_sentences,
        "target_sentences": sent_row.target_sentences,
        "negated_sentences": sent_row.negated_sentences,
    }


async def get_latest_job(
    session: AsyncSession, project_id: str
) -> NlpJob | None:
    stmt = (
        select(NlpJob)
        .where(NlpJob.project_id == project_id)
        .order_by(NlpJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_target_sentences(
    session: AsyncSession,
    project_id: str,
    include_negated: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Sentence]:
    """Get target sentences for a project (matched search queries)."""
    stmt = (
        select(Sentence)
        .where(
            Sentence.project_id == project_id,
            Sentence.is_target.is_(True),
        )
        .order_by(Sentence.created_at, Sentence.sentence_number)
        .offset(offset)
        .limit(limit)
    )
    if not include_negated:
        stmt = stmt.where(Sentence.is_negated.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_reprocess_impact(session: AsyncSession, project_id: str) -> dict:
    counts = {}
    for name, model in (
        ("annotations", Annotation), ("predictions", AnnotationPrediction),
        ("sentences", Sentence),
    ):
        counts[name] = (
            await session.execute(
                select(func.count()).select_from(model).where(model.project_id == project_id)
            )
        ).scalar_one()
    return counts


async def reprocess_is_busy(session: AsyncSession, project_id: str) -> bool:
    from app.pipeline.models import PipelineRun, PipelineRunStatus
    from app.production.models import ProductionRun

    checks = (
        select(BackgroundJob.id).where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type.in_([JobType.NLP, JobType.PREDICTION]),
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        ),
        select(NlpJob.id).where(
            NlpJob.project_id == project_id,
            NlpJob.status.in_([NlpJobStatus.PENDING, NlpJobStatus.RUNNING]),
        ),
        select(PipelineRun.id).where(
            PipelineRun.project_id == project_id,
            PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING]),
        ),
        select(ProductionRun.id).where(
            ProductionRun.project_id == project_id,
            ProductionRun.status.in_(["queued", "running"]),
        ),
        select(Patient.id).where(
            Patient.project_id == project_id,
            Patient.locked_by.is_not(None),
            Patient.status != PatientStatus.REVIEWED,
            Patient.locked_at > now_utc() - STALE_LOCK_AGE,
        ),
    )
    for statement in checks:
        if (await session.execute(statement.limit(1))).first() is not None:
            return True
    return False


async def clear_sentences(
    session: AsyncSession, project_id: str, *, commit: bool = True,
) -> int:
    """Clear the sentence cache; confirmed production reset is coordinated separately."""
    result = await session.execute(delete(Sentence).where(Sentence.project_id == project_id))
    if commit:
        from app.production.service import start_run

        config = await _active_production_config(session, project_id)
        production_run = await start_run(
            session, project_id, None, config, confirmed=True
        )
        session.info["confirmed_production_run_id"] = production_run.id
    else:
        from app.production.service import start_run

        config = await _active_production_config(session, project_id)
        production_run = await start_run(
            session, project_id, None, config, confirmed=True
        )
        session.info["confirmed_production_run_id"] = production_run.id
    if commit:
        await session.commit()
    return result.rowcount
