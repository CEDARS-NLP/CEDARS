"""ARQ worker configuration.

Run with: arq app.worker.WorkerSettings
"""

import logging
from urllib.parse import urlparse

from arq.connections import RedisSettings

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


async def run_ingestion_job(ctx: dict, project_id: str, job_db_id: str, data_source_id: str) -> dict:
    """ARQ task: run data ingestion for a data source."""
    from app.jobs.ingestion import execute_ingestion_job

    return await execute_ingestion_job(project_id, job_db_id, data_source_id)


async def run_export_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: generate export. (Placeholder)"""
    return {"status": "not_implemented"}


async def run_pipeline_job(ctx: dict, pipeline_run_id: str) -> dict:
    """ARQ task: execute a pipeline run (search + classify per patient)."""
    from app.jobs.pipeline import execute_pipeline_run

    return await execute_pipeline_run(pipeline_run_id)


class WorkerSettings:
    functions = [run_nlp_job, run_prediction_job, run_ingestion_job, run_export_job, run_pipeline_job]
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
