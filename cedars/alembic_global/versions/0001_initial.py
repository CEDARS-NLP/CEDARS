'''
0001_initial.py

Baseline migration for the global application database. Creates the schema
from the current GlobalBase ORM metadata (Users, Projects, UserProjectRelation)
rather than hand-written op.create_table calls, so this stays in sync with
global_app_tables.py by construction. Future schema changes should be added as
new revisions generated via `alembic revision --autogenerate`.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
'''
from alembic import op

from cedars.app.database.global_app_tables import GlobalBase

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    GlobalBase.metadata.create_all(op.get_bind())


def downgrade() -> None:
    GlobalBase.metadata.drop_all(op.get_bind())
