"""Business logic for NLP pipeline: search queries, sentence processing, jobs."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import Note, Patient, PatientStatus
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
) -> SearchQuery:
    sq = SearchQuery(
        project_id=project_id,
        name=name,
        query=query,
        created_by=created_by,
        nlp_apply=nlp_apply,
        hide_duplicates=hide_duplicates,
        skip_after_event=skip_after_event,
    )
    session.add(sq)
    await session.commit()
    await session.refresh(sq)
    return sq


async def list_search_queries(
    session: AsyncSession, project_id: str
) -> list[SearchQuery]:
    stmt = (
        select(SearchQuery)
        .where(SearchQuery.project_id == project_id, SearchQuery.deleted_at.is_(None))
        .order_by(SearchQuery.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_search_query(
    session: AsyncSession, project_id: str, query_id: str
) -> SearchQuery | None:
    stmt = select(SearchQuery).where(
        SearchQuery.id == query_id,
        SearchQuery.project_id == project_id,
        SearchQuery.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_search_query(
    session: AsyncSession, project_id: str, query_id: str, updates: dict
) -> SearchQuery | None:
    sq = await get_search_query(session, project_id, query_id)
    if not sq:
        return None
    for key, value in updates.items():
        if value is not None and hasattr(sq, key):
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
    sq.deleted_at = datetime.now(UTC)
    session.add(sq)
    await session.commit()
    return True


# ── NLP Processing ───────────────────────────────────────────────


async def dispatch_nlp_job(session: AsyncSession, project_id: str, user_id: str) -> dict:
    """Create a BackgroundJob and enqueue NLP processing via ARQ.

    Falls back to synchronous execution if Redis/ARQ is unavailable.
    """
    from app.jobs.models import BackgroundJob, JobStatus, JobType

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.NLP,
        status=JobStatus.PENDING,
        created_by=user_id,
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        arq_job = await redis.enqueue_job("run_nlp_job", project_id, bg_job.id)
        bg_job.arq_job_id = arq_job.job_id
        session.add(bg_job)
        await session.commit()
        await redis.aclose()
    except Exception:
        logger.warning("ARQ unavailable, running NLP synchronously")
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _AsyncSession

        from app.jobs.nlp import execute_nlp_job

        # Build a session factory from the current session's bind so that
        # the inline execution uses the same database (important in tests
        # where the DB is overridden via dependency injection).
        factory = async_sessionmaker(
            session.bind, class_=_AsyncSession, expire_on_commit=False
        )
        await execute_nlp_job(project_id, bg_job.id, session_factory=factory)
        await session.refresh(bg_job)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


async def _process_notes_into_sentences(
    session: AsyncSession,
    project_id: str,
    progress_callback=None,
) -> dict:
    """Core NLP pipeline: fetch queries, find unprocessed notes, create sentences.

    Returns {"total_notes": int, "processed_notes": int}.
    """
    # Get active search queries
    queries = await list_search_queries(session, project_id)
    active_queries = [q for q in queries if q.is_active]

    all_query_groups = []
    for q in active_queries:
        groups = parse_query(q.query)
        all_query_groups.extend(groups)

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
        return {"total_notes": 0, "processed_notes": 0}

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

        await session.flush()

        if (i + 1) % 50 == 0 or i == total - 1:
            if progress_callback:
                await progress_callback(i + 1, total)

    return {"total_notes": total, "processed_notes": total}


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

    try:
        job.status = NlpJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
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
        job.completed_at = datetime.now(UTC)

    except Exception as exc:
        logger.exception("NLP pipeline failed for project %s", project_id)
        job.status = NlpJobStatus.FAILED
        job.error_message = str(exc)

    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ── Queries ──────────────────────────────────────────────────────


async def get_nlp_stats(session: AsyncSession, project_id: str) -> dict:
    """Get NLP processing stats for a project."""
    total_notes = (
        await session.execute(
            select(func.count(Note.id)).where(
                Note.project_id == project_id, Note.deleted_at.is_(None)
            )
        )
    ).scalar() or 0

    # Notes that have sentences
    processed_notes = (
        await session.execute(
            select(func.count(func.distinct(Sentence.note_id))).where(
                Sentence.project_id == project_id
            )
        )
    ).scalar() or 0

    total_sentences = (
        await session.execute(
            select(func.count(Sentence.id)).where(
                Sentence.project_id == project_id
            )
        )
    ).scalar() or 0

    target_sentences = (
        await session.execute(
            select(func.count(Sentence.id)).where(
                Sentence.project_id == project_id,
                Sentence.is_target.is_(True),
            )
        )
    ).scalar() or 0

    negated_sentences = (
        await session.execute(
            select(func.count(Sentence.id)).where(
                Sentence.project_id == project_id,
                Sentence.is_target.is_(True),
                Sentence.is_negated.is_(True),
            )
        )
    ).scalar() or 0

    return {
        "total_notes": total_notes,
        "processed_notes": processed_notes,
        "total_sentences": total_sentences,
        "target_sentences": target_sentences,
        "negated_sentences": negated_sentences,
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


async def clear_sentences(session: AsyncSession, project_id: str) -> int:
    """Delete all sentences (and their annotations) for a project to allow re-processing."""
    # Delete annotations first (FK dependency on sentences)
    await session.execute(
        text("DELETE FROM annotations WHERE project_id = :pid"),
        {"pid": project_id},
    )
    # Reset patients that were marked reviewed back to nlp_complete
    await session.execute(
        update(Patient)
        .where(Patient.project_id == project_id, Patient.status == PatientStatus.REVIEWED)
        .values(status=PatientStatus.NLP_COMPLETE)
    )
    result = await session.execute(
        text("DELETE FROM sentences WHERE project_id = :pid"),
        {"pid": project_id},
    )
    await session.commit()
    return result.rowcount
