"""Data models for NLP pipeline: sentences and search queries."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class Sentence(SQLModel, table=True):
    """A sentence extracted from a clinical note by the NLP pipeline."""

    __tablename__ = "sentences"
    __table_args__ = (
        UniqueConstraint("note_id", "sentence_number", name="uq_sentence_note_pos"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    note_id: str = Field(foreign_key="notes.id", index=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    sentence_number: int
    text: str = Field(sa_column=Column(Text, nullable=False))
    start_pos: int  # character offset in the note
    end_pos: int
    is_negated: bool = Field(default=False)
    is_target: bool = Field(default=False)  # matched a search query
    matched_tokens: list = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SearchQuery(SQLModel, table=True):
    """A search query pattern configured for a project.

    Queries use the CEDARS syntax: OR/AND operators, ! for negation, * and ? wildcards.
    Example: (DVT OR embolus) AND !suspected
    """

    __tablename__ = "search_queries"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    name: str = Field(default="")
    query: str  # CEDARS query syntax
    is_active: bool = Field(default=True)
    nlp_apply: bool = Field(default=True)  # apply predictor after NLP
    hide_duplicates: bool = Field(default=True)  # filter duplicate sentences
    skip_after_event: bool = Field(default=True)  # skip sentences after event date
    created_by: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class NlpJobStatus(str, enum.Enum):
    """Status of an NLP processing job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NlpJob(SQLModel, table=True):
    """Tracks NLP processing jobs for a project."""

    __tablename__ = "nlp_jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    status: NlpJobStatus = Field(default=NlpJobStatus.PENDING)
    total_notes: int = Field(default=0)
    processed_notes: int = Field(default=0)
    error_message: str | None = Field(default=None)
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
