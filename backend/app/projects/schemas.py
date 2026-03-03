"""Request and response schemas for project endpoints."""

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    settings: dict
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
