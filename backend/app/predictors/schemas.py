"""Pydantic schemas for predictor API."""

from datetime import datetime

from pydantic import BaseModel

from app.predictors.models import PredictorType


class CreatePredictorRequest(BaseModel):
    name: str
    predictor_type: PredictorType
    config: dict = {}


class UpdatePredictorRequest(BaseModel):
    name: str | None = None
    config: dict | None = None


class PredictorResponse(BaseModel):
    id: str
    project_id: str
    predictor_type: PredictorType
    name: str
    config: dict
    is_active: bool
    created_by: str
    created_at: datetime


class TestPredictionRequest(BaseModel):
    text: str


class TokenUsageResponse(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class TestPredictionResponse(BaseModel):
    score: float
    label: int
    model: str
    reasoning: str
    token_usage: TokenUsageResponse | None = None
