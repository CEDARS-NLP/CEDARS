"""Data models for connectors, patients, and clinical notes."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint, func
from sqlmodel import Field, SQLModel

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


class DataSource(SQLModel, table=True):
    """A configured data source connection for a project."""

    __tablename__ = "data_sources"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
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


class Patient(SQLModel, table=True):
    """A patient record within a project."""

    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("project_id", "patient_id_ext", name="uq_patient_ext_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id_ext: str = Field(index=True)
    status: PatientStatus = Field(default=PatientStatus.NEW)
    locked_by: str | None = Field(default=None, foreign_key="users.id")
    locked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
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


class Note(SQLModel, table=True):
    """A clinical note belonging to a patient."""

    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint("project_id", "text_id", name="uq_note_text_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    text_id: str = Field(index=True)
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
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
