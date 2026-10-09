"""enforce single active search query per project

Revision ID: f4a9c21e7b83
Revises: d82c17b06f43
Create Date: 2026-10-07

Adds a partial unique index on search_queries (project_id) WHERE is_active
AND deleted_at IS NULL, so each project can have at most one active query.
Existing projects with multiple active queries are backfilled first: only
the most recently created active query stays active.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a9c21e7b83"
down_revision = "d82c17b06f43"
branch_labels = None
depends_on = None

# Keep only the newest active query per project (tie-break on id for
# deterministic ordering when created_at collides).
_BACKFILL_SQL = """
UPDATE search_queries AS sq
SET is_active = false
WHERE sq.deleted_at IS NULL
  AND sq.is_active = true
  AND sq.id NOT IN (
      SELECT DISTINCT ON (project_id) id
      FROM search_queries
      WHERE deleted_at IS NULL
        AND is_active = true
      ORDER BY project_id, created_at DESC, id DESC
  )
"""


def upgrade() -> None:
    # Backfill first: the partial unique index cannot be created while any
    # project still has more than one active query.
    op.execute(_BACKFILL_SQL)
    op.create_index(
        "uq_search_queries_project_active",
        "search_queries",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_active AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_search_queries_project_active",
        table_name="search_queries",
    )
