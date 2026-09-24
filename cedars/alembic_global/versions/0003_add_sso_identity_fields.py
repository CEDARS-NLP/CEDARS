'''
0003_add_sso_identity_fields.py

Adds nullable SSO identity metadata to the global Users table while preserving
local username/password accounts.

Revision ID: 0003_add_sso_identity_fields
Revises: 0002_add_project_redis_credentials
Create Date: 2026-09-23
'''
import sqlalchemy as sa
from alembic import op

revision = "0003_add_sso_identity_fields"
down_revision = "0002_add_project_redis_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("Users", sa.Column("auth_provider", sa.String(50), nullable=True))
    op.add_column("Users", sa.Column("sso_subject", sa.String(255), nullable=True))
    op.add_column("Users", sa.Column("sso_email", sa.String(255), nullable=True))
    op.add_column("Users", sa.Column("sso_email_verified", sa.Boolean(), nullable=True))
    op.add_column("Users", sa.Column("sso_groups_json", sa.Text(), nullable=True))
    op.add_column("Users", sa.Column("last_login_time", sa.DateTime(), nullable=True))
    op.create_index("ix_users_sso_email", "Users", ["sso_email"])
    op.create_index(
        "ix_users_auth_provider_sso_subject",
        "Users",
        ["auth_provider", "sso_subject"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_auth_provider_sso_subject", table_name="Users")
    op.drop_index("ix_users_sso_email", table_name="Users")
    op.drop_column("Users", "last_login_time")
    op.drop_column("Users", "sso_groups_json")
    op.drop_column("Users", "sso_email_verified")
    op.drop_column("Users", "sso_email")
    op.drop_column("Users", "sso_subject")
    op.drop_column("Users", "auth_provider")