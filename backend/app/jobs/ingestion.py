"""Ingestion pipeline ARQ job implementation."""

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


async def execute_ingestion_job(
    project_id: str,
    job_db_id: str,
    data_source_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Run data ingestion, updating BackgroundJob progress.

    Called from ARQ worker (separate process) -- creates its own DB session.
    When called inline (sync fallback), an existing session_factory can be passed.
    """
    from app.audit.models import AuditAction
    from app.audit.service import log_action
    from app.connectors.models import IngestionStatus
    from app.connectors.registry import get_connector
    from app.connectors.service import _ingest_rows, get_data_source

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
            ds = await get_data_source(session, project_id, data_source_id)
            if not ds:
                raise ValueError("Data source not found")

            connector = get_connector(ds.connector_type)

            errors = await connector.validate_config(ds.config)
            if errors:
                ds.status = IngestionStatus.FAILED
                ds.error_message = "; ".join(errors)
                session.add(ds)
                await session.commit()
                raise ValueError(f"Connector validation failed: {ds.error_message}")

            ds.status = IngestionStatus.RUNNING
            ds.error_message = None
            session.add(ds)
            await session.commit()

            total_rows = 0
            offset = 0
            batch_size = 1000
            batch_num = 0

            while True:
                # Check cancellation between batches
                await session.refresh(bg_job)
                if bg_job.is_cancelled:
                    ds.status = IngestionStatus.FAILED
                    ds.error_message = "Cancelled by user"
                    session.add(ds)
                    bg_job.status = JobStatus.CANCELLED
                    bg_job.completed_at = datetime.now(UTC)
                    bg_job.result_summary = {"total_rows": total_rows, "batches": batch_num}
                    session.add(bg_job)
                    await session.commit()
                    return bg_job.result_summary

                batch = await connector.fetch(ds.config, batch_size=batch_size, offset=offset)
                if not batch.rows:
                    break

                mapping = ds.config.get("column_mapping", {})
                count = await _ingest_rows(session, project_id, ds.id, batch.rows, mapping)
                total_rows += count
                offset += batch_size
                batch_num += 1

                # Update progress
                bg_job.result_summary = {"total_rows": total_rows, "batches": batch_num}
                # We don't know total ahead of time, so use batch count for progress
                # If has_more is False on next check, we'll set to 100
                if not batch.has_more:
                    bg_job.progress = 100
                else:
                    # Estimate progress — we can't know total, so cap at 95
                    bg_job.progress = min(95, batch_num * 10)
                session.add(bg_job)
                await session.commit()

                if not batch.has_more:
                    break

            ds.status = IngestionStatus.COMPLETED
            ds.row_count = total_rows
            ds.last_sync = datetime.now(UTC)
            ds.error_message = None
            session.add(ds)
            await session.commit()

            await log_action(
                session, project_id, AuditAction.DATA_INGESTED,
                detail={"data_source_id": data_source_id, "row_count": total_rows},
            )

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = {"total_rows": total_rows, "batches": batch_num}

        except Exception as exc:
            logger.exception("Ingestion job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return bg_job.result_summary or {}
