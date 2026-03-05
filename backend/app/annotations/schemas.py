"""Request/response schemas for annotations."""

from datetime import datetime

from pydantic import BaseModel


class AnnotationResponse(BaseModel):
    id: str
    project_id: str
    patient_id: str
    note_id: str
    sentence_id: str
    sentence_text: str
    matched_tokens: str
    is_negated: bool
    predicted_score: float | None
    predicted_label: int | None
    predictor_model: str
    reasoning: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    event_date: datetime | None
    created_at: datetime


class ReviewRequest(BaseModel):
    """Mark an annotation as reviewed, optionally with an event date."""

    event_date: datetime | None = None


class BulkRunResponse(BaseModel):
    """Response for bulk prediction run."""

    total_sentences: int
    predictions_made: int
    annotations_created: int
    errors: int
    token_usage: dict | None = None


class BulkEstimateResponse(BaseModel):
    """Estimated token usage for bulk predictions."""

    sentence_count: int
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    estimated_total_tokens: int


class PredictionJobResponse(BaseModel):
    """Response when dispatching or querying a prediction job."""

    job_id: str
    status: str
    progress: int = 0
    result_summary: dict | None = None


class PatientAnnotationResponse(AnnotationResponse):
    """Annotation with note context for patient review."""

    note_date: datetime | None = None
    note_text_id: str = ""
    sentence_number: int = 0


class NextPatientResponse(BaseModel):
    patient_id: str | None = None
    patient_id_ext: str | None = None
    total_annotations: int = 0
    unreviewed_annotations: int = 0
    all_complete: bool = False


class ReviewResultResponse(BaseModel):
    annotation: AnnotationResponse
    skipped_count: int = 0


class DeleteEventDateResponse(BaseModel):
    annotation: AnnotationResponse
    reverted_count: int = 0


class PatientReviewStats(BaseModel):
    total: int
    unreviewed: int
    reviewed: int
    skipped: int
    current_event_date: datetime | None = None
    event_annotation_id: str | None = None


class AnnotationStatsResponse(BaseModel):
    total: int
    unreviewed: int
    reviewed: int
    skipped: int
    events_found: int
    is_complete: bool = False
