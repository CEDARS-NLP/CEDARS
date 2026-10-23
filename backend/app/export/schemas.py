"""Export schemas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class ExportAnnotationRow(BaseModel):
    annotation_id: int | None = None
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
    text_date: date | datetime | None = None
    predicted_label: int | None
    predicted_score: float | None
    predictor_model: str
    reasoning: str
    review_status: str
    review_type: str | None = None
    reviewed_by: str | None
    reviewed_at: datetime | None
    event_date: date | datetime | None
    patient_review_source: str | None = None
    patient_review_reason: str | None = None
    patient_reviewed_by: str | None = None
    patient_reviewed_at: datetime | None = None


class ExportResultRow(BaseModel):
    project_id: str
    patient_uuid: str
    patient_id: str
    index_no: int | None = None
    processing_status: str
    review_status: str
    review_type: str | None = None
    comments: str | None = None
    event_information: dict | None = None
    event_date: date | None = None
    event_annotation_id: int | None = None
    first_note_date: datetime | None = None
    last_note_date: datetime | None = None
    max_score: float | None = None
    max_score_note_date: datetime | None = None
    max_score_note_id: str | None = None
    reviewer: str | None = None
    reviewed_notes: int = 0
    reviewed_sentences: int = 0
    total_notes: int = 0
    total_sentences: int = 0
    notes_total: int = 0
    notes_processed: int = 0
    notes_failed: int = 0
    annotations_total: int = 0
    annotations_pending: int = 0
    annotations_reviewed: int = 0
    annotations_skipped: int = 0
    reason_counts: dict = Field(default_factory=dict)
    failure_count: int = 0
    last_error: str | None = None
    last_updated_at: datetime | None = None
    updated_at: datetime | None = None


class ExportStatsResponse(BaseModel):
    total: int
    reviewed: int
    events: int
    total_eval_tokens: int = 0


class DatabricksExportRequest(BaseModel):
    data_source_id: str
    target_table: str
    export_type: str  # "annotations", "predictions", "results", or "evaluation"


class DatabricksExportResponse(BaseModel):
    rows_exported: int
    target_table: str
    export_type: str
    status: str
