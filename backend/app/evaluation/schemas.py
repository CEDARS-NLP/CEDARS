# backend/app/evaluation/schemas.py
"""Request/response schemas for unified evaluation sessions."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Session ---

class SearchQueryItem(BaseModel):
    query: str
    type: str = "include"  # "include" or "exclude"


class CreateSessionRequest(BaseModel):
    search_queries: list[SearchQueryItem] = []
    cloned_from_id: str | None = None


class UpdateQueriesRequest(BaseModel):
    search_queries: list[SearchQueryItem]


class LlmConfigRequest(BaseModel):
    event_name: str = Field(max_length=200)
    event_description: str = Field(max_length=5000)
    include_criteria: str = Field(max_length=2000)
    exclude_criteria: str = Field(default="", max_length=2000)
    llm_provider: str = Field(max_length=50)
    llm_model: str = Field(max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class SessionResponse(BaseModel):
    id: str
    project_id: str
    status: str
    search_queries: list[dict]
    event_name: str | None
    event_description: str | None
    include_criteria: str | None
    exclude_criteria: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_api_base: str | None
    sample_size: int
    metrics: dict | None
    committed_config: dict | None
    committed_at: datetime | None
    cloned_from_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    id: str
    project_id: str
    status: str
    search_queries: list[dict]
    event_name: str | None
    sample_size: int
    metrics: dict | None
    committed_at: datetime | None
    created_at: datetime


# --- Funnel ---

class FunnelResponse(BaseModel):
    sample_patients: int
    sample_notes: int
    matched_patients: int
    matched_notes: int
    filter_percent: float
    llm_positive: int | None = None
    llm_negative: int | None = None
    llm_inconclusive: int | None = None
    estimated_cost: float | None = None


# --- Search Matches ---

class MatchPosition(BaseModel):
    start: int
    end: int
    token: str


class SearchMatchResponse(BaseModel):
    id: int
    patient_id: str
    note_id: str
    matched_tokens: list[str]
    match_positions: list[dict]
    is_negated: bool


class NoteWithMatchesResponse(BaseModel):
    note_id: str
    patient_id: str
    note_text: str
    note_date: str | None
    note_type: str | None
    matches: list[SearchMatchResponse]


class QueryMatchesResponse(BaseModel):
    query_index: int
    query: str
    query_type: str
    total_notes: int
    total_patients: int
    notes: list[NoteWithMatchesResponse]
    page: int
    page_size: int
    total_pages: int


# --- Suggest Queries ---

class SuggestQueriesRequest(BaseModel):
    description: str = Field(max_length=5000)
    llm_provider: str = Field(max_length=50)
    llm_model: str = Field(max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class SuggestedQuery(BaseModel):
    query: str
    type: str  # "include" or "exclude"


class SuggestQueriesResponse(BaseModel):
    suggestions: list[SuggestedQuery]


# --- Patient Results ---

class PatientResultResponse(BaseModel):
    id: int
    patient_id: str
    status: str
    finding_label: str | None
    finding_reasoning: str | None
    finding_evidence: list[dict] | None
    event_date: str | None
    predicted_score: float | None
    review_judgment: str | None
    reviewer_date_override: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    notes_searched: int
    notes_matched: int


class SubmitJudgmentRequest(BaseModel):
    judgment: str  # "correct", "wrong", "skipped"
    event_date_override: str | None = None  # ISO date


# --- Metrics ---

class MetricsResponse(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    tn: int
    fn: int
    total_reviewed: int
    total_pending: int


# --- Commit ---

class CommitRequest(BaseModel):
    confidence_threshold: float | None = None


class CommitResponse(BaseModel):
    session: SessionResponse
    pipeline_run_id: str
    total_patients: int
    estimated_cost: float | None = None


# --- Pipeline ---

class PipelineStatsResponse(BaseModel):
    total: int
    queued: int
    processing: int
    completed: int
    failed: int
    no_match: int
    is_cancelled: bool
