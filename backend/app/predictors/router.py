"""API routes for predictor configuration."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.common.errors import raise_not_found
from app.dependencies import require_project_role
from app.predictors.factory import create_predictor
from app.predictors.schemas import (
    CreatePredictorRequest,
    PredictorResponse,
    TestPredictionRequest,
    TestPredictionResponse,
    TokenUsageResponse,
    UpdatePredictorRequest,
)
from app.predictors.service import (
    activate_predictor,
    create_predictor_config,
    delete_predictor_config,
    get_predictor_config,
    list_predictor_configs,
    update_predictor_config,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/predictors", tags=["predictors"])


@router.post("", response_model=PredictorResponse, status_code=status.HTTP_201_CREATED)
async def create_predictor_endpoint(
    project_id: str,
    body: CreatePredictorRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    pc = await create_predictor_config(
        session, project_id, body.name, body.predictor_type, body.config, current_user.id
    )
    return pc


@router.get("", response_model=list[PredictorResponse])
async def list_predictors_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_predictor_configs(session, project_id)


@router.get("/{predictor_id}", response_model=PredictorResponse)
async def get_predictor_endpoint(
    project_id: str,
    predictor_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    pc = await get_predictor_config(session, project_id, predictor_id)
    if not pc:
        raise_not_found("Predictor not found")
    return pc


@router.put("/{predictor_id}", response_model=PredictorResponse)
async def update_predictor_endpoint(
    project_id: str,
    predictor_id: str,
    body: UpdatePredictorRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    pc = await update_predictor_config(
        session, project_id, predictor_id, name=body.name, config=body.config
    )
    if not pc:
        raise_not_found("Predictor not found")
    return pc


@router.delete("/{predictor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_predictor_endpoint(
    project_id: str,
    predictor_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    deleted = await delete_predictor_config(session, project_id, predictor_id)
    if not deleted:
        raise_not_found("Predictor not found")


@router.post("/{predictor_id}/activate", response_model=PredictorResponse)
async def activate_predictor_endpoint(
    project_id: str,
    predictor_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    pc = await activate_predictor(session, project_id, predictor_id)
    if not pc:
        raise_not_found("Predictor not found")
    return pc


@router.post("/{predictor_id}/test", response_model=TestPredictionResponse)
async def test_predictor_endpoint(
    project_id: str,
    predictor_id: str,
    body: TestPredictionRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Run a single test prediction against a configured predictor."""
    pc = await get_predictor_config(session, project_id, predictor_id)
    if not pc:
        raise_not_found("Predictor not found")

    predictor = create_predictor(pc)
    try:
        result = await predictor.predict(body.text)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    token_usage = None
    if result.token_usage:
        token_usage = TokenUsageResponse(
            prompt_tokens=result.token_usage.prompt_tokens,
            completion_tokens=result.token_usage.completion_tokens,
            total_tokens=result.token_usage.total_tokens,
        )

    return TestPredictionResponse(
        score=result.score,
        label=result.label,
        model=result.model,
        reasoning=result.reasoning,
        token_usage=token_usage,
    )
