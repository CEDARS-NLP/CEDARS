"""Project management routes: list / create / get / update.

Projects are the one multi-tenant feature retained from the v2 frontend. Each
project owns its own Postgres database (see :mod:`app.database`); the global
Projects table lists them. Every workflow within a project is identical to the
original single-project Flask app.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..database import get_current_project_engine, get_global_engine
from ..database.db_auth import (count_project_admins, get_project_membership,
                                get_user, list_project_members,
                                list_user_project_memberships,
                                remove_project_member,
                                set_project_member_admin)
from ..database.db_inserts import add_user_to_project
from ..database.db_projects import (delete_project_registry,
                                    list_projects as list_project_rows,
                                    update_project_description,
                                    update_project_name)
from ..database.init_db import drop_project_database, initialize_project
from ..dependencies import (ProjectContext, require_project,
                            require_project_admin)
from ..rq_dashboard_gateway import forget_dashboard_app
from ..schemas import (MessageResponse, ProjectCreate, ProjectMemberCreate,
                       ProjectMemberOut, ProjectMemberUpdate, ProjectOut,
                       ProjectUpdate)
from ..security import CurrentUser, get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


def _role_for(is_project_admin: bool) -> str:
    """Map a project membership flag onto the UI role label."""
    return "admin" if is_project_admin else "annotator"


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


def _role_is_admin(role: str) -> bool:
    return role == "admin"


def _member_out(member: dict) -> ProjectMemberOut:
    return ProjectMemberOut(**member)


@router.get("", response_model=list[ProjectOut])
def list_projects(user: CurrentUser = Depends(get_current_user)):
    """List projects assigned to the authenticated user."""
    global_engine = get_global_engine()
    memberships = list_user_project_memberships(global_engine, user.username)
    return [
        _to_project_out(project, _role_for(memberships[project.project_id]))
        for project in list_project_rows(global_engine)
        if project.project_id in memberships
    ]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate,
                   user: CurrentUser = Depends(get_current_user)):
    """Create a new project with its own database + registry entry."""
    name = (payload.name or "").strip()
    project_id = initialize_project(name, user.username, "0.1.0",
                                    description=payload.description or "")
    project = next((p for p in list_project_rows(get_global_engine())
                    if p.project_id == project_id), None)
    return _to_project_out(project, role="admin")


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(ctx: ProjectContext = Depends(require_project)):
    """Return a single project's details."""
    project = next((p for p in list_project_rows(get_global_engine())
                    if p.project_id == ctx.project_id), None)
    membership = get_project_membership(get_global_engine(), ctx.project_id,
                                        ctx.user.username)
    return _to_project_out(project, role=_role_for(membership.has_admin_privileges))


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(payload: ProjectUpdate,
                   ctx: ProjectContext = Depends(require_project_admin)):
    """Update a project's name/description (admin only)."""
    if payload.name is not None and payload.name.strip():
        update_project_name(get_global_engine(), ctx.project_id, payload.name.strip())
    if payload.description is not None:
        update_project_description(get_global_engine(), ctx.project_id, payload.description)

    project = next((p for p in list_project_rows(get_global_engine())
                    if p.project_id == ctx.project_id), None)
    return _to_project_out(project, role="admin")


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(ctx: ProjectContext = Depends(require_project_admin)):
    """Terminate a project: drop its database and registry entry (admin only)."""
    drop_project_database(ctx.project_id)
    delete_project_registry(get_global_engine(), ctx.project_id)
    forget_dashboard_app(ctx.project_id)
    return MessageResponse(message="Project Terminated.")


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
def get_project_members(ctx: ProjectContext = Depends(require_project_admin)):
    """List project members and their project-scoped roles."""
    return [_member_out(member)
            for member in list_project_members(get_global_engine(), ctx.project_id)]


@router.post("/{project_id}/members", response_model=ProjectMemberOut,
             status_code=201)
def add_project_member(payload: ProjectMemberCreate,
                       ctx: ProjectContext = Depends(require_project_admin)):
    """Add an existing registered user to a project."""
    username = (payload.username or "").strip()
    global_engine = get_global_engine()
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Username is required.")
    if get_user(global_engine, username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "User not found.")
    if get_project_membership(global_engine, ctx.project_id, username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "User is already a project member.")

    add_user_to_project(global_engine, get_current_project_engine(), username,
                        ctx.user.username, _role_is_admin(payload.role),
                        ctx.project_id)
    return ProjectMemberOut(username=username, role=payload.role,
                            added_by=ctx.user.username)


@router.patch("/{project_id}/members/{username}", response_model=ProjectMemberOut)
def update_project_member(username: str, payload: ProjectMemberUpdate,
                          ctx: ProjectContext = Depends(require_project_admin)):
    """Update a project member's role."""
    global_engine = get_global_engine()
    membership = get_project_membership(global_engine, ctx.project_id, username)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Project member not found.")
    if username == ctx.info.get("investigator") and payload.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Project investigator must remain an admin.")
    if membership.has_admin_privileges and payload.role != "admin" and \
            count_project_admins(global_engine, ctx.project_id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A project must have at least one admin.")

    set_project_member_admin(global_engine, get_current_project_engine(),
                             ctx.project_id, username, _role_is_admin(payload.role))
    return ProjectMemberOut(username=username, role=payload.role,
                            added_by=membership.added_by)


@router.delete("/{project_id}/members/{username}", response_model=MessageResponse)
def delete_project_member(username: str,
                          ctx: ProjectContext = Depends(require_project_admin)):
    """Remove a member from a project."""
    global_engine = get_global_engine()
    membership = get_project_membership(global_engine, ctx.project_id, username)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Project member not found.")
    if username == ctx.info.get("investigator"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Project investigator cannot be removed.")
    if membership.has_admin_privileges and \
            count_project_admins(global_engine, ctx.project_id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A project must have at least one admin.")

    remove_project_member(global_engine, get_current_project_engine(),
                          ctx.project_id, username)
    return MessageResponse(message="Project member removed.")

