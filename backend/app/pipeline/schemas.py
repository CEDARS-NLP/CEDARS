"""Request/response schemas for the pipeline API."""

from datetime import datetime

from pydantic import BaseModel, Field


class CreateEventConfigRequest(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(max_length=5000)
    include_criteria: str = Field(max_length=2000)
    exclude_criteria: str = Field(default="", max_length=2000)
    search_patterns: dict = Field(default_factory=dict)
    llm_provider: str = Field(max_length=50)
    llm_model: str = Field(max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class UpdateEventConfigRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    include_criteria: str | None = Field(default=None, max_length=2000)
    exclude_criteria: str | None = Field(default=None, max_length=2000)
    search_patterns: dict | None = None
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class CommitEventConfigRequest(BaseModel):
    confidence_threshold: float | None = None


class EventConfigResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    include_criteria: str
    exclude_criteria: str
    search_patterns: dict
    llm_provider: str
    llm_model: str
    llm_api_base: str | None
    confidence_threshold: float | None
    is_committed: bool
    created_at: datetime
    updated_at: datetime


class RunSampleRequest(BaseModel):
    sample_size: int = Field(default=10, ge=1, le=1000)


class PipelineRunResponse(BaseModel):
    id: str
    project_id: str
    event_config_id: str
    run_type: str
    status: str
    config_snapshot: dict
    sample_size: int | None
    total_patients: int
    processed_patients: int
    failed_patients: int
    is_cancelled: bool
    result_summary: dict | None
    created_by: str
    snapshot_version: int
    created_at: datetime
    updated_at: datetime


class PatientTaskResponse(BaseModel):
    id: int
    pipeline_run_id: str
    patient_id: str
    status: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class RunStatsResponse(BaseModel):
    total: int
    queued: int
    processing: int
    completed: int
    failed: int
    no_match: int


class RunMetricsResponse(BaseModel):
    total_reviewed: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float | None
    recall: float | None
    f1_score: float | None
    suggested_threshold: float | None
