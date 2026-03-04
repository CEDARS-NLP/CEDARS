"""API routes for annotations: bulk prediction runs and review operations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.annotations.schemas import (
    AnnotationResponse,
    AnnotationStatsResponse,
    BulkEstimateResponse,
    BulkRunResponse,
    DeleteEventDateResponse,
    NextPatientResponse,
    PatientAnnotationResponse,
    PatientReviewStats,
    ReviewRequest,
    ReviewResultResponse,
)
from app.annotations.service import (
    delete_event_date,
    estimate_bulk_predictions,
    get_annotation,
    get_annotation_stats,
    get_next_patient_for_review,
    get_next_unreviewed,
    get_note_context,
    get_patient_annotations,
    get_patient_review_stats,
    list_annotations,
    review_annotation,
    run_bulk_predictions,
    skip_annotation,
    unlock_patient,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/annotations", tags=["annotations"])


# ── Token Estimation ──────────────────────────────────────────────


@router.get("/estimate", response_model=BulkEstimateResponse)
async def estimate_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Estimate token usage for bulk predictions on unprocessed target sentences."""
    return await estimate_bulk_predictions(session, project_id)


# ── Bulk Prediction Run ──────────────────────────────────────────


@router.post("/run", response_model=BulkRunResponse)
async def run_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Run the active predictor on all unprocessed target sentences."""
    try:
        result = await run_bulk_predictions(session, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


# ── Annotation CRUD ──────────────────────────────────────────────


@router.get("", response_model=list[AnnotationResponse])
async def list_annotations_endpoint(
    project_id: str,
    review_status: str | None = Query(None, alias="status"),
    patient_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_annotations(
        session, project_id, status=review_status, patient_id=patient_id,
        limit=limit, offset=offset,
    )


@router.get("/stats", response_model=AnnotationStatsResponse)
async def annotation_stats_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await get_annotation_stats(session, project_id)


@router.get("/next", response_model=AnnotationResponse | None)
async def next_unreviewed_endpoint(
    project_id: str,
    patient_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get the next unreviewed annotation for the review queue."""
    return await get_next_unreviewed(session, project_id, patient_id=patient_id)


# ── Patient-first review ─────────────────────────────────────────
# These routes MUST come before /{annotation_id} to avoid path conflicts.


@router.get("/patient/next", response_model=NextPatientResponse)
async def next_patient_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get and lock the next patient with unreviewed annotations."""
    return await get_next_patient_for_review(session, project_id, current_user.id)


@router.get(
    "/patient/{patient_id}/annotations",
    response_model=list[PatientAnnotationResponse],
)
async def patient_annotations_endpoint(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get all annotations for a patient, sorted by note_date and sentence position."""
    return await get_patient_annotations(session, project_id, patient_id)


@router.get("/patient/{patient_id}/stats", response_model=PatientReviewStats)
async def patient_stats_endpoint(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get review stats for a specific patient."""
    return await get_patient_review_stats(session, project_id, patient_id)


@router.post("/patient/{patient_id}/unlock")
async def unlock_patient_endpoint(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Unlock a patient (release review lock)."""
    await unlock_patient(session, project_id, patient_id, current_user.id)
    return {"ok": True}


# ── Annotation by ID ─────────────────────────────────────────────


@router.get("/{annotation_id}", response_model=AnnotationResponse)
async def get_annotation_endpoint(
    project_id: str,
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return annotation


@router.get("/{annotation_id}/context")
async def annotation_context_endpoint(
    project_id: str,
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get the full note context for an annotation (for review UI)."""
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    context = await get_note_context(session, annotation.note_id)
    if not context:
        raise HTTPException(status_code=404, detail="Note not found")

    return context


# ── Review Operations ────────────────────────────────────────────


@router.post(
    "/{annotation_id}/review",
    response_model=ReviewResultResponse,
)
async def review_annotation_endpoint(
    project_id: str,
    annotation_id: str,
    body: ReviewRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Mark an annotation as reviewed, optionally with an event date."""
    result = await review_annotation(
        session, project_id, annotation_id, current_user.id,
        event_date=body.event_date,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return result


@router.post(
    "/{annotation_id}/delete-event-date",
    response_model=DeleteEventDateResponse,
)
async def delete_event_date_endpoint(
    project_id: str,
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Delete an event date and revert skipped annotations."""
    result = await delete_event_date(
        session, project_id, annotation_id, current_user.id,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Annotation not found or no event date set")
    return result


@router.post(
    "/{annotation_id}/skip",
    response_model=AnnotationResponse,
)
async def skip_annotation_endpoint(
    project_id: str,
    annotation_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Mark an annotation as skipped."""
    annotation = await skip_annotation(
        session, project_id, annotation_id, current_user.id,
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return annotation
