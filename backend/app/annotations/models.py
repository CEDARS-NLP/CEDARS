"""Annotation models for clinical event adjudication."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc


class ReviewStatus(str, enum.Enum):
    """Review status for an annotation."""

    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    SKIPPED = "skipped"
    # Pipeline-specific statuses
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Annotation(SQLModel, table=True):
    """A clinical annotation linking a target sentence to a prediction result.

    Created during bulk prediction runs. Reviewed by human annotators.
    """

    __tablename__ = "annotations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    note_id: str = Field(foreign_key="notes.id", index=True)
    sentence_id: str | None = Field(default=None, foreign_key="sentences.id", index=True)

    # Denormalized from sentence for fast access during review
    sentence_text: str = Field(sa_column=Column(Text, nullable=False))
    matched_tokens: str = Field(default="")  # comma-separated
    is_negated: bool = Field(default=False)

    # v1 workflow fields (faithful port of db.py ANNOTATIONS collection).
    # sentence_number/start/end locate the sentence within the note; text_date is
    # the denormalized note date used for ordering annotations during adjudication.
    sentence_number: int | None = Field(default=None)
    sentence_start: int | None = Field(default=None)
    sentence_end: int | None = Field(default=None)
    text_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Prediction result (from LLM/PINES)
    predicted_score: float | None = Field(default=None)
    predicted_label: int | None = Field(default=None)  # 0 or 1
    predictor_model: str = Field(default="")
    reasoning: str = Field(sa_column=Column(Text, nullable=False, server_default=""))

    # Review state — stored as VARCHAR to avoid PG enum conflicts
    review_status: ReviewStatus = Field(
        default=ReviewStatus.UNREVIEWED,
        sa_column=Column(String(20), nullable=False, default=ReviewStatus.UNREVIEWED.value),
    )
    reviewed_by: str | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Pipeline linkage (optional — set when created by pipeline runs)
    pipeline_run_id: str | None = Field(default=None, foreign_key="pipeline_runs.id", index=True)
    patient_task_id: int | None = Field(default=None, foreign_key="patient_tasks.id", index=True)
    predicted_reasoning: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    reviewer_label: str | None = Field(default=None, max_length=20)
    reviewer_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # Event tracking
    event_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnnotationToken(SQLModel, table=True):
    """A single matched token within an annotation's sentence.

    BCNF normalization of v1's per-token ANNOTATIONS documents: one
    ``annotations`` row represents a matched sentence, and each keyword match
    inside it (token text + character offsets + negation) becomes its own row.
    Drives the lemma/token distribution statistic.
    """

    __tablename__ = "annotation_tokens"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    annotation_id: str = Field(foreign_key="annotations.id", index=True)
    token: str = Field(index=True)
    note_start_index: int
    note_end_index: int
    is_negated: bool = Field(default=False)
