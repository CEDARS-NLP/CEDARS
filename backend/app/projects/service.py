"""Business logic for project CRUD and membership management."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.models import User
from app.projects.models import Project, ProjectMember, ProjectRole


# --- Project CRUD ---


async def create_project(
    session: AsyncSession,
    user: User,
    name: str,
    description: str = "",
) -> Project:
    """Create a new project and add the creating user as an admin member."""
    project = Project(name=name, description=description, owner_id=user.id)
    session.add(project)
    await session.flush()

    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=ProjectRole.ADMIN,
    )
    session.add(member)
    await session.commit()
    await session.refresh(project)
    return project


async def list_user_projects(
    session: AsyncSession,
    user_id: str,
) -> list[tuple[Project, ProjectRole]]:
    """Return all non-deleted projects where the user is a member, with their role."""
    stmt = (
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .where(Project.deleted_at.is_(None))  # type: ignore[union-attr]
    )
    results = await session.execute(stmt)
    return list(results.all())


async def get_project(
    session: AsyncSession,
    project_id: str,
) -> Project | None:
    """Return a project by ID, excluding soft-deleted projects."""
    stmt = select(Project).where(
        Project.id == project_id,
        Project.deleted_at.is_(None),  # type: ignore[union-attr]
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_project(
    session: AsyncSession,
    project_id: str,
    updates: dict,
) -> Project | None:
    """Update a project's name, description, or settings."""
    project = await get_project(session, project_id)
    if not project:
        return None

    for key, value in updates.items():
        if value is not None:
            setattr(project, key, value)

    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(
    session: AsyncSession,
    project_id: str,
) -> bool:
    """Soft-delete a project by setting deleted_at."""
    project = await get_project(session, project_id)
    if not project:
        return False

    project.deleted_at = datetime.now(UTC)
    session.add(project)
    await session.commit()
    return True


# --- Membership ---


async def get_user_project_role(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> ProjectRole | None:
    """Return the user's role in a project, or None if not a member."""
    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
    )
    result = await session.execute(stmt)
    member = result.scalar_one_or_none()
    return member.role if member else None


async def get_member(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> ProjectMember | None:
    """Return the ProjectMember record or None."""
    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def add_member(
    session: AsyncSession,
    project_id: str,
    user_email: str,
    role: str = "annotator",
) -> ProjectMember | None:
    """Add a user to a project by email. Returns the membership or None if user not found."""
    # Look up user by email
    stmt = select(User).where(User.email == user_email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return None

    # Check if already a member
    existing = await get_member(session, project_id, user.id)
    if existing:
        return existing

    member = ProjectMember(
        project_id=project_id,
        user_id=user.id,
        role=ProjectRole(role),
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return member


async def list_members(
    session: AsyncSession,
    project_id: str,
) -> list[tuple[ProjectMember, User]]:
    """List all members of a project with their user info."""
    stmt = (
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def remove_member(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> bool:
    """Remove a member from a project. Returns True if removed."""
    member = await get_member(session, project_id, user_id)
    if not member:
        return False

    await session.delete(member)
    await session.commit()
    return True
