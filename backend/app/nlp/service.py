"""Business logic for NLP pipeline: search queries, sentence processing, jobs."""

import logging

from sqlalchemy import case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.filters import reviewable_filter
from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
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
) -> SearchQuery:
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


_QUERY_UPDATE_FIELDS = {
    "query", "name", "is_active", "nlp_apply", "hide_duplicates",
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


async def dispatch_nlp_job(session: AsyncSession, project_id: str, user_id: str) -> dict:
    """Create a BackgroundJob and enqueue NLP processing via ARQ.

    Falls back to synchronous execution if Redis/ARQ is unavailable.
    """
    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.NLP,
        status=JobStatus.PENDING,
        created_by=user_id,
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    use_sync = True
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())

        # Check if any ARQ workers are active before enqueuing
        health_key = await redis.exists(b"arq:queue:health-check")
        if health_key:
            arq_job = await redis.enqueue_job("run_nlp_job", project_id, bg_job.id)
            bg_job.arq_job_id = arq_job.job_id
            session.add(bg_job)
            await session.commit()
            use_sync = False
        else:
            logger.warning("No ARQ workers found, running NLP synchronously")

        await redis.aclose()
    except Exception:
        logger.warning("ARQ unavailable, running NLP synchronously")

    if use_sync:
        import asyncio

        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.jobs.nlp import execute_nlp_job

        # Build a session factory from the current session's bind so that
        # the inline execution uses the same database (important in tests
        # where the DB is overridden via dependency injection).
        factory = async_sessionmaker(
            session.bind, class_=_AsyncSession, expire_on_commit=False
        )
        # Run as a background task so the endpoint returns immediately
        # and the job is cancellable via the cancel endpoint.
        def _on_done(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception():
                logger.exception("Background NLP task failed", exc_info=t.exception())

        task = asyncio.create_task(
            execute_nlp_job(project_id, bg_job.id, session_factory=factory)
        )
        task.add_done_callback(_on_done)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


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
) -> dict:
    """Core NLP pipeline: fetch queries, find unprocessed notes, create sentences.

    Every matched token also becomes an Annotation row, mirroring the v1
    nlpprocessor record, so review can proceed without any predictor.

    Returns a stats dict with note, annotation and patient counts.
    """
    # Get active search queries
    queries = await list_search_queries(session, project_id)
    active_queries = [q for q in queries if q.is_active]

    all_query_groups = []
    for q in active_queries:
        groups = parse_query(q.query)
        all_query_groups.extend(groups)
    exclude_negated = len(active_queries) == 1 and active_queries[0].exclude_negated

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
    if not notes:
        return {
            "total_notes": 0,
            "processed_notes": 0,
            "annotations_created": 0,
            "patients_with_matches": 0,
            "patients_auto_completed": 0,
        }

    annotations_created = 0
    match_counts: dict[str, int] = {}

    for i, note in enumerate(notes):
        sentences = process_note(note.text, all_query_groups)
        match_counts.setdefault(note.patient_id, 0)
        sentence_rows = []

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
            sentence_rows.append((sentence, sent_data))

        await session.flush()

        for sentence, sent_data in sentence_rows:
            for match in sent_data.get("matches", []):
                auto_excluded = exclude_negated and sent_data["is_negated"]
                session.add(
                    Annotation(
                        project_id=project_id,
                        patient_id=note.patient_id,
                        note_id=note.id,
                        sentence_id=sentence.id,
                        sentence_text=sent_data["text"],
                        matched_tokens=",".join(sent_data["matched_tokens"]),
                        is_negated=sent_data["is_negated"],
                        token=match["token"],
                        note_start_index=match["note_start_index"],
                        note_end_index=match["note_end_index"],
                        sentence_number=sent_data["sentence_number"],
                        sentence_start=sent_data["start_pos"],
                        sentence_end=sent_data["end_pos"],
                        text_date=note.note_date,
                        review_status=(
                            ReviewStatus.REVIEWED if auto_excluded else ReviewStatus.UNREVIEWED
                        ),
                        reviewed_at=now_utc() if auto_excluded else None,
                        review_excluded=auto_excluded,
                    )
                )
                annotations_created += 1
                match_counts[note.patient_id] += 1

        await session.flush()

        if (i + 1) % 50 == 0 or i == total - 1:
            if progress_callback:
                await progress_callback(i + 1, total)

    matched_patients = [pid for pid, count in match_counts.items() if count > 0]
    patients_with_unreviewed = set()

    touched_patient_ids = list(match_counts)
    if touched_patient_ids:
        pending_result = await session.execute(
            select(Annotation.patient_id)
            .where(
                Annotation.project_id == project_id,
                Annotation.patient_id.in_(touched_patient_ids),
                Annotation.review_status == ReviewStatus.UNREVIEWED,
                Annotation.review_excluded.is_(False),
                reviewable_filter(),
            )
            .distinct()
        )
        patients_with_unreviewed = set(pending_result.scalars().all())

    auto_completed_patients = [pid for pid in touched_patient_ids if pid not in patients_with_unreviewed]
    patients_requiring_review = [pid for pid in matched_patients if pid in patients_with_unreviewed]

    if patients_requiring_review:
        await session.execute(
            update(Patient)
            .where(
                Patient.id.in_(patients_requiring_review),
                Patient.status != PatientStatus.REVIEWING,
            )
            .values(
                status=PatientStatus.NLP_COMPLETE, updated_at=now_utc(),
                review_source=None, review_reason=None, reviewed_by=None, reviewed_at=None,
            )
        )
    if auto_completed_patients:
        annotations_result = await session.execute(
            select(Annotation).where(
                Annotation.project_id == project_id,
                Annotation.patient_id.in_(auto_completed_patients),
            )
        )
        annotations_by_patient: dict[str, list[Annotation]] = {}
        for annotation in annotations_result.scalars():
            annotations_by_patient.setdefault(annotation.patient_id, []).append(annotation)
        for patient_id in auto_completed_patients:
            patient = await session.get(Patient, patient_id)
            if patient is None or patient.review_source in ("human", "llm"):
                continue
            existing = annotations_by_patient.get(patient_id, [])
            if existing and not all(
                annotation.review_excluded and annotation.reviewed_by is None
                and not annotation.manual_review_override for annotation in existing
            ):
                continue
            patient.status = PatientStatus.REVIEWED
            patient.review_source = "cedars"
            patient.review_reason = (
                "negated_matches_only" if existing else "no_keyword_matches"
            )
            patient.reviewed_by = None
            patient.reviewed_at = now_utc()
            patient.updated_at = now_utc()
            session.add(patient)
    await session.commit()

    return {
        "total_notes": total,
        "processed_notes": total,
        "annotations_created": annotations_created,
        "patients_with_matches": len(matched_patients),
        "patients_auto_completed": len(auto_completed_patients),
    }


async def run_nlp_pipeline(
    session: AsyncSession, project_id: str
) -> NlpJob:
    """Run the NLP pipeline for a project: split notes into sentences,
    match search queries, detect negation.

    Creates sentences for all notes that haven't been processed yet.
    """
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

        async def _progress(processed, total):
            job.total_notes = total
            job.processed_notes = processed
            session.add(job)
            await session.commit()

        stats = await _process_notes_into_sentences(session, project_id, _progress)

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
        select(Patient.id).where(
            Patient.project_id == project_id, Patient.locked_by.is_not(None),
        ),
    )
    for statement in checks:
        if (await session.execute(statement.limit(1))).first() is not None:
            return True
    return False


async def clear_sentences(session: AsyncSession, project_id: str) -> int:
    """Delete all sentences (and their annotations) for a project to allow re-processing."""
    # Delete predictions first (FK dependency on annotations)
    await session.execute(
        text("DELETE FROM annotation_predictions WHERE project_id = :pid"),
        {"pid": project_id},
    )
    # Delete annotations next (FK dependency on sentences)
    await session.execute(
        text("DELETE FROM annotations WHERE project_id = :pid"),
        {"pid": project_id},
    )
    await session.execute(
        update(Patient)
        .where(Patient.project_id == project_id)
        .values(
            status=PatientStatus.NLP_COMPLETE, review_source=None, review_reason=None,
            reviewed_by=None, reviewed_at=None, updated_at=now_utc(),
        )
    )
    result = await session.execute(
        text("DELETE FROM sentences WHERE project_id = :pid"),
        {"pid": project_id},
    )
    await session.commit()
    return result.rowcount
