"""Evaluation framework models."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, Text
from sqlmodel import Field, SQLModel


class SessionStatus(str, enum.Enum):
    SAMPLING = "sampling"
    RUNNING = "running"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class JudgmentValue(str, enum.Enum):
    PENDING = "pending"
    CORRECT = "correct"
    WRONG = "wrong"
    SKIPPED = "skipped"


class EvaluationSession(SQLModel, table=True):
    """An evaluation session: sample notes, run predictor, collect judgments."""

    __tablename__ = "evaluation_sessions"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    predictor_config_id: str = Field(foreign_key="predictor_configs.id")
    name: str = Field(default="")

    status: SessionStatus = Field(default=SessionStatus.SAMPLING)

    # Flexible sampling config stored as JSON
    sample_config: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )

    # Computed metrics (updated as judgments come in)
    metrics: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )

    total_notes: int = Field(default=0)
    judged_notes: int = Field(default=0)

    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class EvaluationJudgment(SQLModel, table=True):
    """A single note prediction + clinician judgment within an evaluation session."""

    __tablename__ = "evaluation_judgments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="evaluation_sessions.id", index=True)
    note_id: str = Field(foreign_key="notes.id")

    # Prediction from the model
    predicted_label: int | None = Field(default=None)  # 0 or 1
    predicted_score: float | None = Field(default=None)
    reasoning: str = Field(sa_column=Column(Text, nullable=False, server_default=""))

    # Clinician judgment
    judgment: JudgmentValue = Field(default=JudgmentValue.PENDING)
    judged_by: str | None = Field(default=None, foreign_key="users.id")
    judged_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ValidatedPredictor(SQLModel, table=True):
    """A predictor configuration validated via evaluation, ready for production."""

    __tablename__ = "validated_predictors"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    predictor_config_id: str = Field(foreign_key="predictor_configs.id")
    session_id: str = Field(foreign_key="evaluation_sessions.id")

    name: str
    notes: str = Field(sa_column=Column(Text, nullable=False, server_default=""))

    # Snapshot of config + metrics at validation time
    config_snapshot: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    metrics_snapshot: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    threshold: float = Field(default=0.5)

    is_active: bool = Field(default=False)

    validated_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
