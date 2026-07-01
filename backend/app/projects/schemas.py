"""Request and response schemas for project endpoints."""

from pydantic import BaseModel, Field


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)
    llm_api_key: str | None = Field(default=None, max_length=500)


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None
    # Send a non-empty string to set/replace the key, or "" to clear it.
    # Omit the field entirely to leave the stored key unchanged.
    llm_api_key: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    settings: dict
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None
    # Never expose the stored key; only whether one is set.
    llm_api_key_set: bool = False
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
