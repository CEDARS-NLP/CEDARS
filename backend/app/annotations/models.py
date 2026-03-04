"""Annotation models for clinical event adjudication."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Text
from sqlmodel import Field, SQLModel


class ReviewStatus(str, enum.Enum):
    """Review status for an annotation."""

    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    SKIPPED = "skipped"


class Annotation(SQLModel, table=True):
    """A clinical annotation linking a target sentence to a prediction result.

    Created during bulk prediction runs. Reviewed by human annotators.
    """

    __tablename__ = "annotations"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    note_id: str = Field(foreign_key="notes.id", index=True)
    sentence_id: str = Field(foreign_key="sentences.id", index=True)

    # Denormalized from sentence for fast access during review
    sentence_text: str = Field(sa_column=Column(Text, nullable=False))
    matched_tokens: str = Field(default="")  # comma-separated
    is_negated: bool = Field(default=False)

    # Prediction result (from LLM/PINES)
    predicted_score: float | None = Field(default=None)
    predicted_label: int | None = Field(default=None)  # 0 or 1
    predictor_model: str = Field(default="")
    reasoning: str = Field(sa_column=Column(Text, nullable=False, server_default=""))

    # Review state
    review_status: ReviewStatus = Field(default=ReviewStatus.UNREVIEWED)
    reviewed_by: str | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Event tracking
    event_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
