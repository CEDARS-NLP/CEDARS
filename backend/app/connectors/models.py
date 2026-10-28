"""Data models for connectors, patients, and clinical notes."""

import enum
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlmodel import Field

import app.production.models  # noqa: F401
import app.projects.models  # noqa: F401
from app.common.model_registry import ProjectSQLModel
from app.common.utils import now_utc


class ConnectorType(str, enum.Enum):
    """Supported data connector types."""

    FILE_UPLOAD = "file_upload"
    DATABRICKS = "databricks"


class IngestionStatus(str, enum.Enum):
    """Status of a data source ingestion."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PatientStatus(str, enum.Enum):
    """Processing status for a patient record."""

    NEW = "new"
    NLP_PROCESSING = "nlp_processing"
    NLP_COMPLETE = "nlp_complete"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"


class DataSource(ProjectSQLModel, table=True):
    """A configured data source connection for a project."""

    __tablename__ = "data_sources"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    name: str
    connector_type: ConnectorType
    config: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    last_sync: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    status: IngestionStatus = Field(default=IngestionStatus.PENDING)
    row_count: int | None = Field(default=None)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Patient(ProjectSQLModel, table=True):
    """A patient record within a project."""

    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("project_id", "patient_id_ext", name="uq_patient_ext_id"),
        CheckConstraint(
            "(event_date IS NULL AND event_annotation_id IS NULL AND event_reviewer IS NULL) "
            "OR (event_date IS NOT NULL AND event_annotation_id IS NOT NULL "
            "AND event_reviewer IS NOT NULL)",
            name="ck_patient_event_all_or_none",
        ),
        ForeignKeyConstraint(
            ["project_id", "patient_id_ext", "event_annotation_id"],
            ["Annotations.project_id", "Annotations.patient_id", "Annotations.annotation_id"],
            name="fk_patient_event_annotation_same_patient",
            use_alter=True,
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    patient_id_ext: str = Field(index=True)
    status: PatientStatus = Field(default=PatientStatus.NEW)
    review_source: str | None = Field(default=None, max_length=20)
    review_reason: str | None = Field(default=None, max_length=80)
    review_type: str | None = Field(default=None, max_length=20)
    reviewed_by: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    reviewed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    locked_by: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    locked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    event_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    event_annotation_id: int | None = Field(default=None)
    event_reviewer: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    metadata_: dict = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False, server_default="{}"),
    )
    data_source_id: str | None = Field(default=None, foreign_key="data_sources.id")
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Note(ProjectSQLModel, table=True):
    """A clinical note belonging to a patient."""

    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("project_id", "text_id", name="uq_note_text_id"),
        UniqueConstraint(
            "project_id", "text_id", "patient_id_ext", name="uq_note_project_text_patient"
        ),
        Index("ix_notes_project_patient_deleted", "project_id", "patient_id", "deleted_at"),
        Index("ix_notes_patient_notedate", "patient_id", "note_date"),
        ForeignKeyConstraint(
            ["project_id", "patient_id_ext"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_notes_patient_external",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    text_id: str = Field(index=True)
    patient_id_ext: str | None = Field(default=None, max_length=100)
    note_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    text: str = Field(sa_column=Column(Text, nullable=False))
    metadata_: dict = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False, server_default="{}"),
    )
    source_ref: str | None = Field(default=None)
    data_source_id: str | None = Field(default=None, foreign_key="data_sources.id")
    review_status: str | None = Field(default=None, max_length=20)
    review_type: str | None = Field(default=None, max_length=20)
    reviewed_by: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
