"""Pydantic schemas for NLP API requests and responses."""

from datetime import datetime

from pydantic import BaseModel

from app.nlp.models import NlpJobStatus


class CreateSearchQueryRequest(BaseModel):
    name: str = ""
    query: str
    nlp_apply: bool = True
    hide_duplicates: bool = True
    skip_after_event: bool = True


class UpdateSearchQueryRequest(BaseModel):
    name: str | None = None
    query: str | None = None
    is_active: bool | None = None
    nlp_apply: bool | None = None
    hide_duplicates: bool | None = None
    skip_after_event: bool | None = None


class SearchQueryResponse(BaseModel):
    id: str
    project_id: str
    name: str
    query: str
    is_active: bool
    nlp_apply: bool
    hide_duplicates: bool
    skip_after_event: bool
    created_at: datetime


class NlpJobResponse(BaseModel):
    id: str
    project_id: str
    status: NlpJobStatus
    total_notes: int
    processed_notes: int
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class SentenceResponse(BaseModel):
    id: str
    note_id: str
    sentence_number: int
    text: str
    start_pos: int
    end_pos: int
    is_negated: bool
    is_target: bool
    matched_tokens: list
    created_at: datetime


class NlpStatsResponse(BaseModel):
    total_notes: int
    processed_notes: int
    total_sentences: int
    target_sentences: int
    negated_sentences: int
