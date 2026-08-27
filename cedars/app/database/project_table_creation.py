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

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Double,
    String,
    Text,
    Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

logger.enable(__name__)


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

    # One-to-many relationship back to destinations, for convenient ORM navigation.
    Notes: Mapped[list["Notes"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    NotesSummary: Mapped[list["NotesSummary"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    Annotations: Mapped[list["Annotations"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    Events: Mapped[list["Events"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    PINES: Mapped[list["PINES"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    Results: Mapped[list["Results"]] = relationship(
        back_populates="Patients", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Patients(patient_id={self.patient_id!r}, locked={self.locked!r})"


class Notes(ProjectBase):
    """Notes table. patient_id is a foreign key into Patients.patient_id."""

    __tablename__ = "Notes"

    text_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    # Foreign key column, linking each note to a patient.
    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_date: Mapped[date] = mapped_column(Date, nullable=False)
    text_sequence: Mapped[int] = mapped_column(Integer, autoincrement=True,
                                               nullable=False)
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

    Annotations: Mapped[list["Annotations"]] = relationship(
        back_populates="Notes", cascade="all, delete-orphan"
    )

    PINES: Mapped[list["PINES"]] = relationship(
        back_populates="Notes", cascade="all, delete-orphan"
    )

    Results: Mapped[list["Results"]] = relationship(
        back_populates="Notes", cascade="all, delete-orphan"
    )

    ReviewerLog: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="Notes", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_notes_patient_date", "patient_id", "note_date"),
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Notes(text_id={self.text_id!r}, patient_id={self.patient_id!r})"

class NotesSummary(ProjectBase):
    """NotesSummary table."""

    __tablename__ = "NotesSummary"

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    first_note_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_note_date: Mapped[date] = mapped_column(Date, nullable=False)
    num_notes: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # for debugging and logging only
        return f"NotesSummary(patient_id={self.patient_id!r})"


class Annotations(ProjectBase):
    """Annotations table."""

    __tablename__ = "Annotations"

    annotation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    text_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Notes.text_id"), nullable=False
    )

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    sentence: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(String(200), nullable=False)
    isNegated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note_start_index: Mapped[int] = mapped_column(Integer, nullable=False)
    note_end_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_end: Mapped[int] = mapped_column(Integer, nullable=False)

    reviewed: Mapped[bool] = mapped_column(Boolean,
                                                 default=False,
                                                 nullable=False)

    Events: Mapped[list["Events"]] = relationship(
        back_populates="Annotations", cascade="all, delete-orphan"
    )

    ReviewerLog: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="Annotations", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Annotations(annotation_id={self.annotation_id!r}, text_id={self.text_id!r})"

class Events(ProjectBase):
    """Events table."""

    __tablename__ = "Events"

    patient_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Patients.patient_id"), nullable=False
    )

    has_event: Mapped[bool] = mapped_column(Boolean, nullable=False)

    annotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("Annotations.annotation_id"), nullable=True
    )

    event_date: Mapped[date] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Events(patient_id={self.patient_id!r})"

class PINES(ProjectBase):
    """PINES table."""

    __tablename__ = "PINES"

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

    Results: Mapped[list["Results"]] = relationship(
        back_populates="ProjectUsers", cascade="all, delete-orphan"
    )

    ReviewerLog: Mapped[list["ReviewerLog"]] = relationship(
        back_populates="ProjectUsers", cascade="all, delete-orphan"
    )

    Task: Mapped[list["Task"]] = relationship(
        back_populates="ProjectUsers", cascade="all, delete-orphan"
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

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Results(patient_id={self.patient_id!r})"

class ReviewerLog(ProjectBase):
    """ReviewerLog table."""

    __tablename__ = "ReviewerLog"

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
