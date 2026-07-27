"""add v1 workflow tables and columns

Adds the schema needed to run the original CEDARS (v1) linear workflow on the
v2 SQL stack:

New tables:
  - note_tags               (BCNF replacement for NOTES.text_tag_1..5)
  - annotation_tokens       (BCNF per-token normalization of ANNOTATIONS)
  - note_predictions        (port of the PINES collection)
  - review_sessions         (replaces Flask adjudication session state)
  - patient_review_results  (port of the RESULTS collection)

Altered tables:
  - patients        (+reviewed_by, +event_date, +event_annotation_id, +comments)
  - notes           (+reviewed, +reviewed_by)
  - search_queries  (+use_negation, +tag_exact)
  - annotations     (+sentence_number, +sentence_start, +sentence_end, +text_date)

Revision ID: a1b2c3d4e5f6
Revises: f8a1c2d3e4b5
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8a1c2d3e4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Alter existing tables ---
    op.add_column(
        "patients",
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("event_annotation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("comments", sa.Text(), server_default="", nullable=False),
    )

    op.add_column(
        "notes",
        sa.Column("reviewed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "notes",
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )

    op.add_column(
        "search_queries",
        sa.Column("use_negation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "search_queries",
        sa.Column("tag_exact", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    op.add_column("annotations", sa.Column("sentence_number", sa.Integer(), nullable=True))
    op.add_column("annotations", sa.Column("sentence_start", sa.Integer(), nullable=True))
    op.add_column("annotations", sa.Column("sentence_end", sa.Integer(), nullable=True))
    op.add_column(
        "annotations",
        sa.Column("text_date", sa.DateTime(timezone=True), nullable=True),
    )

    # --- New tables ---
    op.create_table(
        "note_tags",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "position", name="uq_note_tag_position"),
    )
    op.create_index(op.f("ix_note_tags_note_id"), "note_tags", ["note_id"], unique=False)

    op.create_table(
        "annotation_tokens",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("annotation_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("token", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note_start_index", sa.Integer(), nullable=False),
        sa.Column("note_end_index", sa.Integer(), nullable=False),
        sa.Column("is_negated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_annotation_tokens_annotation_id"),
        "annotation_tokens",
        ["annotation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_annotation_tokens_token"), "annotation_tokens", ["token"], unique=False
    )

    op.create_table(
        "note_predictions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "predictor_name",
            sqlmodel.sql.sqltypes.AutoString(),
            server_default="PINES",
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "predictor_name", name="uq_note_prediction"),
    )
    op.create_index(
        op.f("ix_note_predictions_note_id"), "note_predictions", ["note_id"], unique=False
    )
    op.create_index(
        op.f("ix_note_predictions_project_id"), "note_predictions", ["project_id"], unique=False
    )

    op.create_table(
        "review_sessions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("reviewed_annotation_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("patient_comments", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "skip_after_event", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "patient_id", name="uq_review_session_patient"),
    )
    op.create_index(
        op.f("ix_review_sessions_patient_id"), "review_sessions", ["patient_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_sessions_project_id"), "review_sessions", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_review_sessions_user_id"), "review_sessions", ["user_id"], unique=False
    )

    op.create_table(
        "patient_review_results",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_note_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_note_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_notes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reviewed_notes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_sentences", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reviewed_sentences", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("comments", sa.Text(), server_default="", nullable=False),
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "patient_id", name="uq_patient_result"),
    )
    op.create_index(
        op.f("ix_patient_review_results_patient_id"),
        "patient_review_results",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_patient_review_results_project_id"),
        "patient_review_results",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_patient_review_results_project_id"), table_name="patient_review_results"
    )
    op.drop_index(
        op.f("ix_patient_review_results_patient_id"), table_name="patient_review_results"
    )
    op.drop_table("patient_review_results")

    op.drop_index(op.f("ix_review_sessions_user_id"), table_name="review_sessions")
    op.drop_index(op.f("ix_review_sessions_project_id"), table_name="review_sessions")
    op.drop_index(op.f("ix_review_sessions_patient_id"), table_name="review_sessions")
    op.drop_table("review_sessions")

    op.drop_index(op.f("ix_note_predictions_project_id"), table_name="note_predictions")
    op.drop_index(op.f("ix_note_predictions_note_id"), table_name="note_predictions")
    op.drop_table("note_predictions")

    op.drop_index(op.f("ix_annotation_tokens_token"), table_name="annotation_tokens")
    op.drop_index(
        op.f("ix_annotation_tokens_annotation_id"), table_name="annotation_tokens"
    )
    op.drop_table("annotation_tokens")

    op.drop_index(op.f("ix_note_tags_note_id"), table_name="note_tags")
    op.drop_table("note_tags")

    op.drop_column("annotations", "text_date")
    op.drop_column("annotations", "sentence_end")
    op.drop_column("annotations", "sentence_start")
    op.drop_column("annotations", "sentence_number")

    op.drop_column("search_queries", "tag_exact")
    op.drop_column("search_queries", "use_negation")

    op.drop_column("notes", "reviewed_by")
    op.drop_column("notes", "reviewed")

    op.drop_column("patients", "comments")
    op.drop_column("patients", "event_annotation_id")
    op.drop_column("patients", "event_date")
    op.drop_column("patients", "reviewed_by")
