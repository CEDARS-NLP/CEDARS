"""API routes for annotations: bulk prediction runs and review operations."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.evaluation.models import EvaluationSession, PatientResult
from app.annotations.schemas import (
    AnnotationResponse,
    AnnotationStatsResponse,
    BulkEstimateResponse,
    BulkRunResponse,
    DeleteEventDateResponse,
    NextPatientResponse,
    PatientAnnotationResponse,
    PatientReviewStats,
    PredictionJobResponse,
    ReviewRequest,
    ReviewResultResponse,
)
from app.annotations.query_service import get_patient_matched_notes
from app.annotations.service import (
    cancel_prediction_job,
    delete_event_date,
    dispatch_prediction_job,
    estimate_bulk_predictions,
    get_annotation,
    get_annotation_stats,
    get_next_patient_for_review,
    get_next_unreviewed,
    get_note_context,
    get_patient_annotations,
    get_patient_review_stats,
    get_prediction_job_status,
    list_annotations,
    reopen_patient,
    review_annotation,
    run_bulk_predictions,
    skip_annotation,
    unlock_patient,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/annotations", tags=["annotations"])


def _extract_keywords_from_queries(search_queries: list[dict]) -> list[str]:
    """Extract plain keyword tokens from evaluation session search queries."""
    keywords: set[str] = set()
    for sq in search_queries:
        query = sq.get("query", "")
        # Strip boolean operators and parens, split into tokens
        cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", query, flags=re.IGNORECASE)
        cleaned = re.sub(r"[()\"']", " ", cleaned)
        for token in cleaned.split():
            token = token.strip().rstrip("*")
            if len(token) >= 2:
                keywords.add(token.lower())
    return sorted(keywords)


async def _get_search_keywords(
    db: AsyncSession,
    project_id: str,
    pipeline_run_id: str | None,
) -> list[str]:
    """Get search keywords for an annotation from its evaluation session."""
    if not pipeline_run_id:
        return []

    # Find evaluation session via PatientResult → session
    stmt = (
        select(PatientResult.session_id)
        .where(PatientResult.pipeline_run_id == pipeline_run_id)
        .distinct()
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row or not row[0]:
        return []

    eval_session = await db.get(EvaluationSession, row[0])
    if not eval_session or not eval_session.search_queries:
        return []

    return _extract_keywords_from_queries(eval_session.search_queries)


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


# ── Prediction Job Dispatch ─────────────────────────────────────


@router.post("/predictions/run", response_model=PredictionJobResponse)
async def dispatch_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Dispatch a background prediction job for all unprocessed target sentences."""
    try:
        result = await dispatch_prediction_job(session, project_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/predictions/status", response_model=PredictionJobResponse | None)
async def prediction_status_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get the latest prediction job status for this project."""
    return await get_prediction_job_status(session, project_id)


@router.post("/predictions/cancel")
async def cancel_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Cancel the running prediction job."""
    result = await cancel_prediction_job(session, project_id)
    if not result:
        raise HTTPException(status_code=404, detail="No running prediction job found")
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


@router.post("/patient/{patient_id}/reopen")
async def reopen_patient_endpoint(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Re-queue a reviewed patient. Admin only. Preserves annotation decisions."""
    success = await reopen_patient(session, project_id, patient_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Patient not found or not in reviewed state")
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

    # Attach search keywords from the evaluation session linked via pipeline_run
    context["search_keywords"] = await _get_search_keywords(
        session, project_id, annotation.pipeline_run_id
    )

    return context


@router.get("/patient/{patient_id}/matched-notes")
async def patient_matched_notes_endpoint(
    project_id: str,
    patient_id: str,
    annotation_id: str = Query(..., description="Annotation ID to trace pipeline run"),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get all notes with keyword matches for a patient (for pipeline annotations)."""
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    notes = await get_patient_matched_notes(
        session, project_id, patient_id, annotation.pipeline_run_id
    )
    return notes


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
