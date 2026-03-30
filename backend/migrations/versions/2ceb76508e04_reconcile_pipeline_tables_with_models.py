"""reconcile pipeline tables with models

Revision ID: 2ceb76508e04
Revises: b4de01f3eae0
Create Date: 2026-03-29 22:30:52.608263

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ceb76508e04'
down_revision: Union[str, Sequence[str], None] = 'b4de01f3eae0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table (PostgreSQL)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    """Add missing columns and rename evidences -> evidence.

    The pipeline tables were partially created by a ghost migration.
    This reconciles the actual DB state with the SQLModel definitions.
    """

    # ── event_configs: add deleted_at ────────────────────────────
    if not _column_exists("event_configs", "deleted_at"):
        op.add_column(
            "event_configs",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ── pipeline_runs: add missing columns ───────────────────────
    if not _column_exists("pipeline_runs", "snapshot_version"):
        op.add_column(
            "pipeline_runs",
            sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"),
        )

    if not _column_exists("pipeline_runs", "processed_patients"):
        op.add_column(
            "pipeline_runs",
            sa.Column("processed_patients", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _column_exists("pipeline_runs", "failed_patients"):
        op.add_column(
            "pipeline_runs",
            sa.Column("failed_patients", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _column_exists("pipeline_runs", "progress"):
        op.add_column(
            "pipeline_runs",
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _column_exists("pipeline_runs", "updated_at"):
        op.add_column(
            "pipeline_runs",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        # Backfill updated_at from created_at
        op.execute("UPDATE pipeline_runs SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column("pipeline_runs", "updated_at", nullable=False)

    # ── patient_tasks: add created_at ────────────────────────────
    if not _column_exists("patient_tasks", "created_at"):
        op.add_column(
            "patient_tasks",
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        # Backfill from started_at or current time
        op.execute(
            "UPDATE patient_tasks SET created_at = COALESCE(started_at, NOW()) WHERE created_at IS NULL"
        )
        op.alter_column("patient_tasks", "created_at", nullable=False)

    # ── evidence: rename table if needed ─────────────────────────
    if _table_exists("evidences") and not _table_exists("evidence"):
        op.rename_table("evidences", "evidence")
    elif not _table_exists("evidence"):
        # Create from scratch if neither exists
        op.create_table(
            "evidence",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("patient_task_id", sa.Integer(), nullable=False),
            sa.Column("note_id", sa.String(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("start_pos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("end_pos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("match_source", sa.String(length=20), nullable=False),
            sa.Column("match_pattern", sa.String(length=500), nullable=False, server_default=""),
            sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
            sa.ForeignKeyConstraint(["patient_task_id"], ["patient_tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_evidence_patient_task_id"), "evidence", ["patient_task_id"])
        op.create_index(op.f("ix_evidence_note_id"), "evidence", ["note_id"])


def downgrade() -> None:
    """Reverse the reconciliation."""
    if _table_exists("evidence") and not _table_exists("evidences"):
        op.rename_table("evidence", "evidences")

    op.drop_column("patient_tasks", "created_at")
    op.drop_column("pipeline_runs", "updated_at")
    op.drop_column("pipeline_runs", "progress")
    op.drop_column("pipeline_runs", "failed_patients")
    op.drop_column("pipeline_runs", "processed_patients")
    op.drop_column("pipeline_runs", "snapshot_version")
    op.drop_column("event_configs", "deleted_at")
