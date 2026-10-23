"""ARQ worker configuration.

Run with: arq app.worker.WorkerSettings
"""

import logging
from urllib.parse import urlparse

from arq import cron
from arq.connections import RedisSettings

import app.annotations.models  # noqa: F401
import app.annotations.review_jobs  # noqa: F401

# Import ALL models at worker startup so SQLAlchemy can resolve foreign keys.
# The ARQ worker runs in a separate process without the FastAPI app context.
import app.auth.models  # noqa: F401
import app.connectors.models  # noqa: F401
import app.evaluation.models  # noqa: F401  # Phase 1: unified eval models
import app.nlp.models  # noqa: F401
import app.pipeline.models  # noqa: F401
import app.production.models  # noqa: F401
import app.projects.models  # noqa: F401
from app.common.utils import now_utc
from app.config import settings

logger = logging.getLogger(__name__)

def parse_redis_settings() -> RedisSettings:
    """Parse CEDARS redis_url into ARQ RedisSettings."""
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def run_nlp_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run NLP pipeline for a project."""
    from app.jobs.nlp import execute_nlp_job

    return await execute_nlp_job(project_id, job_db_id)


async def run_prediction_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run bulk predictions with per-patient batching."""
    from app.jobs.prediction import execute_prediction_job

    return await execute_prediction_job(project_id, job_db_id)


async def run_ingestion_job(ctx: dict, project_id: str,
                            job_db_id: str, data_source_id: str) -> dict:
    """ARQ task: run data ingestion for a data source."""
    from app.jobs.ingestion import execute_ingestion_job

    return await execute_ingestion_job(project_id, job_db_id, data_source_id)


async def run_export_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: generate export. (Placeholder)"""
    return {"status": "not_implemented"}


async def run_pipeline_job(ctx: dict, pipeline_run_id: str) -> dict:
    """ARQ task: orchestrate a pipeline run — enqueues per-patient jobs,
        monitors, circuit-breaks."""
    from app.jobs.pipeline import execute_pipeline_run

    return await execute_pipeline_run(pipeline_run_id)


async def run_patient_task(ctx: dict, pipeline_run_id: str, patient_task_id: int) -> dict:
    """ARQ task: process a single patient (search + classify). One message per patient."""
    from app.jobs.pipeline import process_single_patient

    return await process_single_patient(pipeline_run_id, patient_task_id)


async def run_sample_llm_job(ctx: dict, session_id: str, project_id: str) -> dict:
    """ARQ task: run LLM classification on matched patients in an evaluation sample."""
    from app.evaluation.service import execute_sample_llm

    return await execute_sample_llm(session_id, project_id)


async def run_eval_pipeline_job(ctx: dict, run_id: str) -> dict:
    """Execute the production note-level run linked to an evaluation session."""
    from app.common.database import async_session
    from app.production.service import ProductionError, execute_run

    async with async_session() as db:
        try:
            run = await execute_run(db, run_id)
        except ProductionError as exc:
            return {"error": str(exc)}
        session_id = (run.config_snapshot or {}).get("evaluation_session_id")
        if run.status == "completed" and session_id:
            from app.evaluation.models import EvaluationSession, SessionStatus

            session = await db.get(EvaluationSession, session_id)
            if session and session.status == SessionStatus.COMMITTED:
                session.status = SessionStatus.COMPLETED
                session.updated_at = now_utc()
                await db.commit()
        return {"processed": run.completed_notes, "failed": run.failed_notes}


async def finalize_patient_review_job(ctx: dict, job_id: str) -> dict:
    """Apply one durable patient-level review batch."""
    from app.jobs.review import execute_patient_review_job

    return await execute_patient_review_job(job_id)


async def recover_patient_review_jobs_task(ctx: dict) -> None:
    """Periodically re-enqueue durable batches that missed their Redis enqueue."""
    from app.common.database import async_session
    from app.jobs.review import recover_patient_review_jobs

    await recover_patient_review_jobs(async_session)


async def on_worker_startup(ctx: dict) -> None:
    """Re-enqueue orphaned production runs; legacy pipeline jobs stay fenced."""
    log = logging.getLogger("arq.worker.startup")
    try:
        from sqlalchemy import select

        from app.common.database import async_session
        from app.jobs.review import recover_patient_review_jobs
        from app.production.models import ProductionRun

        async with async_session() as db:
            orphaned_runs = list(
                await db.scalars(
                    select(ProductionRun).where(
                        ProductionRun.status.in_(["queued", "running"])
                    )
                )
            )
            from app.evaluation.service import _enqueue_eval_pipeline_run

            for run in orphaned_runs:
                await _enqueue_eval_pipeline_run(run.id)
                log.info("Re-enqueued orphaned production run %s", run.id)
            if not orphaned_runs:
                log.info("No orphaned production runs to recover")
        recovered_review_jobs = await recover_patient_review_jobs(async_session)
        log.info("Recovered %s queued or stale patient review jobs", recovered_review_jobs)
    except Exception:
        log.exception("Failed to auto-recover orphaned pipeline runs")


class WorkerSettings:
    functions = [
        run_nlp_job,
        run_prediction_job,
        run_ingestion_job,
        run_export_job,
        run_pipeline_job,
        run_patient_task,
        run_sample_llm_job,
        run_eval_pipeline_job,
        finalize_patient_review_job,
    ]
    cron_jobs = [
        cron(recover_patient_review_jobs_task, minute=set(range(0, 60, 5)))
    ]
    on_startup = on_worker_startup
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
    # We handle retries ourselves (litellm for LLM, circuit breaker for runs).
    # ARQ-level retry would re-run jobs whose DB state is already marked FAILED.
    max_tries = 1
