# backend/app/evaluation/schemas.py
"""Request/response schemas for unified evaluation sessions."""

from datetime import datetime

from pydantic import BaseModel, Field

# --- Session ---

class SearchQueryItem(BaseModel):
    query: str
    type: str = "include"  # "include" or "exclude"


# A session runs every query against every note of every sampled patient, so an
# unbounded list is both a memory risk and a fan-out multiplier in the worker
# loop. 50 is far above any real event definition.
_MAX_SEARCH_QUERIES = 50


class CreateSessionRequest(BaseModel):
    search_queries: list[SearchQueryItem] = Field(default=[], max_length=_MAX_SEARCH_QUERIES)
    cloned_from_id: str | None = None


class UpdateQueriesRequest(BaseModel):
    search_queries: list[SearchQueryItem] = Field(max_length=_MAX_SEARCH_QUERIES)


class EventConfigRequest(BaseModel):
    event_name: str = Field(max_length=200)
    event_description: str = Field(max_length=5000)
    include_criteria: str = Field(max_length=2000)
    exclude_criteria: str = Field(default="", max_length=2000)


class SessionResponse(BaseModel):
    id: str
    project_id: str
    status: str
    search_queries: list[dict]
    event_name: str | None
    event_description: str | None
    include_criteria: str | None
    exclude_criteria: str | None
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


class NextResultResponse(BaseModel):
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
    notes_searched: int
    notes_matched: int
    position: int
    total_unreviewed: int
    total_results: int


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


class ResultNoteContext(BaseModel):
    note_id: str
    text_id: str
    text: str
    note_date: str | None
    note_tags: dict
    matched_tokens: list[str]
    match_positions: list[dict]
    is_evidence: bool


class ResultNotesResponse(BaseModel):
    patient_id: str
    patient_id_ext: str | None
    notes: list[ResultNoteContext]
    search_keywords: list[str]
