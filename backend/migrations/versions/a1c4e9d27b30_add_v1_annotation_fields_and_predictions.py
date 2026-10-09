"""add v1 annotation fields and annotation_predictions table

Revision ID: a1c4e9d27b30
Revises: f8a1c2d3e4b5
Create Date: 2026-10-01

"""

import sqlalchemy as sa
from alembic import op

revision = "a1c4e9d27b30"
down_revision = "f8a1c2d3e4b5"
branch_labels = None
depends_on = None


_NEW_ANNOTATION_COLUMNS = [
    ("token", sa.String()),
    ("note_start_index", sa.Integer()),
    ("note_end_index", sa.Integer()),
    ("sentence_number", sa.Integer()),
    ("sentence_start", sa.Integer()),
    ("sentence_end", sa.Integer()),
    ("text_date", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    for name, type_ in _NEW_ANNOTATION_COLUMNS:
        op.add_column("annotations", sa.Column(name, type_, nullable=True))

    op.create_table(
        "annotation_predictions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("annotation_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("predictor_config_id", sa.String(), nullable=True),
        sa.Column("predictor_model", sa.String(), nullable=False, server_default=""),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("predicted_label", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "annotation_id", "predictor_config_id", name="uq_annotation_prediction"
        ),
    )
    op.create_index(
        "ix_annotation_predictions_annotation_id",
        "annotation_predictions",
        ["annotation_id"],
    )
    op.create_index(
        "ix_annotation_predictions_project_id",
        "annotation_predictions",
        ["project_id"],
    )
    op.create_index(
        "ix_annotation_predictions_predictor_config_id",
        "annotation_predictions",
        ["predictor_config_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_annotation_predictions_predictor_config_id", table_name="annotation_predictions"
    )
    op.drop_index("ix_annotation_predictions_project_id", table_name="annotation_predictions")
    op.drop_index("ix_annotation_predictions_annotation_id", table_name="annotation_predictions")
    op.drop_table("annotation_predictions")

    for name, _type in reversed(_NEW_ANNOTATION_COLUMNS):
        op.drop_column("annotations", name)
