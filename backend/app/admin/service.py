"""Business logic for admin queue monitoring."""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import BackgroundJob, JobStatus

logger = logging.getLogger(__name__)


async def get_queue_stats(session: AsyncSession) -> list[dict]:
    """Get job counts grouped by type and status."""
    stmt = (
        select(BackgroundJob.job_type, BackgroundJob.status, func.count(BackgroundJob.id))
        .group_by(BackgroundJob.job_type, BackgroundJob.status)
    )
    result = await session.execute(stmt)
    rows = result.all()

    type_stats: dict[str, dict[str, int]] = {}
    for job_type, status, count in rows:
        jt = job_type.value if hasattr(job_type, "value") else job_type
        if jt not in type_stats:
            type_stats[jt] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        st = status.value if hasattr(status, "value") else status
        type_stats[jt][st] = count

    return [
        {
            "name": job_type,
            "pending": stats.get("pending", 0),
            "active": stats.get("running", 0),
            "complete": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
        }
        for job_type, stats in type_stats.items()
    ]


async def get_worker_info() -> list[dict]:
    """Get active ARQ worker info from Redis. Returns empty if unavailable."""
    try:
        from arq import create_pool
        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        health_val = await redis.get("arq:queue:health-check")
        workers = []
        if health_val is not None:
            workers.append({
                "name": "arq-worker",
                "queue": "arq:queue",
                "current_job": health_val.decode() if isinstance(health_val, bytes) else str(health_val),
            })
        await redis.aclose()
        return workers
    except Exception:
        logger.debug("Redis unavailable for worker info")
        return []


async def list_jobs(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BackgroundJob]:
    """List background jobs, optionally filtered by status."""
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    if status:
        stmt = stmt.where(BackgroundJob.status == status)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
