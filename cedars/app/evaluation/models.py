"""Pydantic models for LLM prompt evaluation system."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import EventDefinitionModel, LLMConfigModel


class SampleConfig(BaseModel):
    """Configuration for stratified sampling of notes."""

    model_config = ConfigDict(from_attributes=True)

    size: int = Field(default=50, ge=20, le=200)
    keyword_match_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list)


class EvaluationMetrics(BaseModel):
    """Computed metrics from evaluation judgments."""

    model_config = ConfigDict(from_attributes=True)

    reviewed: int = 0
    correct: int = 0
    wrong: int = 0
    skipped: int = 0
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class EvaluationSession(BaseModel):
    """Main evaluation session tracking LLM prompt testing."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    project_id: str
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal[
        "sampling", "running", "reviewing", "completed"
    ] = "sampling"
    sample_config: SampleConfig
    sampled_note_ids: list[str] = Field(default_factory=list)
    llm_config: LLMConfigModel
    event_definition: EventDefinitionModel
    metrics: Optional[EvaluationMetrics] = None


class LLMPrediction(BaseModel):
    """Embedded prediction data from LLM."""

    model_config = ConfigDict(from_attributes=True)

    label: int
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""


class EvaluationJudgment(BaseModel):
    """Individual judgment record for an LLM prediction."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    session_id: str
    note_id: str
    note_text: str
    llm_prediction: LLMPrediction
    judgment: Literal["correct", "wrong", "skipped"] = "skipped"
    judged_by: str
    judged_at: datetime = Field(default_factory=datetime.utcnow)


class ValidatedPrompt(BaseModel):
    """Saved validated prompt configuration with evaluation metrics."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    project_id: str
    version_name: str
    notes: Optional[str] = None
    event_definition: EventDefinitionModel
    llm_config: LLMConfigModel
    evaluation_metrics: EvaluationMetrics
    evaluation_session_id: str
    validated_by: str
    validated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = False
