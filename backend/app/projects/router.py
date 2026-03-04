"""Project API router: CRUD and membership endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import get_current_user, require_project_role
from app.projects.models import ProjectRole
from app.projects.schemas import (
    AddMemberRequest,
    CreateProjectRequest,
    ProjectMemberResponse,
    ProjectResponse,
    UpdateProjectRequest,
)
from app.projects.stats import get_project_stats
from app.projects.service import (
    add_member,
    create_project,
    delete_project,
    get_project,
    get_user_project_role,
    list_members,
    list_user_projects,
    remove_member,
    update_project,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _project_response(project, role: str | None = None) -> dict:
    """Convert a Project model to a response dict."""
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "settings": project.settings,
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "role": role,
    }


# --- Project CRUD ---


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    body: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new project. The authenticated user becomes the admin."""
    project = await create_project(session, current_user, body.name, body.description)
    return _project_response(project, role=ProjectRole.ADMIN.value)


@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List all projects the authenticated user is a member of."""
    results = await list_user_projects(session, current_user.id)
    return [_project_response(project, role=role.value) for project, role in results]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
    session: AsyncSession = Depends(get_session),
):
    """Get project details. Requires project membership."""
    project = await get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    role = await get_user_project_role(session, project_id, current_user.id)
    return _project_response(project, role=role.value if role else None)


@router.get("/{project_id}/stats")
async def project_stats_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
    session: AsyncSession = Depends(get_session),
):
    """Get comprehensive project statistics."""
    return await get_project_stats(session, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project_endpoint(
    project_id: str,
    body: UpdateProjectRequest,
    current_user: User = Depends(require_project_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    """Update project details. Requires admin role."""
    updates = body.model_dump(exclude_none=True)
    project = await update_project(session, project_id, updates)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    role = await get_user_project_role(session, project_id, current_user.id)
    return _project_response(project, role=role.value if role else None)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    """Soft-delete a project. Requires admin role."""
    deleted = await delete_project(session, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return None


# --- Membership ---


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member_endpoint(
    project_id: str,
    body: AddMemberRequest,
    current_user: User = Depends(require_project_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    """Add a member to the project by email. Requires admin role."""
    member = await add_member(session, project_id, body.email, body.role)
    if not member:
        raise HTTPException(status_code=404, detail="User not found")
    # Fetch user info for the response
    from sqlmodel import select
    from app.auth.models import User as UserModel
    result = await session.execute(
        select(UserModel).where(UserModel.id == member.user_id)
    )
    user = result.scalar_one()
    return ProjectMemberResponse(
        user_id=member.user_id,
        email=user.email,
        name=user.name,
        role=member.role.value,
    )


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def list_members_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
    session: AsyncSession = Depends(get_session),
):
    """List all members of the project. Requires project membership."""
    members = await list_members(session, project_id)
    return [
        ProjectMemberResponse(
            user_id=member.user_id,
            email=user.email,
            name=user.name,
            role=member.role.value,
        )
        for member, user in members
    ]


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member_endpoint(
    project_id: str,
    user_id: str,
    current_user: User = Depends(require_project_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    """Remove a member from the project. Requires admin role."""
    removed = await remove_member(session, project_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return None
