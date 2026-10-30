"""Durable state for production note-level prediction and adjudication."""

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
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlmodel import Field

import app.projects.models  # noqa: F401
from app.common.model_registry import ProjectSQLModel
from app.common.utils import now_utc


class ProductionRun(ProjectSQLModel, table=True):
    """Immutable run identity plus mutable lifecycle and progress metadata."""

    __tablename__ = "production_runs"
    __table_args__ = (
        Index("ix_production_runs_project_created", "project_id", "created_at"),
        Index("ix_production_runs_project_status", "project_id", "status"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    created_by: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    status: str = Field(default="queued", max_length=20, index=True)
    config_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    config_fingerprint: str | None = Field(default=None, max_length=128)
    total_notes: int = Field(default=0)
    completed_notes: int = Field(default=0)
    failed_notes: int = Field(default=0)
    progress_metadata: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
    error_summary: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    cancelled_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


class ProductionState(ProjectSQLModel, table=True):
    """One project-scoped pointer to its active run; run history remains unrestricted."""

    __tablename__ = "production_states"

    project_id: str = Field(primary_key=True)
    active_run_id: str | None = Field(default=None, foreign_key="production_runs.id", unique=True)
    generation: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )


class NotePrediction(ProjectSQLModel, table=True):
    """The active production verdict and execution record for one source note."""

    __tablename__ = "note_predictions"
    __table_args__ = (
        UniqueConstraint("project_id", "text_id", name="uq_note_prediction_project_text"),
        ForeignKeyConstraint(
            ["project_id", "text_id", "patient_id"],
            ["notes.project_id", "notes.text_id", "notes.patient_id_ext"],
            name="fk_note_predictions_note_patient_external",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_note_predictions_status",
        ),
        CheckConstraint("label IS NULL OR label IN (0, 1)", name="ck_note_predictions_label"),
        Index("ix_note_predictions_run_status", "run_id", "status"),
    )

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True))
    project_id: str = Field(index=True)
    run_id: str = Field(foreign_key="production_runs.id", index=True)
    text_id: str = Field(max_length=100)
    patient_id: str = Field(max_length=100)
    note_uuid: str | None = Field(default=None, foreign_key="notes.id", index=True)
    patient_uuid: str | None = Field(default=None, foreign_key="patients.id", index=True)
    status: str = Field(default="queued", max_length=20)
    label: int | None = Field(default=None)
    score: float | None = Field(default=None)
    reasoning: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    evidence_spans: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    model_fingerprint: str | None = Field(default=None, max_length=128)
    config_fingerprint: str | None = Field(default=None, max_length=128)
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    attempts: int = Field(default=0)
    claimed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )


class ProductionResult(ProjectSQLModel, table=True):
    """One project-level production summary row per source patient (physical RESULTS)."""

    __tablename__ = "RESULTS"
    __table_args__ = (
        UniqueConstraint("project_id", "patient_uuid", name="uq_results_project_patient_uuid"),
        UniqueConstraint("project_id", "patient_id", name="uq_results_project_patient_ext"),
        ForeignKeyConstraint(
            ["project_id", "patient_id"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_results_patient_external",
        ),
        ForeignKeyConstraint(
            ["project_id", "patient_id", "event_annotation_id"],
            ["Annotations.project_id", "Annotations.patient_id", "Annotations.annotation_id"],
            name="fk_results_event_annotation_same_patient",
        ),
        CheckConstraint(
            "(event_date IS NULL AND event_annotation_id IS NULL) OR "
            "(event_date IS NOT NULL AND event_annotation_id IS NOT NULL)",
            name="ck_results_event_all_or_none",
        ),
        Index("ix_results_project_status", "project_id", "processing_status"),
    )

    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True))
    project_id: str = Field(index=True)
    patient_uuid: str = Field(foreign_key="patients.id", index=True)
    patient_id: str = Field(max_length=100)
    processing_status: str = Field(default="queued", max_length=20)
    review_status: str = Field(default="pending", max_length=20)
    review_type: str | None = Field(default=None, max_length=20)
    notes_total: int = Field(default=0)
    notes_processed: int = Field(default=0)
    notes_failed: int = Field(default=0)
    annotations_total: int = Field(default=0)
    annotations_pending: int = Field(default=0)
    annotations_reviewed: int = Field(default=0)
    annotations_skipped: int = Field(default=0)
    reason_counts: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    failure_count: int = Field(default=0)
    comments: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    event_information: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    index_no: int | None = Field(default=None)
    first_note_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_note_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    max_score: float | None = Field(default=None)
    max_score_note_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    max_score_note_id: str | None = Field(default=None, max_length=100)
    reviewer: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    reviewed_notes: int = Field(default=0)
    reviewed_sentences: int = Field(default=0)
    total_notes: int = Field(default=0)
    total_sentences: int = Field(default=0)
    last_updated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    event_date: date | None = Field(default=None, sa_column=Column(Date, nullable=True))
    event_annotation_id: int | None = Field(default=None)
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False, onupdate=func.now()),
    )


__all__ = ["NotePrediction", "ProductionResult", "ProductionRun", "ProductionState"]
