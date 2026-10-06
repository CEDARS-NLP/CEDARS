"""add patient review metadata and manual annotation override

Revision ID: d82c17b06f43
Revises: bc72e4a9610d
Create Date: 2026-10-06

"""

import sqlalchemy as sa
from alembic import op

revision = "d82c17b06f43"
down_revision = "bc72e4a9610d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("review_source", sa.String(20), nullable=True))
    op.add_column("patients", sa.Column("review_reason", sa.String(80), nullable=True))
    op.add_column("patients", sa.Column("reviewed_by", sa.String(), nullable=True))
    op.add_column(
        "patients",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_patients_reviewed_by_users",
        "patients",
        "users",
        ["reviewed_by"],
        ["id"],
    )
    op.add_column(
        "annotations",
        sa.Column(
            "manual_review_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("annotations", "manual_review_override")
    op.drop_constraint("fk_patients_reviewed_by_users", "patients", type_="foreignkey")
    op.drop_column("patients", "reviewed_at")
    op.drop_column("patients", "reviewed_by")
    op.drop_column("patients", "review_reason")
    op.drop_column("patients", "review_source")