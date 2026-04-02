"""add updated_at to patients table

Revision ID: afcb7a2b5eac
Revises: a9491da64510
Create Date: 2026-03-31 20:16:08.923232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'afcb7a2b5eac'
down_revision: Union[str, Sequence[str], None] = 'a9491da64510'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "patients",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Backfill existing rows: set updated_at = created_at
    op.execute("UPDATE patients SET updated_at = created_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("patients", "updated_at")
