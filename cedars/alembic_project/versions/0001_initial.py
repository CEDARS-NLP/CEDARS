'''
0001_initial.py

Baseline migration for a project database. Creates the schema from the current
ProjectBase ORM metadata (Patients, Notes, Annotations, ... ProjectSettings)
rather than hand-written op.create_table calls, so this stays in sync with
project_table_creation.py by construction. Future schema changes should be
added as new revisions generated via `alembic revision --autogenerate` (run
once, then fanned out to every existing project database).

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
'''
from alembic import op

from cedars.app.database.project_table_creation import ProjectBase

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    ProjectBase.metadata.create_all(op.get_bind())


def downgrade() -> None:
    ProjectBase.metadata.drop_all(op.get_bind())
