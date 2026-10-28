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


async def run_pipeline_job(ctx: dict, project_id: str, pipeline_run_id: str) -> dict:
    """ARQ task: orchestrate a pipeline run — enqueues per-patient jobs,
        monitors, circuit-breaks."""
    from app.jobs.pipeline import execute_pipeline_run

    return await execute_pipeline_run(project_id, pipeline_run_id)


async def run_patient_task(
    ctx: dict, project_id: str, pipeline_run_id: str, patient_task_id: int
) -> dict:
    """ARQ task: process a single patient (search + classify). One message per patient."""
    from app.jobs.pipeline import process_single_patient

    return await process_single_patient(project_id, pipeline_run_id, patient_task_id)


async def run_sample_llm_job(ctx: dict, session_id: str, project_id: str) -> dict:
    """ARQ task: run LLM classification on matched patients in an evaluation sample."""
    from app.evaluation.service import execute_sample_llm

    return await execute_sample_llm(session_id, project_id)


async def run_eval_pipeline_job(ctx: dict, project_id: str, run_id: str) -> dict:
    """Execute the production note-level run linked to an evaluation session."""
    from app.common.project_registry import get_project_session_factory_for_id
    from app.production.service import ProductionError, execute_run

    session_factory = await get_project_session_factory_for_id(project_id)
    async with session_factory() as db:
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


async def finalize_patient_review_job(ctx: dict, project_id: str, job_id: str) -> dict:
    """Apply one durable patient-level review batch."""
    from app.jobs.review import execute_patient_review_job

    return await execute_patient_review_job(project_id, job_id)


async def recover_patient_review_jobs_task(ctx: dict) -> None:
    """Periodically re-enqueue durable batches that missed their Redis enqueue."""
    from app.common.database import get_project_session_factory
    from app.common.project_registry import list_ready_project_contexts
    from app.jobs.review import recover_patient_review_jobs

    for context in await list_ready_project_contexts():
        session_factory = await get_project_session_factory(context)
        await recover_patient_review_jobs(context.project_id, session_factory)


async def on_worker_startup(ctx: dict) -> None:
    """Re-enqueue orphaned production runs; legacy pipeline jobs stay fenced."""
    log = logging.getLogger("arq.worker.startup")
    try:
        from app.common.project_database import configure_project_database_routing

        configure_project_database_routing()
        from sqlalchemy import select
        from sqlmodel import col

        from app.common.database import get_project_session_factory
        from app.common.project_registry import list_ready_project_contexts
        from app.jobs.review import recover_patient_review_jobs
        from app.production.models import ProductionRun

        for context in await list_ready_project_contexts():
            session_factory = await get_project_session_factory(context)
            async with session_factory() as db:
                orphaned_runs = list(
                    await db.scalars(
                        select(ProductionRun).where(
                            col(ProductionRun.status).in_(["queued", "running"])
                        )
                    )
                )
                from app.evaluation.service import _enqueue_eval_pipeline_run

                for run in orphaned_runs:
                    await _enqueue_eval_pipeline_run(context.project_id, run.id)
                    log.info("Re-enqueued orphaned production run %s", run.id)
                if not orphaned_runs:
                    log.info("No orphaned production runs to recover for %s", context.project_id)
            await recover_patient_review_jobs(context.project_id, session_factory)
    except Exception:
        log.exception("Failed to auto-recover orphaned pipeline runs")


async def on_worker_shutdown(ctx: dict) -> None:
    """Dispose tenant engine pools when the ARQ process exits."""
    from app.common.database import dispose_project_engines

    await dispose_project_engines()


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
    on_shutdown = on_worker_shutdown
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
    # We handle retries ourselves (litellm for LLM, circuit breaker for runs).
    # ARQ-level retry would re-run jobs whose DB state is already marked FAILED.
    max_tries = 1
