"""Unified evaluation session API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.evaluation.schemas import (
    CommitRequest,
    CommitResponse,
    CreateSessionRequest,
    FunnelResponse,
    LlmConfigRequest,
    MetricsResponse,
    PipelineStatsResponse,
    QueryMatchesResponse,
    SessionListResponse,
    SessionResponse,
    SubmitJudgmentRequest,
    SuggestQueriesRequest,
    SuggestQueriesResponse,
    UpdateQueriesRequest,
)
from app.evaluation.service import (
    commit_session,
    compute_metrics,
    create_session,
    discard_session,
    execute_search_queries,
    get_funnel_stats,
    get_query_matches,
    get_session as get_eval_session,
    list_patient_results,
    list_sessions,
    run_llm_on_sample,
    submit_judgment,
    update_llm_config,
    update_queries,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/evaluation",
    tags=["evaluation"],
)


# ── Helpers ──────────────────────────────────────────────────────


async def _get_session_or_404(
    db: AsyncSession, project_id: str, session_id: str
):
    """Fetch an evaluation session, raising 404 if not found or wrong project."""
    eval_session = await get_eval_session(db, session_id)
    if not eval_session or eval_session.project_id != project_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return eval_session


# ── Sessions CRUD ────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session_endpoint(
    project_id: str,
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Create a new evaluation session with patient sampling."""
    try:
        search_queries = [q.model_dump() for q in body.search_queries] if body.search_queries else []
        session = await create_session(
            db,
            project_id,
            user_id=current_user.id,
            search_queries=search_queries,
            cloned_from_id=body.cloned_from_id,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/sessions", response_model=list[SessionListResponse])
async def list_sessions_endpoint(
    project_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """List all sessions for a project."""
    return await list_sessions(db, project_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get a single evaluation session."""
    return await _get_session_or_404(db, project_id, session_id)


@router.delete("/sessions/{session_id}", response_model=SessionResponse)
async def discard_session_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Discard an evaluation session."""
    await _get_session_or_404(db, project_id, session_id)
    try:
        return await discard_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/sessions/{session_id}/clone",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_session_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Clone a new session from a previous one, copying queries and LLM config."""
    await _get_session_or_404(db, project_id, session_id)
    try:
        session = await create_session(
            db,
            project_id,
            user_id=current_user.id,
            cloned_from_id=session_id,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ── Search queries ───────────────────────────────────────────────


@router.put("/sessions/{session_id}/queries", response_model=SessionResponse)
async def update_queries_endpoint(
    project_id: str,
    session_id: str,
    body: UpdateQueriesRequest,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Update search queries on a session."""
    await _get_session_or_404(db, project_id, session_id)
    search_queries = [q.model_dump() for q in body.search_queries]
    return await update_queries(db, session_id, search_queries)


@router.post("/sessions/{session_id}/queries/suggest", response_model=SuggestQueriesResponse)
async def suggest_queries_endpoint(
    project_id: str,
    session_id: str,
    body: SuggestQueriesRequest,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Use LLM to suggest search queries from a natural language description."""
    await _get_session_or_404(db, project_id, session_id)

    from app.evaluation.query_suggest import suggest_queries

    try:
        suggestions = await suggest_queries(
            description=body.description,
            llm_provider=body.llm_provider,
            llm_model=body.llm_model,
            llm_api_base=body.llm_api_base,
        )
        return SuggestQueriesResponse(suggestions=suggestions)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/sessions/{session_id}/queries/execute", response_model=FunnelResponse)
async def execute_queries_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Execute search queries against sample notes."""
    await _get_session_or_404(db, project_id, session_id)
    await execute_search_queries(db, session_id)
    stats = await get_funnel_stats(db, session_id)
    return FunnelResponse(**stats)


@router.get("/sessions/{session_id}/queries/{query_index}/matches", response_model=QueryMatchesResponse)
async def get_query_matches_endpoint(
    project_id: str,
    session_id: str,
    query_index: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get paginated note previews with match highlights for a specific query."""
    eval_session = await _get_session_or_404(db, project_id, session_id)
    data = await get_query_matches(db, session_id, query_index, page=page, page_size=page_size)

    # Get the query definition for the response
    queries = eval_session.search_queries or []
    include_queries = [q for q in queries if q.get("type") == "include"]
    query_def = include_queries[query_index] if query_index < len(include_queries) else {}

    # Build NoteWithMatchesResponse-compatible items from service data
    from app.evaluation.schemas import NoteWithMatchesResponse, SearchMatchResponse

    note_items = []
    for m in data.get("matches", []):
        match_resp = SearchMatchResponse(
            id=m.get("match_id", 0),
            patient_id=m.get("patient_id", ""),
            note_id=m.get("note_id", ""),
            matched_tokens=m.get("matched_tokens", []),
            match_positions=m.get("highlights", []),
            is_negated=m.get("is_negated", False),
        )
        note_items.append(NoteWithMatchesResponse(
            note_id=m.get("note_id", ""),
            patient_id=m.get("patient_id", ""),
            note_text=m.get("note_text", ""),
            note_date=None,
            note_type=None,
            matches=[match_resp],
        ))

    import math
    total = data.get("total", 0)
    total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    # Count distinct patients in this page
    patient_ids = {m.get("patient_id") for m in data.get("matches", [])}

    return QueryMatchesResponse(
        query_index=query_index,
        query=query_def.get("query", ""),
        query_type=query_def.get("type", "include"),
        total_notes=total,
        total_patients=len(patient_ids),
        notes=note_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── LLM configuration & run ─────────────────────────────────────


@router.put("/sessions/{session_id}/llm-config", response_model=SessionResponse)
async def update_llm_config_endpoint(
    project_id: str,
    session_id: str,
    body: LlmConfigRequest,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Update LLM configuration on a session."""
    await _get_session_or_404(db, project_id, session_id)
    return await update_llm_config(
        db,
        session_id,
        event_name=body.event_name,
        event_description=body.event_description,
        include_criteria=body.include_criteria,
        exclude_criteria=body.exclude_criteria,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_api_base=body.llm_api_base,
    )


@router.post("/sessions/{session_id}/run-llm")
async def run_llm_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Run LLM classification on matched patients in the sample."""
    await _get_session_or_404(db, project_id, session_id)
    return await run_llm_on_sample(db, session_id)


# ── Results & review ─────────────────────────────────────────────


@router.get("/sessions/{session_id}/results")
async def list_results_endpoint(
    project_id: str,
    session_id: str,
    label: str | None = Query(default=None),
    reviewed: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """List patient results with optional filtering."""
    await _get_session_or_404(db, project_id, session_id)
    return await list_patient_results(
        db,
        session_id,
        label_filter=label,
        reviewed_filter=reviewed,
        page=page,
        page_size=page_size,
    )


@router.post("/sessions/{session_id}/results/{result_id}/judge")
async def submit_judgment_endpoint(
    project_id: str,
    session_id: str,
    result_id: int,
    body: SubmitJudgmentRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin", "annotator")),
):
    """Submit clinician judgment on a patient result."""
    await _get_session_or_404(db, project_id, session_id)
    if body.judgment not in ("correct", "wrong", "skipped"):
        raise HTTPException(status_code=400, detail="Invalid judgment value")
    try:
        return await submit_judgment(
            db,
            result_id,
            body.judgment,
            current_user.id,
            event_date_override=body.event_date_override,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Result not found")


# ── Metrics & funnel ─────────────────────────────────────────────


@router.get("/sessions/{session_id}/metrics", response_model=MetricsResponse)
async def metrics_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get accuracy metrics for a session."""
    await _get_session_or_404(db, project_id, session_id)
    metrics = await compute_metrics(db, session_id)
    # Ensure total_pending is present for the response schema
    if "total_pending" not in metrics:
        metrics["total_pending"] = 0
    return MetricsResponse(**metrics)


@router.get("/sessions/{session_id}/funnel", response_model=FunnelResponse)
async def funnel_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get funnel statistics for a session."""
    await _get_session_or_404(db, project_id, session_id)
    stats = await get_funnel_stats(db, session_id)
    return FunnelResponse(**stats)


# ── Commit ───────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/commit", response_model=CommitResponse)
async def commit_endpoint(
    project_id: str,
    session_id: str,
    body: CommitRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Commit an evaluation session and dispatch a full pipeline run."""
    await _get_session_or_404(db, project_id, session_id)
    try:
        session = await commit_session(
            db,
            session_id,
            user_id=current_user.id,
            confidence_threshold=body.confidence_threshold,
        )

        from app.evaluation.service import dispatch_full_pipeline_run
        run = await dispatch_full_pipeline_run(db, session)

        return CommitResponse(
            session=SessionResponse.model_validate(session, from_attributes=True),
            pipeline_run_id=run.id,
            total_patients=run.total_patients,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/sessions/{session_id}/pipeline/stats", response_model=PipelineStatsResponse)
async def pipeline_stats_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get full pipeline run progress for a committed session."""
    await _get_session_or_404(db, project_id, session_id)
    from app.evaluation.service import get_pipeline_stats
    try:
        return await get_pipeline_stats(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/pipeline/cancel")
async def cancel_pipeline_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Cancel a running full pipeline."""
    await _get_session_or_404(db, project_id, session_id)
    from app.evaluation.service import cancel_pipeline_run
    try:
        return await cancel_pipeline_run(db, session_id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/pipeline/retry-failed")
async def retry_failed_endpoint(
    project_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Retry failed patients in the full pipeline run."""
    await _get_session_or_404(db, project_id, session_id)
    from app.evaluation.service import retry_failed_pipeline
    try:
        return await retry_failed_pipeline(db, session_id, project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
