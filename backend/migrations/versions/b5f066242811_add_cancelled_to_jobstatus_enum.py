"""add cancelled to jobstatus enum

Revision ID: b5f066242811
Revises: b093f45964d4
Create Date: 2026-03-04 22:33:22.162590

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5f066242811'
down_revision: Union[str, Sequence[str], None] = 'b093f45964d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'cancelled' value to the jobstatus PostgreSQL enum."""
    op.execute("ALTER TYPE jobstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    """PostgreSQL does not support removing enum values; no-op."""
    pass
