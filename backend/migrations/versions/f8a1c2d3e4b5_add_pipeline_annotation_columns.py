"""add pipeline annotation columns to annotations table

These 5 columns exist on the Annotation model but were never added by a
migration, so the migrated Postgres schema was missing them (SQLite/create_all
had them, which is why tests passed but the deployed app failed with
"column annotations.pipeline_run_id does not exist").

Revision ID: f8a1c2d3e4b5
Revises: d1f2a3b4c5e6
Create Date: 2026-07-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8a1c2d3e4b5"
down_revision: Union[str, Sequence[str], None] = "d1f2a3b4c5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pipeline-annotation columns, FKs, and indexes to annotations."""
    op.add_column("annotations", sa.Column("pipeline_run_id", sa.String(), nullable=True))
    op.add_column("annotations", sa.Column("patient_task_id", sa.Integer(), nullable=True))
    op.add_column("annotations", sa.Column("predicted_reasoning", sa.Text(), nullable=True))
    op.add_column("annotations", sa.Column("reviewer_label", sa.String(length=20), nullable=True))
    op.add_column("annotations", sa.Column("reviewer_notes", sa.Text(), nullable=True))

    op.create_index(
        op.f("ix_annotations_pipeline_run_id"), "annotations", ["pipeline_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_annotations_patient_task_id"), "annotations", ["patient_task_id"], unique=False
    )
    op.create_foreign_key(
        "annotations_pipeline_run_id_fkey",
        "annotations",
        "pipeline_runs",
        ["pipeline_run_id"],
        ["id"],
    )
    op.create_foreign_key(
        "annotations_patient_task_id_fkey",
        "annotations",
        "patient_tasks",
        ["patient_task_id"],
        ["id"],
    )

    # The model declares review_status as VARCHAR(20) ("to avoid PG enum
    # conflicts"), but the original migration created it as a native
    # `reviewstatus` enum. On Postgres that mismatch fails inserts with
    # "column review_status is of type reviewstatus but expression is of type
    # character varying". Convert the column to VARCHAR to match the model.
    # (No-op on SQLite, which has no native enum types.)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "annotations",
            "review_status",
            type_=sa.String(length=20),
            postgresql_using="review_status::text",
            existing_nullable=False,
        )
        op.execute("DROP TYPE IF EXISTS reviewstatus")


def downgrade() -> None:
    """Drop the pipeline-annotation columns and their constraints/indexes."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        reviewstatus = sa.Enum("UNREVIEWED", "REVIEWED", "SKIPPED", name="reviewstatus")
        reviewstatus.create(bind, checkfirst=True)
        op.alter_column(
            "annotations",
            "review_status",
            type_=reviewstatus,
            postgresql_using="review_status::reviewstatus",
            existing_nullable=False,
        )
    op.drop_constraint("annotations_patient_task_id_fkey", "annotations", type_="foreignkey")
    op.drop_constraint("annotations_pipeline_run_id_fkey", "annotations", type_="foreignkey")
    op.drop_index(op.f("ix_annotations_patient_task_id"), table_name="annotations")
    op.drop_index(op.f("ix_annotations_pipeline_run_id"), table_name="annotations")
    op.drop_column("annotations", "reviewer_notes")
    op.drop_column("annotations", "reviewer_label")
    op.drop_column("annotations", "predicted_reasoning")
    op.drop_column("annotations", "patient_task_id")
    op.drop_column("annotations", "pipeline_run_id")
