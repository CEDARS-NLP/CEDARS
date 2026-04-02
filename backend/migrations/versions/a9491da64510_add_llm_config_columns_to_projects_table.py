"""add llm config columns to projects table

Revision ID: a9491da64510
Revises: 9e2b3d31be5d
Create Date: 2026-03-30 18:19:15.867681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9491da64510'
down_revision: Union[str, Sequence[str], None] = '9e2b3d31be5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add LLM configuration columns to projects table."""
    op.add_column("projects", sa.Column("llm_provider", sa.String(50), nullable=True))
    op.add_column("projects", sa.Column("llm_model", sa.String(200), nullable=True))
    op.add_column("projects", sa.Column("llm_api_base", sa.String(500), nullable=True))


def downgrade() -> None:
    """Remove LLM configuration columns from projects table."""
    op.drop_column("projects", "llm_api_base")
    op.drop_column("projects", "llm_model")
    op.drop_column("projects", "llm_provider")
