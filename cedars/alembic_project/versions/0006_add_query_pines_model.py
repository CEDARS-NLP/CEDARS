"""Record which PINES model a query selected.

Nullable, so existing queries keep working with no PINES model selected.
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_add_query_pines_model"
down_revision = "0005_add_llm_evaluation_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("Query", sa.Column("pines_model", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("Query", "pines_model")
