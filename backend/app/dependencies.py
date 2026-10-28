"""Shared FastAPI dependencies for authentication and authorization."""

from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from jwt import ExpiredSignatureError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from app.auth.models import User
from app.auth.service import decode_token
from app.common.context import ProjectContext
from app.common.database import (
    get_global_session,
    get_project_engine,
)
from app.projects.models import Project, ProjectMember, ProjectRole, ProjectUser


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_global_session),
) -> User:
    """Validate JWT from httpOnly cookie and return the authenticated user."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(token)
    except ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_project_role(*allowed_roles: str):
    """Return a dependency that checks the user has one of the allowed roles in the project.

    Platform admins also require explicit project membership for project data.
    """

    async def dependency(
        project_id: str,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_global_session),
    ) -> User:
        # Import here to avoid circular imports
        from app.projects.service import get_member

        member = await get_member(session, project_id, current_user.id)
        if not member or member.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency


async def get_project_context(
    project_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_global_session),
) -> ProjectContext:
    """Authorize project membership and return trusted tenant routing metadata."""
    project = await session.get(Project, project_id)
    member = await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not project or project.deleted_at is not None or not member or not member.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if project.database_status != "ready" or not project.database_secret_ref:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project database is not ready",
        )
    return ProjectContext(project_id=project_id, routing_version=project.routing_version)


async def get_project_db_session(
    context: ProjectContext = Depends(get_project_context),
    current_user: User = Depends(get_current_user),
    global_session: AsyncSession = Depends(get_global_session),
) -> AsyncGenerator[AsyncSession, None]:
    """Open a tenant session after projecting current global membership locally."""
    project_engine = await get_project_engine(context)
    factory = async_sessionmaker(project_engine, class_=AsyncSession, expire_on_commit=False)
    member = await global_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == context.project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not member or not member.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    async with factory() as project_session:
        project = await global_session.get(Project, context.project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if member.added_by_user_id and member.added_by_user_id != current_user.id:
            actor = await global_session.get(User, member.added_by_user_id)
            if actor and await project_session.get(ProjectUser, actor.id) is None:
                project_session.add(
                    ProjectUser(
                        global_user_id=actor.id,
                        project_id=context.project_id,
                        email=actor.email,
                        name=actor.name,
                        role=ProjectRole.VIEWER,
                        is_active=False,
                        added_by_kind="unknown",
                    )
                )
                await project_session.flush()

        local_member = await project_session.get(ProjectUser, current_user.id)
        if local_member is None:
            local_member = ProjectUser(
                global_user_id=current_user.id,
                project_id=context.project_id,
                email=current_user.email,
                name=current_user.name,
                role=member.role,
                is_investigator=member.user_id == project.owner_id,
                is_active=True,
                added_by_kind=member.added_by_kind,
                added_by_user_id=member.added_by_user_id,
                membership_revision=member.membership_revision,
            )
            project_session.add(local_member)
        else:
            local_member.email = current_user.email
            local_member.name = current_user.name
            local_member.role = member.role
            local_member.is_active = True
            local_member.revoked_at = None
            local_member.is_investigator = member.user_id == project.owner_id
            local_member.added_by_kind = member.added_by_kind
            local_member.added_by_user_id = member.added_by_user_id
            local_member.membership_revision = member.membership_revision
        await project_session.commit()
        member.synced_revision = member.membership_revision
        global_session.add(member)
        await global_session.commit()
        yield project_session
