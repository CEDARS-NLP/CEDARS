"""API routes for NLP pipeline: search queries, processing, sentences."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.nlp.schemas import (
    CreateSearchQueryRequest,
    NlpJobResponse,
    NlpStatsResponse,
    SearchQueryResponse,
    SentenceResponse,
    UpdateSearchQueryRequest,
)
from app.nlp.engine import get_pipeline_info
from app.jobs.schemas import BackgroundJobResponse
from app.nlp.service import (
    cancel_nlp_job,
    clear_sentences,
    create_search_query,
    delete_search_query,
    dispatch_nlp_job,
    get_latest_job,
    get_nlp_job_status,
    get_nlp_stats,
    get_search_query,
    list_search_queries,
    list_target_sentences,
    run_nlp_pipeline,
    update_search_query,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/nlp", tags=["nlp"])


# ── Search Queries ───────────────────────────────────────────────


@router.post(
    "/queries",
    response_model=SearchQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_query_endpoint(
    project_id: str,
    body: CreateSearchQueryRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    sq = await create_search_query(
        session,
        project_id,
        body.query,
        name=body.name,
        created_by=current_user.id,
        nlp_apply=body.nlp_apply,
        hide_duplicates=body.hide_duplicates,
        skip_after_event=body.skip_after_event,
    )
    return sq


@router.get("/queries", response_model=list[SearchQueryResponse])
async def list_queries_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_search_queries(session, project_id)


@router.get("/queries/{query_id}", response_model=SearchQueryResponse)
async def get_query_endpoint(
    project_id: str,
    query_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    sq = await get_search_query(session, project_id, query_id)
    if not sq:
        raise HTTPException(status_code=404, detail="Search query not found")
    return sq


@router.put("/queries/{query_id}", response_model=SearchQueryResponse)
async def update_query_endpoint(
    project_id: str,
    query_id: str,
    body: UpdateSearchQueryRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    updates = body.model_dump(exclude_none=True)
    sq = await update_search_query(session, project_id, query_id, updates)
    if not sq:
        raise HTTPException(status_code=404, detail="Search query not found")
    return sq


@router.delete("/queries/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_query_endpoint(
    project_id: str,
    query_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    deleted = await delete_search_query(session, project_id, query_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Search query not found")


# ── NLP Processing ───────────────────────────────────────────────


@router.post("/run")
async def run_nlp_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Trigger NLP processing for all unprocessed notes in the project."""
    return await dispatch_nlp_job(session, project_id, current_user.id)


@router.get("/job/status", response_model=BackgroundJobResponse | None)
async def nlp_job_status_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get the latest NLP background job status."""
    return await get_nlp_job_status(session, project_id)


@router.post("/cancel")
async def cancel_nlp_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Cancel a running NLP job."""
    result = await cancel_nlp_job(session, project_id)
    if not result:
        raise HTTPException(status_code=404, detail="No active NLP job found")
    return result


@router.post("/reprocess", response_model=NlpJobResponse)
async def reprocess_nlp_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Clear all sentences and re-run the NLP pipeline from scratch."""
    await clear_sentences(session, project_id)
    job = await run_nlp_pipeline(session, project_id)
    return job


@router.get("/stats", response_model=NlpStatsResponse)
async def nlp_stats_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await get_nlp_stats(session, project_id)


@router.get("/job", response_model=NlpJobResponse | None)
async def latest_job_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await get_latest_job(session, project_id)


# ── Sentences ────────────────────────────────────────────────────


@router.get("/sentences", response_model=list[SentenceResponse])
async def list_sentences_endpoint(
    project_id: str,
    include_negated: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """List target sentences (matched by search queries)."""
    return await list_target_sentences(
        session, project_id, include_negated=include_negated, limit=limit, offset=offset
    )


# ── Pipeline info ────────────────────────────────────────────────


@router.get("/pipeline-info")
async def pipeline_info_endpoint(
    project_id: str,
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Return info about the NLP pipeline configuration."""
    return get_pipeline_info()
