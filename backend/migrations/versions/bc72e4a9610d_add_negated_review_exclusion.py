"""add negated review exclusion fields

Revision ID: bc72e4a9610d
Revises: a1c4e9d27b30
Create Date: 2026-10-05

"""

import sqlalchemy as sa
from alembic import op

revision = "bc72e4a9610d"
down_revision = "a1c4e9d27b30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "search_queries",
        sa.Column(
            "exclude_negated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "annotations",
        sa.Column(
            "review_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_annotations_review_excluded",
        "annotations",
        ["review_excluded"],
    )


def downgrade() -> None:
    op.drop_index("ix_annotations_review_excluded", table_name="annotations")
    op.drop_column("annotations", "review_excluded")
    op.drop_column("search_queries", "exclude_negated")
