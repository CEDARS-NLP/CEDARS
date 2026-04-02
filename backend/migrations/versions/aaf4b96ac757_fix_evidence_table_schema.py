"""fix evidence table schema

Revision ID: aaf4b96ac757
Revises: ec642691720e
Create Date: 2026-03-29 23:30:18.906772

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aaf4b96ac757'
down_revision: Union[str, Sequence[str], None] = 'ec642691720e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Recreate evidence table with correct schema (autoincrement integer PK).

    The ghost migration created the table with varchar id and wrong column types.
    The model expects: id SERIAL PRIMARY KEY, patient_task_id INTEGER, etc.
    """
    # Drop and recreate — no production data in evidence yet
    op.drop_table("evidence")
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
    op.create_index("ix_evidence_patient_task_id", "evidence", ["patient_task_id"])
    op.create_index("ix_evidence_note_id", "evidence", ["note_id"])


def downgrade() -> None:
    """Drop evidence table (will be recreated by reconcile migration on downgrade)."""
    op.drop_table("evidence")
