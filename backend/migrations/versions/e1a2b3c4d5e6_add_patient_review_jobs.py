"""Add durable patient-review batch jobs.

Revision ID: e1a2b3c4d5e6
Revises: d4e5f6a7b8c9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_review_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("patient_uuid", sa.String(), nullable=False),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("production_run_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("skip_after_event", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_requested_by", sa.String(), nullable=True),
        sa.Column("retry_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'discarded')",
            name="ck_patient_review_job_status",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_patient_review_attempts"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["retry_requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "reviewer_id", "idempotency_key",
            name="uq_patient_review_job_idempotency",
        ),
    )
    op.create_index(
        "ix_patient_review_jobs_project_status",
        "patient_review_jobs", ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_patient_review_jobs_patient_status",
        "patient_review_jobs", ["patient_uuid", "status"],
    )
    op.create_index("ix_patient_review_jobs_project_id", "patient_review_jobs", ["project_id"])
    op.create_index("ix_patient_review_jobs_patient_uuid", "patient_review_jobs", ["patient_uuid"])
    op.create_index("ix_patient_review_jobs_reviewer_id", "patient_review_jobs", ["reviewer_id"])
    op.create_index("ix_patient_review_jobs_status", "patient_review_jobs", ["status"])


def downgrade() -> None:
    for name in (
        "ix_patient_review_jobs_status",
        "ix_patient_review_jobs_reviewer_id",
        "ix_patient_review_jobs_patient_uuid",
        "ix_patient_review_jobs_project_id",
        "ix_patient_review_jobs_patient_status",
        "ix_patient_review_jobs_project_status",
    ):
        op.drop_index(name, table_name="patient_review_jobs")
    op.drop_table("patient_review_jobs")
