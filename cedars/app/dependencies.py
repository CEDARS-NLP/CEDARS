"""Shared FastAPI dependencies — chiefly binding the per-request project context.

Why ``bind_project`` is async: FastAPI dispatches *sync* path operations and
sync dependencies to a threadpool, copying the calling task's ``contextvars``
at dispatch time. A contextvar set inside a *sync* dependency therefore would
NOT be visible to the endpoint. Setting it inside an *async* dependency (which
runs in the event-loop task) makes it part of the context that the endpoint's
threadpool dispatch copies — so ``get_current_project_engine()`` resolves to
the right project's database.
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Path, status

from .database import (get_current_project_engine, get_current_project_id,
                       get_global_engine, reset_current_project_db,
                       set_current_project_db)
from .database.db_auth import get_project_membership
from .database.db_projects import get_info
from .security import CurrentUser, get_current_user


@dataclass
class ProjectContext:
    """Resolved, access-checked project context for a request."""

    project_id: str
    user: CurrentUser
    info: dict


async def bind_project(project_id: str = Path(...)):
    """Bind the request context to ``project_id``'s database for its duration.

    Yields the raw ``project_id``; the context is reset once the response is
    produced. Runs in the event-loop task so the binding propagates to the
    (threadpool-dispatched) sync endpoint.
    """
    token = set_current_project_db(project_id)
    try:
        yield project_id
    finally:
        reset_current_project_db(token)


def require_project(project_id: str = Depends(bind_project),
                    user: CurrentUser = Depends(get_current_user)) -> ProjectContext:
    """Require an authenticated user and an existing, initialized project.

    ``bind_project`` has already bound the project engine, so ``get_info``
    resolves to this project's metadata and doubles as an existence check.
    """
    info = get_info(get_global_engine(), get_current_project_engine(),
                    get_current_project_id())
    if not info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Project not found")
    if get_project_membership(get_global_engine(), project_id, user.username) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have access to this project.")
    return ProjectContext(project_id=project_id, user=user, info=info)


def require_project_admin(ctx: ProjectContext = Depends(require_project)) -> ProjectContext:
    """Require the authenticated user to be an admin for this project."""
    membership = get_project_membership(get_global_engine(), ctx.project_id,
                                        ctx.user.username)
    if membership is None or not membership.has_admin_privileges:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have admin access.")
    return ctx
