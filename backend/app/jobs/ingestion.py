"""Ingestion pipeline ARQ job implementation."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.common.utils import now_utc
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
        bg_job.started_at = now_utc()
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

            inserted_rows = 0
            file_rows = 0
            offset = 0
            batch_size = 1000
            batch_num = 0

            def _summary() -> dict:
                return {
                    "total_rows": file_rows,
                    "inserted_rows": inserted_rows,
                    "skipped_rows": file_rows - inserted_rows,
                    "batches": batch_num,
                }

            while True:
                # Check cancellation between batches
                await session.refresh(bg_job)
                if bg_job.is_cancelled:
                    ds.status = IngestionStatus.FAILED
                    ds.error_message = "Cancelled by user"
                    session.add(ds)
                    bg_job.status = JobStatus.CANCELLED
                    bg_job.completed_at = now_utc()
                    bg_job.result_summary = _summary()
                    session.add(bg_job)
                    await session.commit()
                    return bg_job.result_summary

                batch = await connector.fetch(ds.config, batch_size=batch_size, offset=offset)
                if not batch.rows:
                    break

                # Use connector-reported total if available
                if batch.total_rows is not None:
                    file_rows = batch.total_rows
                else:
                    file_rows = offset + len(batch.rows)

                mapping = ds.config.get("column_mapping", {})
                count = await _ingest_rows(session, project_id, ds.id, batch.rows, mapping)
                inserted_rows += count
                offset += batch_size
                batch_num += 1

                # Update progress
                bg_job.result_summary = _summary()
                if not batch.has_more:
                    bg_job.progress = 100
                elif file_rows > 0:
                    bg_job.progress = min(95, int(offset / file_rows * 100))
                else:
                    bg_job.progress = min(95, batch_num * 10)
                session.add(bg_job)
                await session.commit()

                if not batch.has_more:
                    break

            ds.status = IngestionStatus.COMPLETED
            ds.row_count = inserted_rows
            ds.last_sync = now_utc()
            ds.error_message = None
            session.add(ds)
            await session.commit()

            await log_action(
                session, project_id, AuditAction.DATA_INGESTED,
                detail={"data_source_id": data_source_id, "row_count": inserted_rows},
            )

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = now_utc()
            bg_job.result_summary = _summary()

        except Exception as exc:
            logger.exception("Ingestion job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return bg_job.result_summary or {}
