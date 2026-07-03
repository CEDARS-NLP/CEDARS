"""Project and ProjectMember models for multi-tenant project management."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc


class ProjectRole(str, enum.Enum):
    """Roles available for project members."""

    ADMIN = "admin"
    ANNOTATOR = "annotator"
    VIEWER = "viewer"


class Project(SQLModel, table=True):
    """A CEDARS annotation project."""

    __tablename__ = "projects"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    owner_id: str = Field(foreign_key="users.id")

    # LLM configuration (project-wide)
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)
    llm_api_key: str | None = Field(default=None, max_length=500)

    settings: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ProjectMember(SQLModel, table=True):
    """Association between a user and a project with a specific role."""

    __tablename__ = "project_members"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: ProjectRole = Field(default=ProjectRole.ANNOTATOR)
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
