"""add llm_api_key to projects and event_configs

Revision ID: d1f2a3b4c5e6
Revises: afcb7a2b5eac
Create Date: 2026-06-30 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f2a3b4c5e6'
down_revision: Union[str, Sequence[str], None] = 'afcb7a2b5eac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects",
        sa.Column("llm_api_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "event_configs",
        sa.Column("llm_api_key", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("event_configs", "llm_api_key")
    op.drop_column("projects", "llm_api_key")
