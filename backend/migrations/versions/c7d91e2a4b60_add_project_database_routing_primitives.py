"""Add project database routing and local membership projection primitives.

Revision ID: c7d91e2a4b60
Revises: a8d4c6e2f109
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d91e2a4b60"
down_revision: Union[str, Sequence[str], None] = "a8d4c6e2f109"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("projects", "owner_id", new_column_name="Investigator")
    op.add_column("projects", sa.Column("database_secret_ref", sa.String(length=512)))
    op.add_column(
        "projects",
        sa.Column("database_status", sa.String(length=20), nullable=False, server_default="legacy"),
    )
    op.add_column("projects", sa.Column("database_schema_version", sa.String(length=64)))
    op.add_column(
        "projects",
        sa.Column("routing_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("projects", sa.Column("provisioning_error", sa.Text()))

    op.add_column(
        "project_members",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "project_members",
        sa.Column("added_by_kind", sa.String(length=20), nullable=False, server_default="unknown"),
    )
    op.add_column("project_members", sa.Column("added_by_user_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_project_members_added_by_user",
        "project_members",
        "users",
        ["added_by_user_id"],
        ["id"],
    )
    op.add_column(
        "project_members",
        sa.Column("membership_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "project_members",
        sa.Column("synced_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("project_members", sa.Column("revoked_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("project_members", "revoked_at")
    op.drop_column("project_members", "synced_revision")
    op.drop_column("project_members", "membership_revision")
    op.drop_constraint("fk_project_members_added_by_user", "project_members", type_="foreignkey")
    op.drop_column("project_members", "added_by_user_id")
    op.drop_column("project_members", "added_by_kind")
    op.drop_column("project_members", "is_active")

    op.drop_column("projects", "provisioning_error")
    op.drop_column("projects", "routing_version")
    op.drop_column("projects", "database_schema_version")
    op.drop_column("projects", "database_status")
    op.drop_column("projects", "database_secret_ref")
    op.alter_column("projects", "Investigator", new_column_name="owner_id")
