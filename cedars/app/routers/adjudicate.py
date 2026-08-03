"""Adjudication routes (available to any authenticated project member).

Ports the Flask ``adjudicate_records`` / ``show_annotation`` /
``save_adjudications`` / ``unlock_patient`` workflow. Navigation is backend-driven
and the per-user review state lives in Redis (see :mod:`review_state`).
"""
from fastapi import APIRouter, Depends

from ..dependencies import ProjectContext, require_project
from ..schemas import (AdjudicateAction, AdjudicateResponse, MessageResponse,
                       PatientSearch)
from ..services import adjudication_service

router = APIRouter(prefix="/projects/{project_id}/adjudicate", tags=["adjudicate"])


@router.get("/next", response_model=AdjudicateResponse)
def next_annotation(ctx: ProjectContext = Depends(require_project)):
    """Resume the current patient or load the next one to review."""
    return adjudication_service.get_current_or_next(ctx.user.username, ctx.project_id)


@router.get("/annotation", response_model=AdjudicateResponse)
def current_annotation(ctx: ProjectContext = Depends(require_project)):
    """Return the current annotation for the reviewer's active patient."""
    return adjudication_service.get_current_annotation(ctx.user.username, ctx.project_id)


@router.post("/search", response_model=AdjudicateResponse)
def search(payload: PatientSearch, ctx: ProjectContext = Depends(require_project)):
    """Search for a specific patient by id."""
    return adjudication_service.search_patient(ctx.user.username, ctx.project_id,
                                               payload.patient_id)


@router.post("/save", response_model=AdjudicateResponse)
def save(payload: AdjudicateAction, ctx: ProjectContext = Depends(require_project)):
    """Apply an adjudication action (adjudicate / new_date / del_date / nav / comment)."""
    return adjudication_service.save_action(ctx.user.username, ctx.project_id,
                                            payload.action, payload.comment,
                                            payload.event_date)


@router.post("/unlock", response_model=MessageResponse)
def unlock(ctx: ProjectContext = Depends(require_project)):
    """Release the reviewer's currently locked patient."""
    result = adjudication_service.unlock(ctx.user.username, ctx.project_id)
    return MessageResponse(message=result["message"])
