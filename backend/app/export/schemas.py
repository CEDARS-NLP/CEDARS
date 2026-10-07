"""Export schemas."""

from datetime import datetime

from pydantic import BaseModel


class ExportAnnotationRow(BaseModel):
    annotation_id: str | None = None
    predictor_config_id: str | None = None
    patient_id: str
    note_id: str
    sentence_id: str | None = None
    sentence_text: str
    token: str | None = None
    is_negated: bool = False
    review_excluded: bool = False
    manual_review_override: bool = False
    note_start_index: int | None = None
    note_end_index: int | None = None
    sentence_number: int | None = None
    sentence_start: int | None = None
    sentence_end: int | None = None
    text_date: datetime | None = None
    predicted_label: int | None
    predicted_score: float | None
    predictor_model: str
    reasoning: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    event_date: datetime | None
    patient_review_source: str | None = None
    patient_review_reason: str | None = None
    patient_reviewed_by: str | None = None
    patient_reviewed_at: datetime | None = None


class ExportStatsResponse(BaseModel):
    total: int
    reviewed: int
    events: int
    total_eval_tokens: int = 0


class DatabricksExportRequest(BaseModel):
    data_source_id: str
    target_table: str
    export_type: str  # "annotations", "predictions", or "evaluation"


class DatabricksExportResponse(BaseModel):
    rows_exported: int
    target_table: str
    export_type: str
    status: str
