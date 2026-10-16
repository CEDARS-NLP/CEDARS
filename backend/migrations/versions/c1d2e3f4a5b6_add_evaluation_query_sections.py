"""add display-only evaluation query sections

Revision ID: c1d2e3f4a5b6
Revises: b8d4e2f1a9c3
Create Date: 2026-10-16 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b8d4e2f1a9c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_session_query_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "position", name="uq_eval_query_section_position"),
    )
    op.create_index(
        "ix_evaluation_session_query_sections_session_id",
        "evaluation_session_query_sections",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluation_session_query_sections_session_id",
        table_name="evaluation_session_query_sections",
    )
    op.drop_table("evaluation_session_query_sections")