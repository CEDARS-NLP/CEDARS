'''
0002_add_project_redis_credentials.py

Adds the ProjectRedisCredentials table (per-project Redis ACL identity, used
to scope RQ queues/the RQ dashboard so one project cannot see another's jobs).

Revision ID: 0002_add_project_redis_credentials
Revises: 0001_initial
Create Date: 2026-09-11
'''
import sqlalchemy as sa
from alembic import op

revision = "0002_add_project_redis_credentials"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ProjectRedisCredentials",
        sa.Column("project_id", sa.String(100),
                 sa.ForeignKey("Projects.project_id"), primary_key=True),
        sa.Column("redis_username", sa.String(150), nullable=False),
        sa.Column("redis_secret", sa.String(200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ProjectRedisCredentials")
