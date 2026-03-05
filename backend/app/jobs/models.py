"""Generic background job model for ARQ task tracking."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, Text
from sqlmodel import Field, SQLModel


class JobType(str, enum.Enum):
    """Types of background jobs."""

    NLP = "nlp"
    PREDICTION = "prediction"
    EXPORT = "export"


class JobStatus(str, enum.Enum):
    """Status of a background job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundJob(SQLModel, table=True):
    """Tracks background jobs dispatched via ARQ."""

    __tablename__ = "background_jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    job_type: JobType
    arq_job_id: str | None = Field(default=None, index=True)
    status: JobStatus = Field(default=JobStatus.PENDING)
    progress: int = Field(default=0)
    result_summary: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_cancelled: bool = Field(default=False)
    created_by: str | None = Field(default=None, foreign_key="users.id")
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
