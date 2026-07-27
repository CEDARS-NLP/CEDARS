"""Workflow API: v1-style query -> NLP -> adjudicate flow (default project workflow)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.workflow import service
from app.workflow.schemas import (
    ActionResponse,
    AnnotationView,
    NextPatientResponse,
    NlpRunResponse,
    ReviewActionRequest,
    SaveQueryRequest,
    SaveQueryResponse,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/workflow", tags=["workflow"])


@router.get("/query")
async def get_query(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Return the project's active search query, or null."""
    from app.workflow import db_ops

    sq = await db_ops.get_active_search_query(session, project_id)
    if sq is None:
        return None
    return {
        "query": sq.query,
        "hide_duplicates": sq.hide_duplicates,
        "skip_after_event": sq.skip_after_event,
        "use_negation": sq.use_negation,
        "nlp_apply": sq.nlp_apply,
    }


@router.put("/query", response_model=SaveQueryResponse)
async def save_query(
    project_id: str,
    body: SaveQueryRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin")),
):
    """Save the search query and (re)dispatch NLP (ops.py ``upload_query``)."""
    changed, dispatched, mode, job_id = await service.save_query_and_dispatch(
        session,
        project_id,
        user.id,
        query=body.query,
        hide_duplicates=body.hide_duplicates,
        skip_after_event=body.skip_after_event,
        use_negation=body.use_negation,
        nlp_apply=body.nlp_apply,
    )
    return SaveQueryResponse(
        changed=changed, dispatched_patients=dispatched, mode=mode, job_id=job_id
    )


@router.post("/nlp/run", response_model=NlpRunResponse)
async def run_nlp(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin")),
):
    """Dispatch NLP processing for all un-reviewed patients (ops.py ``do_nlp_processing``)."""
    dispatched, mode, job_id = await service.dispatch_nlp(session, project_id, user.id)
    return NlpRunResponse(dispatched_patients=dispatched, mode=mode, job_id=job_id)


@router.get("/review/next", response_model=NextPatientResponse)
async def review_next(
    project_id: str,
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get (or resume) the next patient to adjudicate (ops.py ``adjudicate_records``)."""
    patient_id, status, annotation = await service.get_next_patient(
        session, project_id, user.id, user.name, search=search
    )
    if patient_id is None:
        return NextPatientResponse(complete=True)
    return NextPatientResponse(
        complete=False,
        patient_id=patient_id,
        patient_status=status.name if status else None,
        annotation=annotation,
    )


@router.get(
    "/review/patient/{patient_id}/current", response_model=AnnotationView
)
async def review_current(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator")),
):
    """Render the current annotation for a patient (ops.py ``show_annotation``)."""
    annotation = await service.get_current_annotation(session, project_id, patient_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="No active review session for patient")
    return annotation


@router.post(
    "/review/patient/{patient_id}/action", response_model=ActionResponse
)
async def review_action(
    project_id: str,
    patient_id: str,
    body: ReviewActionRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator")),
):
    """Apply one adjudication action (ops.py ``save_adjudications``)."""
    patient_complete, annotation = await service.apply_action(
        session,
        project_id,
        patient_id,
        user.id,
        user.name,
        body.action,
        body.comment,
        body.event_date,
    )
    return ActionResponse(patient_complete=patient_complete, annotation=annotation)


@router.post("/review/patient/{patient_id}/release", status_code=204)
async def review_release(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator")),
):
    """Finalize + unlock a patient without completing review (ops.py POST finalize)."""
    await service.release_patient(session, project_id, patient_id, user.name)


@router.post("/review/patient/{patient_id}/unlock", status_code=204)
async def review_unlock(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin", "annotator")),
):
    """Unlock a patient (ops.py ``unlock_patient``)."""
    await service.unlock_patient(session, project_id, patient_id)
