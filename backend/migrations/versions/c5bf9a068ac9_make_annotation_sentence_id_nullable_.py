"""make annotation sentence_id nullable for pipeline

Revision ID: c5bf9a068ac9
Revises: 2ceb76508e04
Create Date: 2026-03-29 23:00:41.116974

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5bf9a068ac9'
down_revision: Union[str, Sequence[str], None] = '2ceb76508e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make annotations.sentence_id nullable for pipeline-created annotations."""
    op.alter_column(
        "annotations",
        "sentence_id",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    """Restore annotations.sentence_id as NOT NULL."""
    # Backfill any NULLs before making non-nullable
    op.execute("DELETE FROM annotations WHERE sentence_id IS NULL")
    op.alter_column(
        "annotations",
        "sentence_id",
        existing_type=sa.String(),
        nullable=False,
    )
