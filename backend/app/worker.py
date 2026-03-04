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
    """ARQ task: run bulk predictions. (Placeholder)"""
    return {"status": "not_implemented"}


async def run_export_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: generate export. (Placeholder)"""
    return {"status": "not_implemented"}


class WorkerSettings:
    functions = [run_nlp_job, run_prediction_job, run_export_job]
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
