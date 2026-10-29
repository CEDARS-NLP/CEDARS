"""Frozen global database baseline; keeps legacy combined history separate."""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "g0001_global_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sa.Enum("PLATFORM_ADMIN", "USER", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "projects",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("Investigator", sa.String(), nullable=False),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("llm_model", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("llm_api_base", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("llm_api_key", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column("settings", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("database_secret_ref", sqlmodel.sql.sqltypes.AutoString(length=512)),
        sa.Column("database_status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("database_schema_version", sqlmodel.sql.sqltypes.AutoString(length=64)),
        sa.Column("routing_version", sa.Integer(), nullable=False),
        sa.Column("provisioning_error", sqlmodel.sql.sqltypes.AutoString()),
        sa.ForeignKeyConstraint(["Investigator"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
    op.create_table(
        "project_members",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "role", sa.Enum("ADMIN", "ANNOTATOR", "VIEWER", name="projectrole"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("added_by_kind", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("added_by_user_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("membership_revision", sa.Integer(), nullable=False),
        sa.Column("synced_revision", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_project_members_project_id"), "project_members", ["project_id"])
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"])


def downgrade() -> None:
    op.drop_table("project_members")
    op.drop_index(op.f("ix_projects_name"), table_name="projects")
    op.drop_table("projects")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
