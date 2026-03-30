"""add ingestion to jobtype enum

Revision ID: c3a1e7f82d9b
Revises: b5f066242811
Create Date: 2026-03-04 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3a1e7f82d9b'
down_revision: Union[str, None] = 'b5f066242811'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'INGESTION'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
