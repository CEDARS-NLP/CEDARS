"""Add review_type columns and note-level review fields.

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5e6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "Annotations",
        sa.Column("review_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("review_type", sa.String(length=20), nullable=True),
    )
    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(sa.Column("review_status", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("review_type", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_notes_reviewed_by_users",
            "users",
            ["reviewed_by"],
            ["id"],
        )
    op.add_column(
        "RESULTS",
        sa.Column("review_type", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("RESULTS", "review_type")
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_constraint("fk_notes_reviewed_by_users", type_="foreignkey")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("review_type")
        batch_op.drop_column("review_status")
    op.drop_column("patients", "review_type")
    op.drop_column("Annotations", "review_type")
