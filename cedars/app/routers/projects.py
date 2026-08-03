"""Project management routes: list / create / get / update.

Projects are the one multi-tenant feature retained from the v2 frontend. Each
project owns its own Mongo database (see :mod:`app.database`); a global registry
in the metadata DB lists them. Every workflow within a project is identical to
the original single-project Flask app.
"""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends

from .. import db
from ..database import (get_client, get_meta_db, project_db_name,
                        reset_current_project_db, set_current_project_db)
from ..dependencies import (ProjectContext, require_project,
                            require_project_admin)
from ..schemas import MessageResponse, ProjectCreate, ProjectOut, ProjectUpdate
from ..security import CurrentUser, get_current_user, require_admin

router = APIRouter(prefix="/projects", tags=["projects"])


def _role_for(user: CurrentUser) -> str:
    """Map the global admin flag onto the per-project role label."""
    return "admin" if user.is_admin else "annotator"


def _to_project_out(doc: dict, role: str) -> ProjectOut:
    created = doc.get("created_at")
    return ProjectOut(
        id=doc["project_id"],
        name=doc.get("name", ""),
        description=doc.get("description", ""),
        owner=doc.get("owner"),
        role=role,
        created_at=created.isoformat() if hasattr(created, "isoformat") else created,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(user: CurrentUser = Depends(get_current_user)):
    """List all projects (global roles: every user may open any project)."""
    role = _role_for(user)
    projects = get_meta_db()["PROJECTS"].find().sort("created_at", 1)
    return [_to_project_out(doc, role) for doc in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, admin: CurrentUser = Depends(require_admin)):
    """Create a new project (admin only) with its own database + registry entry."""
    project_id = str(uuid4())
    name = (payload.name or "").strip()

    # Initialize the project's own database (collections, indexes, INFO doc).
    token = set_current_project_db(project_db_name(project_id))
    try:
        db.create_project(project_name=name,
                          investigator_name=admin.username,
                          project_id=project_id)
    finally:
        reset_current_project_db(token)

    registry_doc = {
        "project_id": project_id,
        "name": name,
        "description": payload.description or "",
        "owner": admin.username,
        "created_at": datetime.now(timezone.utc),
    }
    get_meta_db()["PROJECTS"].insert_one(registry_doc)
    return _to_project_out(registry_doc, role="admin")


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(ctx: ProjectContext = Depends(require_project)):
    """Return a single project's details."""
    doc = get_meta_db()["PROJECTS"].find_one({"project_id": ctx.project_id}) or {}
    doc = {**doc,
           "project_id": ctx.project_id,
           "name": doc.get("name") or ctx.info.get("project", "")}
    return _to_project_out(doc, role=_role_for(ctx.user))


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(payload: ProjectUpdate,
                   ctx: ProjectContext = Depends(require_project_admin)):
    """Update a project's name/description (admin only)."""
    updates: dict = {}
    if payload.name is not None and payload.name.strip():
        db.update_project_name(payload.name.strip())  # updates project-scoped INFO
        updates["name"] = payload.name.strip()
    if payload.description is not None:
        updates["description"] = payload.description
    if updates:
        get_meta_db()["PROJECTS"].update_one({"project_id": ctx.project_id},
                                             {"$set": updates})

    doc = get_meta_db()["PROJECTS"].find_one({"project_id": ctx.project_id}) or {}
    return _to_project_out({**doc, "project_id": ctx.project_id}, role="admin")


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(ctx: ProjectContext = Depends(require_project_admin)):
    """Terminate a project: drop its database and registry entry (admin only)."""
    get_client().drop_database(project_db_name(ctx.project_id))
    get_meta_db()["PROJECTS"].delete_one({"project_id": ctx.project_id})
    return MessageResponse(message="Project Terminated.")
