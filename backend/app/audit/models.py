"""Audit log models."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Index
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc


class AuditAction(str, enum.Enum):
    """Auditable actions in the system."""

    # Annotation actions
    ANNOTATION_REVIEWED = "annotation_reviewed"
    ANNOTATION_SKIPPED = "annotation_skipped"
    EVENT_DATE_SET = "event_date_set"
    EVENT_DATE_DELETED = "event_date_deleted"

    # Patient actions
    PATIENT_LOCKED = "patient_locked"
    PATIENT_UNLOCKED = "patient_unlocked"
    PATIENT_REOPENED = "patient_reopened"

    # Model actions
    PREDICTION_RAN = "prediction_ran"
    AUTO_ADJUDICATED = "auto_adjudicated"

    # Data actions
    DATA_INGESTED = "data_ingested"
    DATA_PURGED = "data_purged"
    DATA_RESYNCED = "data_resynced"


class AuditEntry(SQLModel, table=True):
    """Append-only audit log entry."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_project_patient", "project_id", "patient_id"),
        Index("ix_audit_project_created", "project_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str | None = Field(default=None, foreign_key="patients.id")
    user_id: str | None = Field(default=None, foreign_key="users.id")
    action: AuditAction
    detail: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
