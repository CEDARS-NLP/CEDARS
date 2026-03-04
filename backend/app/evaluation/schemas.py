"""Request/response schemas for evaluation."""

from datetime import datetime

from pydantic import BaseModel


class SampleConfig(BaseModel):
    size: int = 50
    keyword_match_ratio: float = 0.6
    keywords: list[str] = []


class CreateSessionRequest(BaseModel):
    name: str = ""
    predictor_config_id: str
    sample_config: SampleConfig = SampleConfig()


class SessionResponse(BaseModel):
    id: str
    project_id: str
    predictor_config_id: str
    name: str
    status: str
    sample_config: dict
    metrics: dict
    total_notes: int
    judged_notes: int
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class JudgmentResponse(BaseModel):
    id: str
    session_id: str
    note_id: str
    predicted_label: int | None
    predicted_score: float | None
    reasoning: str
    judgment: str
    judged_by: str | None
    judged_at: datetime | None


class JudgmentWithNoteResponse(BaseModel):
    """Judgment with note text for the review UI."""

    id: str
    session_id: str
    note_id: str
    predicted_label: int | None
    predicted_score: float | None
    reasoning: str
    judgment: str
    judged_by: str | None
    judged_at: datetime | None
    # Note context
    note_text: str
    note_text_id: str
    patient_id: str


class SubmitJudgmentRequest(BaseModel):
    judgment: str  # "correct", "wrong", "skipped"


class MetricsResponse(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    tn: int
    fn: int
    total_judged: int
    total_pending: int


class ValidateRequest(BaseModel):
    name: str
    notes: str = ""
    threshold: float = 0.5


class ValidatedPredictorResponse(BaseModel):
    id: str
    project_id: str
    predictor_config_id: str
    session_id: str
    name: str
    notes: str
    config_snapshot: dict
    metrics_snapshot: dict
    threshold: float
    is_active: bool
    validated_by: str
    created_at: datetime


class BulkRunStats(BaseModel):
    total_sentences: int = 0
    predictions_made: int = 0
    annotations_created: int = 0
    errors: int = 0
    token_usage: dict | None = None


class ActivateResponse(BaseModel):
    validated: ValidatedPredictorResponse
    bulk_run: BulkRunStats | None = None
