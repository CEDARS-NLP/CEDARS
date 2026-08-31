"""Project management routes: list / create / get / update.

Projects are the one multi-tenant feature retained from the v2 frontend. Each
project owns its own Postgres database (see :mod:`app.database`); the global
Projects table lists them. Every workflow within a project is identical to the
original single-project Flask app.
"""
from fastapi import APIRouter, Depends

from ..database import get_global_engine
from ..database.db_projects import (delete_project_registry, list_projects,
                                    update_project_description,
                                    update_project_name)
from ..database.init_db import drop_project_database, initialize_project
from ..dependencies import (ProjectContext, require_project,
                            require_project_admin)
from ..schemas import MessageResponse, ProjectCreate, ProjectOut, ProjectUpdate
from ..security import CurrentUser, get_current_user, require_admin

router = APIRouter(prefix="/projects", tags=["projects"])


def _role_for(user: CurrentUser) -> str:
    """Map the global admin flag onto the per-project role label."""
    return "admin" if user.is_admin else "annotator"


def _to_project_out(project, role: str) -> ProjectOut:
    created = project.creation_time
    return ProjectOut(
        id=project.project_id,
        name=project.project_name or "",
        description=project.description or "",
        owner=project.investigator,
        role=role,
        created_at=created.isoformat() if hasattr(created, "isoformat") else created,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(user: CurrentUser = Depends(get_current_user)):
    """List all projects (global roles: every user may open any project)."""
    role = _role_for(user)
    return [_to_project_out(project, role) for project in list_projects(get_global_engine())]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, admin: CurrentUser = Depends(require_admin)):
    """Create a new project (admin only) with its own database + registry entry."""
    name = (payload.name or "").strip()
    project_id = initialize_project(name, admin.username, "0.1.0",
                                    description=payload.description or "")
    project = next((p for p in list_projects(get_global_engine())
                    if p.project_id == project_id), None)
    return _to_project_out(project, role="admin")


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(ctx: ProjectContext = Depends(require_project)):
    """Return a single project's details."""
    project = next((p for p in list_projects(get_global_engine())
                    if p.project_id == ctx.project_id), None)
    return _to_project_out(project, role=_role_for(ctx.user))


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(payload: ProjectUpdate,
                   ctx: ProjectContext = Depends(require_project_admin)):
    """Update a project's name/description (admin only)."""
    if payload.name is not None and payload.name.strip():
        update_project_name(get_global_engine(), ctx.project_id, payload.name.strip())
    if payload.description is not None:
        update_project_description(get_global_engine(), ctx.project_id, payload.description)

    project = next((p for p in list_projects(get_global_engine())
                    if p.project_id == ctx.project_id), None)
    return _to_project_out(project, role="admin")


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(ctx: ProjectContext = Depends(require_project_admin)):
    """Terminate a project: drop its database and registry entry (admin only)."""
    drop_project_database(ctx.project_id)
    delete_project_registry(get_global_engine(), ctx.project_id)
    return MessageResponse(message="Project Terminated.")

