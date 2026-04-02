"""add no_match to patienttaskstatus enum

Revision ID: ec642691720e
Revises: c5bf9a068ac9
Create Date: 2026-03-29 23:09:17.995139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec642691720e'
down_revision: Union[str, Sequence[str], None] = 'c5bf9a068ac9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add NO_MATCH value to patienttaskstatus PostgreSQL enum."""
    # Check if value already exists before adding
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_enum WHERE enumtypid = "
            "(SELECT oid FROM pg_type WHERE typname = 'patienttaskstatus') "
            "AND enumlabel = 'NO_MATCH'"
        )
    )
    if not result.scalar():
        op.execute("ALTER TYPE patienttaskstatus ADD VALUE IF NOT EXISTS 'NO_MATCH'")


def downgrade() -> None:
    """PostgreSQL does not support removing enum values; no-op."""
    pass
