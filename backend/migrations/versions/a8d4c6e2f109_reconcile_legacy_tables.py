"""Reconcile legacy prediction and evaluation tables with current usage.

Revision ID: a8d4c6e2f109
Revises: f2b3c4d5e6a7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8d4c6e2f109"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "annotation_predictions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("annotation_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("predictor_config_id", sa.String(), nullable=True),
        sa.Column("predictor_model", sa.String(), nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("predicted_label", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), server_default="", nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["Annotations.annotation_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "annotation_id", "predictor_config_id", name="uq_annotation_prediction"
        ),
    )
    for column in ("annotation_id", "project_id", "predictor_config_id"):
        op.create_index(
            op.f(f"ix_annotation_predictions_{column}"),
            "annotation_predictions",
            [column],
            unique=False,
        )

    op.drop_table("evaluation_judgments")
    op.drop_table("validated_predictors")
    op.drop_table("evaluation_sessions")

    bind = op.get_bind()
    sa.Enum("SAMPLING", "RUNNING", "REVIEWING", "COMPLETED", "FAILED", name="sessionstatus").drop(
        bind, checkfirst=True
    )
    sa.Enum("PENDING", "CORRECT", "WRONG", "SKIPPED", name="judgmentvalue").drop(
        bind, checkfirst=True
    )


def downgrade() -> None:
    for column in ("predictor_config_id", "project_id", "annotation_id"):
        op.drop_index(
            op.f(f"ix_annotation_predictions_{column}"),
            table_name="annotation_predictions",
        )
    op.drop_table("annotation_predictions")

    op.create_table(
        "evaluation_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("predictor_config_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SAMPLING", "RUNNING", "REVIEWING", "COMPLETED", "FAILED",
                name="sessionstatus",
            ),
            nullable=False,
        ),
        sa.Column("sample_config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("metrics", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("judged_notes", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_sessions_project_id"),
        "evaluation_sessions",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "validated_predictors",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("predictor_config_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("config_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("validated_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions.id"]),
        sa.ForeignKeyConstraint(["validated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_validated_predictors_project_id"),
        "validated_predictors",
        ["project_id"],
        unique=False,
    )

    op.create_table(
        "evaluation_judgments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("note_id", sa.String(), nullable=False),
        sa.Column("predicted_label", sa.Integer(), nullable=True),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "judgment",
            sa.Enum("PENDING", "CORRECT", "WRONG", "SKIPPED", name="judgmentvalue"),
            nullable=False,
        ),
        sa.Column("judged_by", sa.String(), nullable=True),
        sa.Column("judged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["judged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_judgments_session_id"),
        "evaluation_judgments",
        ["session_id"],
        unique=False,
    )
