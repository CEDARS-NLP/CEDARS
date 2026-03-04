"""Export schemas."""

from datetime import datetime

from pydantic import BaseModel


class ExportAnnotationRow(BaseModel):
    patient_id: str
    note_id: str
    sentence_id: str
    sentence_text: str
    predicted_label: int | None
    predicted_score: float | None
    predictor_model: str
    reasoning: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    event_date: datetime | None


class ExportStatsResponse(BaseModel):
    total: int
    reviewed: int
    events: int
    total_eval_tokens: int = 0
