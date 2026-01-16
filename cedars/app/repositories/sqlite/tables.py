"""SQLAlchemy table definitions for SQLite backend."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class PatientTable(Base):
    """Patient records table."""

    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(100), unique=True, nullable=False, index=True)
    reviewed = Column(Boolean, default=False)
    locked = Column(Boolean, default=False)
    updated = Column(Boolean, default=False)
    comments = Column(Text, default="")
    reviewed_by = Column(String(100))
    event_date = Column(DateTime)
    event_annotation_id = Column(Integer)  # Reference to annotation
    admin_locked = Column(Boolean, default=False)
    index_no = Column(Integer, default=0)

    # Relationships
    notes = relationship("NoteTable", back_populates="patient")
    annotations = relationship("AnnotationTable", back_populates="patient")


class NoteTable(Base):
    """Clinical notes table."""

    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text_id = Column(String(100), unique=True, nullable=False, index=True)
    patient_id = Column(String(100), ForeignKey("patients.patient_id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    text_date = Column(DateTime)
    reviewed = Column(Boolean, default=False)
    reviewed_by = Column(String(100))
    text_tag_1 = Column(String(100))  # Document type
    text_tag_2 = Column(String(100))
    text_tag_3 = Column(String(100))  # Report type

    # Relationships
    patient = relationship("PatientTable", back_populates="notes")
    annotations = relationship("AnnotationTable", back_populates="note")

    __table_args__ = (
        Index("ix_notes_patient_text", "patient_id", "text_id", unique=True),
    )


class AnnotationTable(Base):
    """NLP annotations table."""

    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(100), ForeignKey("patients.patient_id"), nullable=False, index=True)
    note_id = Column(String(100), ForeignKey("notes.text_id"), nullable=False, index=True)
    sentence = Column(Text, nullable=False)
    token = Column(String(500))
    is_negated = Column(Boolean, default=False)
    note_start_index = Column(Integer, default=0)
    note_end_index = Column(Integer, default=0)
    sentence_number = Column(Integer, default=0)
    sentence_start = Column(Integer, default=0)
    sentence_end = Column(Integer, default=0)
    text_date = Column(DateTime)
    reviewed = Column(Integer, default=0)  # 0=UNREVIEWED, 1=REVIEWED, 2=SKIPPED

    # Relationships
    patient = relationship("PatientTable", back_populates="annotations")
    note = relationship("NoteTable", back_populates="annotations")

    __table_args__ = (
        Index("ix_annotations_patient_note", "patient_id", "note_id"),
        Index("ix_annotations_patient_reviewed", "patient_id", "reviewed"),
        Index("ix_annotations_note_reviewed", "note_id", "reviewed"),
        Index("ix_annotations_patient_date", "patient_id", "text_date", "reviewed"),
    )


class ResultTable(Base):
    """Aggregated patient results table."""

    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(100), unique=True, nullable=False, index=True)
    total_notes = Column(Integer, default=0)
    reviewed_notes = Column(Integer, default=0)
    total_sentences = Column(String(50), default="")
    reviewed_sentences = Column(Integer, default=0)
    sentences = Column(Text, default="")
    event_date = Column(DateTime)
    event_information = Column(Text, default="")
    first_note_date = Column(DateTime)
    last_note_date = Column(DateTime)
    comments = Column(Text, default="")
    reviewer = Column(String(100))
    max_score_note_id = Column(String(100))
    max_score_note_date = Column(DateTime)
    max_score = Column(Float)
    predicted_notes = Column(Text, default="")
    last_updated = Column(DateTime)
    index_no = Column(Integer, default=0)


class PredictionTable(Base):
    """PINES ML predictions table."""

    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text_id = Column(String(100), unique=True, nullable=False, index=True)
    patient_id = Column(String(100), index=True)
    text = Column(Text)
    text_date = Column(DateTime)
    predicted_score = Column(Float, default=0.0)
    report_type = Column(String(100))
    document_type = Column(String(100))


class UserTable(Base):
    """User accounts table."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    date_created = Column(DateTime, default=datetime.now)


class ProjectInfoTable(Base):
    """Project metadata table (single row)."""

    __tablename__ = "project_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    creation_time = Column(DateTime)
    project = Column(String(255))
    project_id = Column(String(100))
    investigator = Column(String(255))
    cedars_version = Column(String(50))
    pines_url = Column(String(500))
    is_pines_server_enabled = Column(Boolean, default=False)


class QueryTable(Base):
    """Search query configuration table."""

    __tablename__ = "queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, default="")
    exclude_negated = Column(Boolean, default=False)
    hide_duplicates = Column(Boolean, default=False)
    skip_after_event = Column(Boolean, default=False)
    tag_query_json = Column(Text)  # JSON serialized TagQuery
    date_min = Column(DateTime)
    date_max = Column(DateTime)
    current = Column(Boolean, default=False)


class TaskTable(Base):
    """Background task tracking table."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(100))
    description = Column(Text, default="")
    user = Column(String(100), default="")
    complete = Column(Boolean, default=False)
    progress = Column(Integer, default=0)


class NotesSummaryTable(Base):
    """Cached note statistics per patient."""

    __tablename__ = "notes_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String(100), unique=True, nullable=False, index=True)
    num_notes = Column(Integer, default=0)
    first_note_date = Column(DateTime)
    last_note_date = Column(DateTime)
