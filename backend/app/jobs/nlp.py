"""NLP pipeline ARQ job implementation."""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.jobs.models import BackgroundJob, JobStatus

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
    from app.nlp.service import _process_notes_into_sentences

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
            async def _progress(processed, total):
                bg_job.progress = int((processed / total) * 100)
                bg_job.result_summary = {
                    "total_notes": total,
                    "processed_notes": processed,
                }
                session.add(bg_job)
                await session.commit()

            stats = await _process_notes_into_sentences(
                session, project_id, _progress,
            )

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = stats

        except Exception as exc:
            logger.exception("NLP job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return bg_job.result_summary or {}
