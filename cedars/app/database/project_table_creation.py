"""
project_table_creation.py
This module defines project-specific database tables for the CEDARS application.

All projects have the same schema, but each project has its own database.
The tables defined here are created in the project-specific database when a new project is initialized.
"""

from __future__ import annotations

from loguru import logger
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Double,
    JSON,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..schemas import ProjectRole

logger.enable(__name__)

SYSTEM_REVIEWERS = ("CEDARS", "PINES")


class ProjectBase(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class DataSources(ProjectBase):
    """A project-local data ingestion source and its latest sync state."""

    __tablename__ = "DataSources"

    source_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_data_sources_active", "deleted_at", "created_at"),
    )


class BackgroundJobs(ProjectBase):
    """Durable project-local lifecycle state for work executed by ARQ."""

    __tablename__ = "BackgroundJobs"

    job_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    arq_job_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_background_jobs_recent", "created_at"),
        Index("idx_background_jobs_status", "status", "created_at"),
    )


class Patients(ProjectBase):
    """
    Table for unique patient information, the primary_key is 'patient_id'.
    Its primary key is referenced by:
        - Notes.patient_id.
    """

    __tablename__ = "Patients"

    patient_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    admin_locked: Mapped[bool] = mapped_column(Boolean,
                                               default=False,
                                               nullable=False)

    # VARCHAR-equivalent: bounded-length text.
    comments: Mapped[str] = mapped_column(String(500), nullable=False)

    index_no: Mapped[int] = mapped_column(Integer, nullable=False)

    locked: Mapped[bool] = mapped_column(Boolean,
                                             default=False,
                                             nullable=False)

    reviewed: Mapped[bool] = mapped_column(Boolean,
                                             default=False,
                                             nullable=False)

    last_reviewed_by: Mapped[str] = mapped_column(String(100), nullable=True)

    pines_query_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("Query.query_id"), nullable=True
    )
    pines_status: Mapped[str] = mapped_column(String(20), nullable=True)
    pines_error: Mapped[str] = mapped_column(String(500), nullable=True)

    data_source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("DataSources.source_id"), nullable=True
    )
    workflow_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    updated: Mapped[bool] = mapped_column(Boolean,
                                             default=False,
                                             nullable=False)

    notes: Mapped[list["Notes"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    notes_summary: Mapped[Optional["NotesSummary"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", uselist=False
    )

    annotations: Mapped[list["Annotations"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    event: Mapped[Optional["Events"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", uselist=False
    )

    pines_predictions: Mapped[list["PINES"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    result: Mapped[Optional["Results"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Patients(patient_id={self.patient_id!r}, locked={self.locked!r})"


class Notes(ProjectBase):
    """Notes table. patient_id is a foreign key into Patients.patient_id.
    
    The foreign key constraint is DEFERRABLE INITIALLY DEFERRED to allow for
    transactional insertion of parents (Patients) and children (Notes) in
    any order within a single transaction, validating only at commit time.
    This serves as a safety net against insertion order bugs.
    """

    __tablename__ = "Notes"

    text_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    # Foreign key column, linking each note to a patient.
    # DEFERRABLE INITIALLY DEFERRED allows flexible insertion order within transactions.
    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id", deferrable=True, initially="DEFERRED"), nullable=False
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_date: Mapped[date] = mapped_column(Date, nullable=False)
    text_sequence: Mapped[int] = mapped_column(Integer, nullable=True)
    text_tag_1: Mapped[str] = mapped_column(String(100),
                                            default="",
                                            nullable=False)
    text_tag_2: Mapped[str] = mapped_column(String(100),
                                            default="",
                                            nullable=False)
    text_tag_3: Mapped[str] = mapped_column(String(100),
                                            default="",
                                            nullable=False)
    text_tag_4: Mapped[str] = mapped_column(String(100),
                                            default="",
                                            nullable=False)

    reviewed: Mapped[bool] = mapped_column(Boolean,
                                                 default=False,
                                                 nullable=False)

    data_source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("DataSources.source_id"), nullable=True
    )

    patient: Mapped["Patients"] = relationship(back_populates="notes")

    annotations: Mapped[list["Annotations"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )

    pines_prediction: Mapped[Optional["PINES"]] = relationship(
        back_populates="note", cascade="all, delete-orphan", uselist=False
    )

    reviewer_logs: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="note", cascade="all, delete-orphan"
    )

    max_score_results: Mapped[list["Results"]] = relationship(
        back_populates="max_score_note",
        foreign_keys="Results.max_score_note_id",
    )

    __table_args__ = (
        Index("idx_notes_patient_date", "patient_id", "text_date"),
        Index("idx_notes_patient", "patient_id"),
        Index("idx_notes_data_source", "data_source_id"),
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Notes(text_id={self.text_id!r}, patient_id={self.patient_id!r})"

class NotesSummary(ProjectBase):
    """NotesSummary table.
    
    The foreign key constraint is DEFERRABLE INITIALLY DEFERRED to allow for
    transactional insertion of parents (Patients) and children (NotesSummary) in
    any order within a single transaction, validating only at commit time.
    This serves as a safety net against insertion order bugs.
    """

    __tablename__ = "NotesSummary"

    # One row per patient: patient_id doubles as the primary key.
    # DEFERRABLE INITIALLY DEFERRED allows flexible insertion order within transactions.
    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id", deferrable=True, initially="DEFERRED"), primary_key=True
    )

    first_note_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_note_date: Mapped[date] = mapped_column(Date, nullable=False)
    num_notes: Mapped[int] = mapped_column(Integer, nullable=False)

    patient: Mapped["Patients"] = relationship(back_populates="notes_summary")

    def __repr__(self) -> str:  # for debugging and logging only
        return f"NotesSummary(patient_id={self.patient_id!r})"


class Annotations(ProjectBase):
    """Annotations table.

    `status` replaces mongo's 3-state ReviewStatus enum (cedars_enums.ReviewStatus)
    as a single character: "U"=UNREVIEWED, "R"=REVIEWED, "S"=SKIPPED (annotation
    falls after a patient's recorded event date and is excluded from review).
    """

    __tablename__ = "Annotations"

    STATUS_UNREVIEWED = "U"
    STATUS_REVIEWED = "R"
    STATUS_SKIPPED = "S"

    annotation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    text_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Notes.text_id"), nullable=False
    )

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    # Denormalized from Notes.text_date so review-status queries and the
    # composite indices below don't need to join Notes on every lookup.
    text_date: Mapped[date] = mapped_column(Date, nullable=False)

    sentence: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(String(200), nullable=False)
    isNegated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note_start_index: Mapped[int] = mapped_column(Integer, nullable=False)
    note_end_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_end: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(1),
                                        default=STATUS_UNREVIEWED,
                                        nullable=False)

    note: Mapped["Notes"] = relationship(back_populates="annotations")

    patient: Mapped["Patients"] = relationship(back_populates="annotations")

    event_references: Mapped[list["Events"]] = relationship(
        back_populates="event_annotation",
        foreign_keys="Events.annotation_id",
    )

    reviewer_logs: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="annotation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_annotations_patient_text", "patient_id", "text_id"),
        Index("idx_annotations_patient_isneg_date_text_start",
             "patient_id", "isNegated", "text_date", "text_id", "note_start_index"),
        Index("idx_annotations_patient_date_status", "patient_id", "text_date", "status"),
        Index("idx_annotations_text_status", "text_id", "status"),
        Index("idx_annotations_patient_status", "patient_id", "status"),
        Index("idx_annotations_text_isneg_date_sentnum",
             "text_id", "isNegated", "text_date", "sentence_number"),
        Index("idx_annotations_text_isneg_date_sentnum_start",
             "text_id", "isNegated", "text_date", "sentence_number", "note_start_index"),
        Index("idx_annotations_patient_isneg_status_sentnum_text_date",
             "patient_id", "isNegated", "status", "sentence_number", "text_id", "text_date"),
        Index("idx_annotations_patient_start_text_date",
             "patient_id", "note_start_index", "text_id", "text_date"),
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Annotations(annotation_id={self.annotation_id!r}, text_id={self.text_id!r})"

class Events(ProjectBase):
    """Events table.

    One row per patient (patient_id is unique) holding that patient's current
    clinical-event state - equivalent to the event_date/event_annotation_id
    fields mongo embedded directly on the PATIENTS document.
    """

    __tablename__ = "Events"

    event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    has_event: Mapped[bool] = mapped_column(Boolean, nullable=False)

    annotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("Annotations.annotation_id"), nullable=True
    )

    event_date: Mapped[date] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("patient_id", name="uq_events_patient_id"),
    )

    patient: Mapped["Patients"] = relationship(back_populates="event")

    event_annotation: Mapped[Optional["Annotations"]] = relationship(
        back_populates="event_references",
        foreign_keys=[annotation_id],
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Events(patient_id={self.patient_id!r})"

class PINES(ProjectBase):
    """PINES table."""

    __tablename__ = "PINES"

    prediction_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    text_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Notes.text_id"), nullable=False
    )

    text_date: Mapped[date] = mapped_column(Date, nullable=False)
    max_predicted_score: Mapped[Decimal] = mapped_column(Double, nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    classification_threshold: Mapped[Decimal] = mapped_column(Double, nullable=False)
    report_type: Mapped[str] = mapped_column(String(100), nullable=True)
    document_type: Mapped[str] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        # one prediction per note
        UniqueConstraint("text_id", name="uq_pines_text_id"),
        Index("idx_pines_patient", "patient_id"),
    )

    patient: Mapped["Patients"] = relationship(back_populates="pines_predictions")

    note: Mapped["Notes"] = relationship(back_populates="pines_prediction")

    def __repr__(self) -> str:  # for debugging and logging only
        return f"PINES(patient_id={self.patient_id!r}, text_id={self.text_id!r})"

class ProjectUsers(ProjectBase):
    """ProjectUsers table.
    Table for all users in a project.

    The date_registered is the date the user was added to the project,
    not the date they registered for the CEDARS application.
    """

    __tablename__ = "ProjectUsers"

    user_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectRole.ANNOTATOR.value
    )

    date_registered: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    results_reviewed: Mapped[list["Results"]] = relationship(
        back_populates="reviewer_user",
        foreign_keys="Results.reviewer",
    )

    reviewer_logs: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="reviewer_user",
        foreign_keys="ReviewerLog.reviewer",
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="user",
        foreign_keys="Task.user_id",
    )

    @property
    def is_admin(self) -> bool:
        return self.role in {ProjectRole.ADMIN.value, ProjectRole.INVESTIGATOR.value}

    @is_admin.setter
    def is_admin(self, value: bool) -> None:
        self.role = ProjectRole.ADMIN.value if value else ProjectRole.ANNOTATOR.value

    def __repr__(self) -> str:  # for debugging and logging only
        return f"ProjectUsers(user_id={self.user_id!r})"


class ProjectAuditLog(ProjectBase):
    """Project-local audit trail for membership and project actions."""

    __tablename__ = "ProjectAuditLog"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target: Mapped[str] = mapped_column(String(100), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)

    def __repr__(self) -> str:
        return f"ProjectAuditLog(audit_id={self.audit_id!r}, action={self.action!r})"


class Results(ProjectBase):
    """Results table."""

    __tablename__ = "Results"

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), primary_key=True
    )
    comments: Mapped[str] = mapped_column(Text, nullable=False)

    event_date: Mapped[date] = mapped_column(Date, nullable=True)
    event_information: Mapped[str] = mapped_column(Text, nullable=True)
    index_no: Mapped[int] = mapped_column(Integer, nullable=False)

    first_note_date: Mapped[date] = mapped_column(Date, nullable=True)
    last_note_date: Mapped[date] = mapped_column(Date, nullable=True)

    max_score: Mapped[Decimal] = mapped_column(Double, nullable=True)
    max_score_note_date: Mapped[date] = mapped_column(Date, nullable=True)
    max_score_note_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Notes.text_id"), nullable=True
    )

    reviewed_notes: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_sentences: Mapped[int] = mapped_column(Integer, nullable=False)
    total_notes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_sentences: Mapped[int] = mapped_column(Integer, nullable=False)

    reviewer: Mapped[str] = mapped_column(
        String(100), ForeignKey("ProjectUsers.user_id"), nullable=True
    )

    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    patient: Mapped["Patients"] = relationship(back_populates="result")

    max_score_note: Mapped[Optional["Notes"]] = relationship(
        back_populates="max_score_results",
        foreign_keys=[max_score_note_id],
    )

    reviewer_user: Mapped[Optional["ProjectUsers"]] = relationship(
        back_populates="results_reviewed",
        foreign_keys=[reviewer],
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Results(patient_id={self.patient_id!r})"

class ReviewerLog(ProjectBase):
    """ReviewerLog table."""

    __tablename__ = "ReviewerLog"

    log_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    text_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Notes.text_id"), nullable=False
    )

    annotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("Annotations.annotation_id"), nullable=True
    )

    reviewer: Mapped[str] = mapped_column(
        String(100), ForeignKey("ProjectUsers.user_id"), nullable=False
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    note: Mapped["Notes"] = relationship(back_populates="reviewer_logs")

    annotation: Mapped[Optional["Annotations"]] = relationship(
        back_populates="reviewer_logs"
    )

    reviewer_user: Mapped["ProjectUsers"] = relationship(
        back_populates="reviewer_logs",
        foreign_keys=[reviewer],
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"ReviewerLog(text_id={self.text_id!r}, reviewer={self.reviewer!r})"

class Task(ProjectBase):
    """Task table."""

    __tablename__ = "Task"

    task_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    user_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("ProjectUsers.user_id"), nullable=False
    )

    complete: Mapped[bool] = mapped_column(Boolean, 
                                             default=False,
                                             nullable=False)
    progress: Mapped[int] = mapped_column(Integer,
                                          default=0,
                                          nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", name="uq_task_job_id"),
    )

    user: Mapped["ProjectUsers"] = relationship(
        back_populates="tasks",
        foreign_keys=[user_id],
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Task(job_id={self.job_id!r}, user_id={self.user_id!r})"

class Query(ProjectBase):
    """Query table."""

    __tablename__ = "Query"

    query_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    query: Mapped[str] = mapped_column(Text, nullable=False)

    exclude_negated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hide_duplicates: Mapped[bool] = mapped_column(Boolean, nullable=False)
    skip_after_event: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tag_query_exact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    apply_pines: Mapped[bool] = mapped_column(Boolean, nullable=False)
    apply_llm: Mapped[bool] = mapped_column(Boolean, nullable=False)
    
    date_min: Mapped[date] = mapped_column(Date, nullable=True)
    date_max: Mapped[date] = mapped_column(Date, nullable=True)
    current: Mapped[bool] = mapped_column(Boolean,
                                          default=True,
                                          nullable=False)

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Query(query_id={self.query_id!r})"


class ProjectSettings(ProjectBase):
    """ProjectSettings table.

    One row per project database, holding project-level configuration that
    mongo kept in the INFO document (e.g. PINES integration settings).
    """

    __tablename__ = "ProjectSettings"

    # Single-row table: fixed id keeps upserts simple (id=1 always).
    settings_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    pines_url: Mapped[str] = mapped_column(Text, nullable=True)
    is_pines_server_enabled: Mapped[bool] = mapped_column(Boolean,
                                                          default=False,
                                                          nullable=False)

    def __repr__(self) -> str:  # for debugging and logging only
        return f"ProjectSettings(settings_id={self.settings_id!r})"


class EvaluationSessions(ProjectBase):
    """Project-local configuration and lifecycle for an isolated evaluation."""

    __tablename__ = "EvaluationSessions"

    eval_session_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    include_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    exclude_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    search_queries: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sample_patient_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )

    __table_args__ = (Index("idx_evaluation_sessions_status", "status", "created_at"),)


class LLMEvaluationResults(ProjectBase):
    """PINES outputs and review state, isolated from CEDARS workflow tables."""

    __tablename__ = "LLMEvaluationResults"

    evaluation_result_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    eval_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("EvaluationSessions.eval_session_id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[str] = mapped_column(String(100), nullable=False)
    note_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    predicted_score: Mapped[float] = mapped_column(Double, nullable=False)
    predicted_label: Mapped[str] = mapped_column(String(100), nullable=False)
    classification_threshold: Mapped[float] = mapped_column(Double, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    review_judgment: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_llm_eval_session", "eval_session_id", "evaluated_at"),
        Index("idx_llm_eval_patient", "patient_id", "evaluated_at"),
    )

