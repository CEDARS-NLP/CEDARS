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

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Double,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

logger.enable(__name__)

SYSTEM_REVIEWERS = ("CEDARS", "PINES")


class ProjectBase(DeclarativeBase):
    """Shared declarative base for all ORM models."""

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

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False)

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

    def __repr__(self) -> str:  # for debugging and logging only
        return f"ProjectUsers(user_id={self.user_id!r})"


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

