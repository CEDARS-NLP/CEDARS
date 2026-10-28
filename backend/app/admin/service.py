"""Business logic for admin queue monitoring."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.common.context import ProjectContext
from app.common.database import get_project_session_factory
from app.jobs.models import BackgroundJob
from app.projects.models import Project

logger = logging.getLogger(__name__)


async def _ready_project_contexts(session: AsyncSession) -> list[ProjectContext]:
    result = await session.execute(
        select(Project).where(
            Project.deleted_at.is_(None),
            Project.database_status == "ready",
            Project.database_secret_ref.is_not(None),
        )
    )
    projects = result.scalars().all()
    return [
        ProjectContext(project_id=project.id, routing_version=project.routing_version)
        for project in projects
    ]


async def get_all_queue_stats(global_session: AsyncSession) -> list[dict]:
    """Aggregate job counts across ready project databases."""
    totals: dict[str, dict[str, int]] = {}
    for context in await _ready_project_contexts(global_session):
        factory = await get_project_session_factory(context)
        async with factory() as session:
            for item in await get_queue_stats(session):
                stats = totals.setdefault(
                    item["name"], {"pending": 0, "active": 0, "complete": 0, "failed": 0}
                )
                for key in ("pending", "active", "complete", "failed"):
                    stats[key] += item[key]
    return [{"name": name, **stats} for name, stats in sorted(totals.items())]


async def list_all_jobs(
    global_session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BackgroundJob]:
    """List jobs across ready project databases, ordered newest first."""
    candidates: list[BackgroundJob] = []
    fetch_limit = offset + limit
    for context in await _ready_project_contexts(global_session):
        factory = await get_project_session_factory(context)
        async with factory() as session:
            candidates.extend(
                await list_jobs(session, status=status, limit=fetch_limit, offset=0)
            )
    candidates.sort(key=lambda job: job.created_at, reverse=True)
    return candidates[offset : offset + limit]


async def get_queue_stats(session: AsyncSession) -> list[dict]:
    """Get job counts grouped by type and status."""
    stmt = (
        select(
            col(BackgroundJob.job_type),
            col(BackgroundJob.status),
            func.count(col(BackgroundJob.id)),
        )
        .group_by(col(BackgroundJob.job_type), col(BackgroundJob.status))
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
                "current_job": health_val.decode() if isinstance(health_val,
                                                                 bytes) else str(health_val),
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
    stmt = select(BackgroundJob).order_by(col(BackgroundJob.created_at).desc())
    if status:
        stmt = stmt.where(col(BackgroundJob.status) == status)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
