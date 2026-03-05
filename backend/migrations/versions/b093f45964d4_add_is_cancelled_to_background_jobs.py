"""add is_cancelled to background_jobs

Revision ID: b093f45964d4
Revises: 6ff9ec5099f0
Create Date: 2026-03-04 21:47:15.314839

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b093f45964d4'
down_revision: Union[str, Sequence[str], None] = '6ff9ec5099f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('background_jobs', sa.Column('is_cancelled', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('background_jobs', 'is_cancelled')
