"""Project and ProjectMember models for multi-tenant project management."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String
from sqlmodel import Field

from app.common.model_registry import GlobalSQLModel, ProjectSQLModel
from app.common.utils import now_utc


class ProjectRole(str, enum.Enum):
    """Roles available for project members."""

    ADMIN = "admin"
    ANNOTATOR = "annotator"
    VIEWER = "viewer"


class Project(GlobalSQLModel, table=True):
    """A CEDARS annotation project."""

    __tablename__ = "projects"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True)
    description: str = Field(default="")
    owner_id: str = Field(
        sa_column=Column("Investigator", String, ForeignKey("users.id"), nullable=False)
    )

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
    database_secret_ref: str | None = Field(default=None, max_length=512)
    database_status: str = Field(default="legacy", max_length=20)
    database_schema_version: str | None = Field(default=None, max_length=64)
    routing_version: int = Field(default=1, ge=1)
    provisioning_error: str | None = Field(default=None)


class ProjectMember(GlobalSQLModel, table=True):
    """Association between a user and a project with a specific role."""

    __tablename__ = "project_members"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: ProjectRole = Field(default=ProjectRole.ANNOTATOR)
    is_active: bool = Field(default=True)
    added_by_kind: str = Field(default="unknown", max_length=20)
    added_by_user_id: str | None = Field(default=None, foreign_key="users.id")
    membership_revision: int = Field(default=1, ge=1)
    synced_revision: int = Field(default=0, ge=0)
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ProjectUser(ProjectSQLModel, table=True):
    """Project-local identity and permission projection for a global user."""

    __tablename__ = "ProjectUsers"

    global_user_id: str = Field(primary_key=True)
    project_id: str = Field(index=True)
    email: str = Field(index=True)
    name: str
    role: ProjectRole = Field(
        default=ProjectRole.ANNOTATOR,
        sa_column=Column(String(20), nullable=False),
    )
    is_investigator: bool = Field(default=False)
    is_active: bool = Field(default=True)
    added_by_kind: str = Field(default="unknown", max_length=20)
    added_by_user_id: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    membership_revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
