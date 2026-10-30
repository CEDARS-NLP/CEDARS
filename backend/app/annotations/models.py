"""Annotation models for clinical event adjudication."""

import enum
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field

import app.projects.models  # noqa: F401
from app.common.model_registry import ProjectSQLModel
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


class ReviewType(str, enum.Enum):
    """How a patient, note, or annotation came to be reviewed."""

    NO_ANNOTATION = "no_annotation"
    NEGATION = "negation"
    LLM = "llm"
    HUMAN = "human"


class Annotation(ProjectSQLModel, table=True):
    """A production match row using the physical v1 Annotations contract."""

    __tablename__ = "Annotations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "patient_id"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_annotations_patient_external",
        ),
        ForeignKeyConstraint(
            ["project_id", "text_id", "patient_id"],
            ["notes.project_id", "notes.text_id", "notes.patient_id_ext"],
            name="fk_annotations_note_patient_external",
        ),
        UniqueConstraint("project_id", "patient_id", "annotation_id",
                         name="uq_annotations_project_patient_id"),
        CheckConstraint("status IN ('U', 'R', 'S')", name="ck_annotations_status"),
        Index("ix_annotations_project_patient_text", "project_id", "patient_id", "text_id"),
        Index(
            "ix_annotations_project_patient_status_date",
            "project_id", "patient_id", "status", "text_date",
        ),
        Index(
            "ix_annotations_project_text_negated_sentence",
            "project_id", "text_id", "isNegated", "sentence_number", "note_start_index",
        ),
    )

    annotation_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    project_id: str = Field(index=True)
    text_id: str = Field(max_length=100)
    patient_id: str = Field(max_length=100)
    text_date: date = Field(sa_column=Column(Date, nullable=False))
    sentence: str = Field(sa_column=Column(Text, nullable=False))
    token: str = Field(max_length=200)
    isNegated: bool = Field(sa_column=Column(Boolean, nullable=False))
    note_start_index: int = Field(sa_column=Column(Integer, nullable=False))
    note_end_index: int = Field(sa_column=Column(Integer, nullable=False))
    sentence_number: int = Field(sa_column=Column(Integer, nullable=False))
    sentence_start: int = Field(sa_column=Column(Integer, nullable=False))
    sentence_end: int = Field(sa_column=Column(Integer, nullable=False))
    status: str = Field(
        default="U",
        sa_column=Column(String(1), nullable=False, default="U", server_default="U"),
    )

    # UUID links are internal compatibility references, not external identity.
    patient_uuid: str | None = Field(default=None, foreign_key="patients.id", index=True)
    note_uuid: str | None = Field(default=None, foreign_key="notes.id", index=True)
    review_reason: str | None = Field(default=None, max_length=80)
    reviewed_by: str | None = Field(default=None, foreign_key="ProjectUsers.global_user_id")
    reviewed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    review_type: str | None = Field(default=None, max_length=20)
    actor_type: str | None = Field(default=None, max_length=20)
    prediction_id: int | None = Field(default=None)
    duplicate_of: int | None = Field(default=None, foreign_key="Annotations.annotation_id")
    skipped_by_event_annotation_id: int | None = Field(
        default=None, foreign_key="Annotations.annotation_id"
    )
    pipeline_run_id: str | None = Field(default=None, foreign_key="pipeline_runs.id", index=True)
    production_run_id: str | None = Field(default=None, foreign_key="production_runs.id")
    patient_task_id: int | None = Field(default=None, foreign_key="patient_tasks.id")
    reviewer_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def id(self) -> int | None:
        return self.annotation_id

    @property
    def note_id(self) -> str | None:
        return self.note_uuid

    @property
    def sentence_text(self) -> str:
        return self.sentence

    @sentence_text.setter
    def sentence_text(self, value: str) -> None:
        self.sentence = value

    @property
    def is_negated(self) -> bool:
        return self.isNegated

    @is_negated.setter
    def is_negated(self, value: bool) -> None:
        self.isNegated = value

    @property
    def review_status(self) -> ReviewStatus:
        return {
            "U": ReviewStatus.UNREVIEWED,
            "R": ReviewStatus.REVIEWED,
            "S": ReviewStatus.SKIPPED,
        }[self.status]

    @review_status.setter
    def review_status(self, value: ReviewStatus | str) -> None:
        normalized = value.value if isinstance(value, ReviewStatus) else value
        self.status = {
            ReviewStatus.UNREVIEWED.value: "U",
            ReviewStatus.PENDING.value: "U",
            ReviewStatus.REVIEWED.value: "R",
            ReviewStatus.CONFIRMED.value: "R",
            ReviewStatus.REJECTED.value: "R",
            ReviewStatus.SKIPPED.value: "S",
        }[normalized]


class AnnotationPrediction(ProjectSQLModel, table=True):
    """An optional predictor (LLM/PINES) verdict layered on top of an annotation.

    Keyword/spaCy matching alone produces annotations; running a predictor adds
    one of these rows per annotation without mutating the annotation itself.
    """

    __tablename__ = "annotation_predictions"
    __table_args__ = (
        UniqueConstraint(
            "annotation_id", "predictor_config_id", name="uq_annotation_prediction"
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    annotation_id: int = Field(foreign_key="Annotations.annotation_id", index=True)
    project_id: str = Field(index=True)
    predictor_config_id: str | None = Field(
        default=None, foreign_key="predictor_configs.id", index=True
    )

    predictor_model: str = Field(default="")
    predicted_score: float | None = Field(default=None)
    predicted_label: int | None = Field(default=None)  # 0 or 1
    reasoning: str = Field(sa_column=Column(Text, nullable=False, server_default=""))
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
