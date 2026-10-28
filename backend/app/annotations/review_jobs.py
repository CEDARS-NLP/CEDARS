"""Durable asynchronous patient-review batches."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Index, Text, UniqueConstraint
from sqlmodel import Field

import app.projects.models  # noqa: F401
from app.common.model_registry import ProjectSQLModel
from app.common.utils import now_utc


class PatientReviewJob(ProjectSQLModel, table=True):
    """One complete patient adjudication batch, applied atomically by a worker."""

    __tablename__ = "patient_review_jobs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "reviewer_id", "idempotency_key",
            name="uq_patient_review_job_idempotency",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'discarded')",
            name="ck_patient_review_job_status",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_patient_review_attempts"),
        Index("ix_patient_review_jobs_project_status", "project_id", "status", "created_at"),
        Index("ix_patient_review_jobs_patient_status", "patient_uuid", "status"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    patient_uuid: str = Field(foreign_key="patients.id", index=True)
    reviewer_id: str = Field(foreign_key="ProjectUsers.global_user_id", index=True)
    production_run_id: str | None = Field(default=None, foreign_key="production_runs.id")
    idempotency_key: str = Field(max_length=100)
    payload: list[dict] = Field(sa_column=Column(JSON, nullable=False))
    skip_after_event: bool = Field(default=False)
    status: str = Field(default="queued", max_length=20, index=True)
    attempt_count: int = Field(default=0)
    retry_requested_by: str | None = Field(
        default=None, foreign_key="ProjectUsers.global_user_id"
    )
    retry_requested_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


__all__ = ["PatientReviewJob"]
