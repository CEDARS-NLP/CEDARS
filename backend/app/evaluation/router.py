"""API routes for the evaluation framework."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.evaluation.schemas import (
    ActivateResponse,
    BulkRunStats,
    CreateSessionRequest,
    JudgmentResponse,
    JudgmentWithNoteResponse,
    MetricsResponse,
    SessionResponse,
    SubmitJudgmentRequest,
    ValidateRequest,
    ValidatedPredictorResponse,
)
from app.evaluation.service import (
    activate_validated_predictor,
    compute_metrics,
    create_session,
    get_next_pending_with_note,
    get_session as get_eval_session,
    list_judgments,
    list_sessions,
    list_validated_predictors,
    run_predictions,
    submit_judgment,
    validate_predictor,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/evaluation",
    tags=["evaluation"],
)


# ── Sessions ─────────────────────────────────────────────────────


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_sessions(session, project_id)


@router.post("/sessions", response_model=SessionResponse)
async def create_session_endpoint(
    project_id: str,
    body: CreateSessionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Create a new evaluation session with sampled notes."""
    return await create_session(
        session,
        project_id,
        predictor_config_id=body.predictor_config_id,
        user_id=current_user.id,
        name=body.name,
        sample_config=body.sample_config.model_dump(),
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    eval_session = await get_eval_session(session, session_id)
    if not eval_session or eval_session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return eval_session


# ── Predictions ──────────────────────────────────────────────────


@router.post("/sessions/{session_id}/run", response_model=SessionResponse)
async def run_predictions_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Run predictions on all sampled notes in the session."""
    eval_session = await get_eval_session(session, session_id)
    if not eval_session or eval_session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return await run_predictions(session, session_id)


# ── Judgments ────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/judgments", response_model=list[JudgmentResponse])
async def list_judgments_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_judgments(session, session_id)


@router.get("/sessions/{session_id}/next", response_model=JudgmentWithNoteResponse | None)
async def next_judgment_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get the next pending judgment with its note text for review."""
    return await get_next_pending_with_note(session, session_id)


@router.post(
    "/sessions/{session_id}/judgments/{judgment_id}",
    response_model=JudgmentResponse,
)
async def submit_judgment_endpoint(
    project_id: str,
    session_id: str,
    judgment_id: str,
    body: SubmitJudgmentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Submit a clinician judgment (correct/wrong/skipped)."""
    if body.judgment not in ("correct", "wrong", "skipped"):
        raise HTTPException(status_code=400, detail="Invalid judgment value")
    judgment = await submit_judgment(session, judgment_id, body.judgment, current_user.id)
    if not judgment:
        raise HTTPException(status_code=404, detail="Judgment not found")
    return judgment


# ── Metrics ──────────────────────────────────────────────────────


@router.get("/sessions/{session_id}/metrics", response_model=MetricsResponse)
async def metrics_endpoint(
    project_id: str,
    session_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await compute_metrics(session, session_id)


# ── Validation ───────────────────────────────────────────────────


@router.post("/sessions/{session_id}/validate", response_model=ValidatedPredictorResponse)
async def validate_endpoint(
    project_id: str,
    session_id: str,
    body: ValidateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Validate the predictor configuration from this evaluation session."""
    return await validate_predictor(
        session,
        project_id,
        session_id,
        current_user.id,
        name=body.name,
        notes=body.notes,
        threshold=body.threshold,
    )


@router.get("/validated", response_model=list[ValidatedPredictorResponse])
async def list_validated_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_validated_predictors(session, project_id)


@router.post("/validated/{validated_id}/activate", response_model=ActivateResponse)
async def activate_validated_endpoint(
    project_id: str,
    validated_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Activate a validated predictor, its config, and trigger bulk predictions."""
    import logging

    from app.annotations.prediction_service import run_bulk_predictions

    validated = await activate_validated_predictor(session, project_id, validated_id)
    if not validated:
        raise HTTPException(status_code=404, detail="Validated predictor not found")

    # Orchestrate: trigger bulk predictions at the integration boundary
    bulk_stats = None
    try:
        bulk_stats = await run_bulk_predictions(session, project_id)
    except (ValueError, Exception) as e:
        logging.getLogger(__name__).warning(
            "Bulk prediction run after activation failed: %s", e
        )

    return ActivateResponse(
        validated=ValidatedPredictorResponse.model_validate(validated, from_attributes=True),
        bulk_run=BulkRunStats(**bulk_stats) if bulk_stats else None,
    )
