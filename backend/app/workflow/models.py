"""Models for the v1-style linear workflow.

- ``ReviewSession`` replaces the Flask session state used by v1's adjudication
  routes (``backup_session_data`` / ``restore_session_data`` in ops.py). It holds
  the in-progress ``patient_data`` produced by :class:`AdjudicationHandler` so a
  stateless JWT API can resume a review exactly where the annotator left off.
- ``PatientResult`` is a denormalized reporting table equivalent to v1's RESULTS
  collection, rebuilt by ``db.update_patient_results`` and consumed by the
  download/export routes.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc


class ReviewSession(SQLModel, table=True):
    """Persisted in-progress adjudication state for one patient.

    Mirrors v1's per-patient session backup. Keyed uniquely by
    ``(project_id, patient_id)`` because a patient is locked to a single
    reviewer at a time (see ``patients.locked_by``).
    """

    __tablename__ = "review_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "patient_id", name="uq_review_session_patient"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)

    # Serialized AdjudicationHandler.patient_data (review_statuses as ints,
    # dates as ISO strings) — see workflow.service (de)serialization helpers.
    patient_data: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    reviewed_annotation_ids: list = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    patient_comments: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )
    skip_after_event: bool = Field(default=False)
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PatientReviewResult(SQLModel, table=True):
    """Denormalized per-patient rollup used for download/export.

    Reporting table (values are derived from patients/notes/annotations) rebuilt
    by the "refresh results" internal-process op. Faithful to the columns emitted
    by v1's ``db.download_annotations`` (the v1 RESULTS collection).

    Named distinctly from ``evaluation.PatientResult`` (a different concept) to
    avoid a table-name collision.
    """

    __tablename__ = "patient_review_results"
    __table_args__ = (
        UniqueConstraint("project_id", "patient_id", name="uq_patient_result"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    patient_id: str = Field(foreign_key="patients.id", index=True)
    event_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    first_note_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_note_date: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    total_notes: int = Field(default=0)
    reviewed_notes: int = Field(default=0)
    total_sentences: int = Field(default=0)
    reviewed_sentences: int = Field(default=0)
    max_score: float | None = Field(default=None)
    comments: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )
    reviewed_by: str | None = Field(default=None)
    updated_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
