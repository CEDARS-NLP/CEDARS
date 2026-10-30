"""Explicit global lookups for project metadata needed by tenant workflows."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import global_session_factory
from app.projects.models import Project


async def load_project(project_id: str) -> Project | None:
    """Fetch project configuration from the global registry, never a tenant session."""
    async with global_session_factory() as session:
        project = await session.get(Project, project_id)
        if project is None:
            return None
        await session.refresh(project)
        return project


async def require_ready_project_context(project_id: str):
    """Resolve a background task's project ID through the global registry."""
    from app.common.context import ProjectContext

    project = await load_project(project_id)
    if (
        project is None
        or project.deleted_at is not None
        or project.database_status != "ready"
        or not project.database_secret_ref
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project database is not ready",
        )
    return ProjectContext(project_id=project_id, routing_version=project.routing_version)


async def get_project_session_factory_for_id(project_id: str):
    """Resolve a project ID from global metadata and return its tenant factory."""
    from app.common.database import get_project_session_factory

    context = await require_ready_project_context(project_id)
    return await get_project_session_factory(context)


async def list_ready_project_contexts():
    """List trusted routing contexts for projects whose tenant DB is ready."""
    from sqlalchemy import select

    from app.common.context import ProjectContext
    from app.common.database import global_session_factory

    async with global_session_factory() as session:
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


async def load_project_in_session(session: AsyncSession, project_id: str) -> Project | None:
    """Fetch project metadata when a caller already owns a global session."""
    return await session.get(Project, project_id)
