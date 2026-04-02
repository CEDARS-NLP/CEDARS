"""Request and response schemas for project endpoints."""

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    settings: dict
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None
    created_at: str
    role: str | None = None  # User's role in this project


class ProjectMemberResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role: str


class AddMemberRequest(BaseModel):
    email: str
    role: str = "annotator"
