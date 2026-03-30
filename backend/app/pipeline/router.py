"""API routes for the agentic pipeline."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import get_current_user, require_project_role
from app.pipeline.schemas import (
    CommitEventConfigRequest,
    CreateEventConfigRequest,
    EventConfigResponse,
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
