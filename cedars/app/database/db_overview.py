"""Project-local queries that supply the Overview data-source and job panels."""
from sqlalchemy import select

from .db_session import session_scope
from .project_table_creation import BackgroundJobs, DataSources


def list_data_sources(project_engine, limit: int = 20) -> list[DataSources]:
    """Return active sources for one project, newest first."""
    with session_scope(project_engine) as session:
        return list(session.scalars(
            select(DataSources)
            .where(DataSources.deleted_at.is_(None))
            .order_by(DataSources.created_at.desc())
            .limit(limit)
        ))


def list_recent_jobs(project_engine, limit: int = 20) -> list[BackgroundJobs]:
    """Return durable ARQ lifecycle records for one project, newest first."""
    with session_scope(project_engine) as session:
        return list(session.scalars(
            select(BackgroundJobs)
            .order_by(BackgroundJobs.created_at.desc())
            .limit(limit)
        ))