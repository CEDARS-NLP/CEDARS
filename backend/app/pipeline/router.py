"""API routes for the agentic pipeline."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import get_current_user, require_project_role
from app.pipeline.schemas import (
    CommitEventConfigRequest,
    CreateEventConfigRequest,
    EventConfigResponse,
    PatientTaskResponse,
    PipelineRunResponse,
    RunSampleRequest,
    RunMetricsResponse,
    RunStatsResponse,
    UpdateEventConfigRequest,
)
from app.pipeline.service import (
    commit_event_config,
    create_event_config,
    delete_event_config,
    get_event_config,
    list_event_configs,
    update_event_config,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/pipeline",
    tags=["pipeline"],
)


# ── EventConfig CRUD ──────────────────────────────────────────────────


@router.post("/events", response_model=EventConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_event_config_endpoint(
    project_id: str,
    body: CreateEventConfigRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    ec = await create_event_config(
        session,
        project_id=project_id,
        name=body.name,
        description=body.description,
        include_criteria=body.include_criteria,
        exclude_criteria=body.exclude_criteria,
        search_patterns=body.search_patterns,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_api_base=body.llm_api_base,
    )
    return ec


@router.get("/events", response_model=list[EventConfigResponse])
async def list_event_configs_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_event_configs(session, project_id)


@router.get("/events/{event_config_id}", response_model=EventConfigResponse)
async def get_event_config_endpoint(
    project_id: str,
    event_config_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    ec = await get_event_config(session, project_id, event_config_id)
    if not ec:
        raise HTTPException(status_code=404, detail="EventConfig not found")
    return ec


@router.put("/events/{event_config_id}", response_model=EventConfigResponse)
async def update_event_config_endpoint(
    project_id: str,
    event_config_id: str,
    body: UpdateEventConfigRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    try:
        ec = await update_event_config(
            session, project_id, event_config_id,
            **body.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ec:
        raise HTTPException(status_code=404, detail="EventConfig not found")
    return ec


@router.delete("/events/{event_config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_config_endpoint(
    project_id: str,
    event_config_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    try:
        deleted = await delete_event_config(session, project_id, event_config_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="EventConfig not found")


@router.post("/events/{event_config_id}/commit", response_model=EventConfigResponse)
async def commit_event_config_endpoint(
    project_id: str,
    event_config_id: str,
    body: CommitEventConfigRequest = CommitEventConfigRequest(),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    try:
        ec = await commit_event_config(
            session, project_id, event_config_id,
            confidence_threshold=body.confidence_threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ec:
        raise HTTPException(status_code=404, detail="EventConfig not found")
    return ec


@router.post("/events/{event_config_id}/generate-patterns", response_model=EventConfigResponse)
async def generate_patterns_endpoint(
    project_id: str,
    event_config_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    ec = await get_event_config(session, project_id, event_config_id)
    if not ec:
        raise HTTPException(status_code=404, detail="EventConfig not found")
    if ec.is_committed:
        raise HTTPException(status_code=400, detail="Cannot modify a committed EventConfig")

    from app.pipeline.pattern_generator import generate_search_patterns

    try:
        patterns = await generate_search_patterns(
            event_name=ec.name,
            description=ec.description,
            include_criteria=ec.include_criteria,
            exclude_criteria=ec.exclude_criteria,
            llm_provider=ec.llm_provider,
            llm_model=ec.llm_model,
            llm_api_base=ec.llm_api_base,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))

    ec = await update_event_config(
        session, project_id, event_config_id,
        search_patterns=patterns,
    )
    return ec


# ── Pipeline Run Endpoints ────────────────────────────────────────────


@router.post("/events/{event_config_id}/run-sample", response_model=PipelineRunResponse)
async def run_sample_endpoint(
    project_id: str,
    event_config_id: str,
    body: RunSampleRequest = RunSampleRequest(),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    from app.pipeline.orchestrator import dispatch_sample_run

    try:
        run = await dispatch_sample_run(
            session, project_id, event_config_id,
            user_id=current_user.id,
            sample_size=body.sample_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return run


@router.post("/events/{event_config_id}/run-full", response_model=PipelineRunResponse)
async def run_full_endpoint(
    project_id: str,
    event_config_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    from app.pipeline.orchestrator import dispatch_full_run

    try:
        run = await dispatch_full_run(
            session, project_id, event_config_id,
            user_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return run


@router.get("/runs", response_model=list[PipelineRunResponse])
async def list_runs_endpoint(
    project_id: str,
    event_config_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    from app.pipeline.orchestrator import list_runs

    return await list_runs(session, project_id, event_config_id)


@router.get("/runs/{run_id}", response_model=PipelineRunResponse)
async def get_run_endpoint(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    from app.pipeline.orchestrator import get_run

    run = await get_run(session, project_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run


@router.get("/runs/{run_id}/stats", response_model=RunStatsResponse)
async def get_run_stats_endpoint(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    from app.pipeline.orchestrator import get_run, get_run_stats

    run = await get_run(session, project_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return await get_run_stats(session, run_id)


@router.get("/runs/{run_id}/metrics", response_model=RunMetricsResponse)
async def get_run_metrics_endpoint(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    from app.pipeline.orchestrator import get_run
    from app.pipeline.service import compute_run_metrics

    run = await get_run(session, project_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return await compute_run_metrics(session, run_id)


@router.get("/runs/{run_id}/tasks", response_model=list[PatientTaskResponse])
async def list_tasks_endpoint(
    project_id: str,
    run_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    from app.pipeline.orchestrator import get_run, list_tasks

    run = await get_run(session, project_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return await list_tasks(session, run_id, status_filter, limit, offset)


@router.post("/runs/{run_id}/cancel", response_model=PipelineRunResponse)
async def cancel_run_endpoint(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    from app.pipeline.orchestrator import cancel_run

    try:
        run = await cancel_run(session, project_id, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run


@router.post("/runs/{run_id}/retry-failed", response_model=PipelineRunResponse)
async def retry_failed_endpoint(
    project_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    from app.pipeline.orchestrator import retry_failed

    try:
        run = await retry_failed(session, project_id, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run
