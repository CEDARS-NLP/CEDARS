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
