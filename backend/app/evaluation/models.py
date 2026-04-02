"""Unified evaluation session models.

Replaces: EventConfig, old EvaluationSession, EvaluationJudgment, ValidatedPredictor.

Phase 1: New models only. Old evaluation/service.py and evaluation/router.py
will be rewritten in subsequent tasks.
"""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, JSON, String, Text
from sqlmodel import Field, SQLModel


class SessionStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    COMMITTED = "committed"
    COMPLETED = "completed"
    DISCARDED = "discarded"


class PatientResultStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_MATCH = "no_match"


PATIENT_RESULT_TRANSITIONS = {
    PatientResultStatus.QUEUED: {PatientResultStatus.PROCESSING},
    PatientResultStatus.PROCESSING: {
        PatientResultStatus.COMPLETED,
        PatientResultStatus.FAILED,
        PatientResultStatus.NO_MATCH,
        PatientResultStatus.QUEUED,
    },
    PatientResultStatus.FAILED: {PatientResultStatus.QUEUED},
    PatientResultStatus.COMPLETED: set(),
    PatientResultStatus.NO_MATCH: set(),
}


class EvaluationSession(SQLModel, table=True):
    __tablename__ = "evaluation_sessions_v2"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)

    # Status — stored as VARCHAR to avoid PG enum conflicts with old migrations
    status: SessionStatus = Field(
        default=SessionStatus.DRAFT,
        sa_column=Column(String(20), nullable=False, default=SessionStatus.DRAFT.value),
    )

    # Search queries
    search_queries: list = Field(default=[], sa_column=Column(JSON, default=[]))

    # Event definition (what to look for)
    event_name: str | None = Field(default=None, max_length=200)
    event_description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    include_criteria: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    exclude_criteria: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    # Sample
    sample_patient_ids: list = Field(default=[], sa_column=Column(JSON, default=[]))
    sample_size: int = Field(default=100)

    # Metrics
    metrics: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Commit
    committed_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    committed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    committed_by: str | None = Field(default=None, foreign_key="users.id")

    # Clone
    cloned_from_id: str | None = Field(default=None, foreign_key="evaluation_sessions_v2.id")

    # Audit
    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class SearchMatch(SQLModel, table=True):
    __tablename__ = "search_matches"
    __table_args__ = (
        Index("ix_search_matches_session_query", "session_id", "query_index"),
        Index("ix_search_matches_session_patient", "session_id", "patient_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="evaluation_sessions_v2.id", index=True)
    query_index: int = Field(default=0)
    patient_id: str = Field(index=True)
    note_id: str = Field(foreign_key="notes.id", index=True)
    matched_tokens: list = Field(default=[], sa_column=Column(JSON, default=[]))
    match_positions: list = Field(default=[], sa_column=Column(JSON, default=[]))
    is_negated: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class PatientResult(SQLModel, table=True):
    __tablename__ = "patient_results"
    __table_args__ = (
        Index("ix_patient_results_session_status", "session_id", "status"),
        Index("ix_patient_results_run_status", "pipeline_run_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="evaluation_sessions_v2.id", index=True)
    pipeline_run_id: str | None = Field(default=None, foreign_key="pipeline_runs.id", index=True)
    patient_id: str = Field(index=True)

    # Search results
    notes_searched: int = Field(default=0)
    notes_matched: int = Field(default=0)

    # LLM classification
    finding_label: str | None = Field(default=None, max_length=20)
    finding_reasoning: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    finding_evidence: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    event_date: str | None = Field(default=None, max_length=10)  # ISO date string
    predicted_score: float | None = Field(default=None)
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Clinician review
    review_judgment: str | None = Field(default=None, max_length=20)
    reviewer_date_override: str | None = Field(default=None, max_length=10)
    reviewed_by: str | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Execution — stored as VARCHAR to avoid PG enum conflicts
    status: PatientResultStatus = Field(
        default=PatientResultStatus.QUEUED,
        sa_column=Column(String(20), nullable=False, default=PatientResultStatus.QUEUED.value),
    )
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )

    def transition_status(self, new_status: PatientResultStatus) -> None:
        allowed = PATIENT_RESULT_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition PatientResult from {self.status} to {new_status}"
            )
        self.status = new_status
