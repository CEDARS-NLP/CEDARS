"""NLP pipeline ARQ job implementation."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.engine import parse_query, process_note
from app.nlp.models import SearchQuery, Sentence

logger = logging.getLogger(__name__)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a standalone session factory for worker processes."""
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def execute_nlp_job(
    project_id: str,
    job_db_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Run the NLP pipeline, updating BackgroundJob progress.

    Called from ARQ worker (separate process) -- creates its own DB session.
    When called inline (sync fallback), an existing session_factory can be passed.
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    async with session_factory() as session:
        bg_job = await session.get(BackgroundJob, job_db_id)
        if not bg_job:
            logger.error("BackgroundJob %s not found", job_db_id)
            return {"error": "Job not found"}

        bg_job.status = JobStatus.RUNNING
        bg_job.started_at = datetime.now(UTC)
        session.add(bg_job)
        await session.commit()

        try:
            # Get active search queries
            stmt = (
                select(SearchQuery)
                .where(
                    SearchQuery.project_id == project_id,
                    SearchQuery.deleted_at.is_(None),
                    SearchQuery.is_active.is_(True),
                )
                .order_by(SearchQuery.created_at.desc())
            )
            result = await session.execute(stmt)
            queries = list(result.scalars().all())

            all_query_groups = []
            for q in queries:
                groups = parse_query(q.query)
                all_query_groups.extend(groups)

            # Get unprocessed notes
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
            bg_job.result_summary = {"total_notes": total, "processed_notes": 0}
            session.add(bg_job)
            await session.commit()

            if not notes:
                bg_job.status = JobStatus.COMPLETED
                bg_job.progress = 100
                bg_job.completed_at = datetime.now(UTC)
                session.add(bg_job)
                await session.commit()
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
                    bg_job.progress = int(((i + 1) / total) * 100)
                    bg_job.result_summary = {
                        "total_notes": total,
                        "processed_notes": i + 1,
                    }
                    session.add(bg_job)
                    await session.commit()

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = {"total_notes": total, "processed_notes": total}

        except Exception as exc:
            logger.exception("NLP job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return bg_job.result_summary or {}
