"""add llm_usage ledger

Revision ID: a7c3e91b5d20
Revises: f4a9c21e7b83
Create Date: 2026-10-12

Append-only per-project record of LLM token usage. New table only; no data to
backfill (earlier per-patient usage stays on patient_results.token_usage).
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e91b5d20"
down_revision = "f4a9c21e7b83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_usage_project_id", "llm_usage", ["project_id"])
    op.create_index("ix_llm_usage_project_created", "llm_usage", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_project_created", table_name="llm_usage")
    op.drop_index("ix_llm_usage_project_id", table_name="llm_usage")
    op.drop_table("llm_usage")
