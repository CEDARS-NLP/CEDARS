"""add exclude_negated to evaluation sessions

Revision ID: b8d4e2f1a9c3
Revises: a7c3e91b5d20
Create Date: 2026-10-14 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d4e2f1a9c3"
down_revision: Union[str, Sequence[str], None] = "a7c3e91b5d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "evaluation_sessions_v2",
        sa.Column(
            "exclude_negated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("evaluation_sessions_v2", "exclude_negated")
