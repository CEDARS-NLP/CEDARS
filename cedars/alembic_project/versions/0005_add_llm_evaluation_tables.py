"""Add isolated, project-local LLM evaluation sessions and results."""
from alembic import op
import sqlalchemy as sa


revision = "0005_add_llm_evaluation_tables"
down_revision = "0004_add_data_sources_and_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "EvaluationSessions",
        sa.Column("eval_session_id", sa.String(length=36), primary_key=True),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("event_description", sa.Text(), nullable=False),
        sa.Column("include_criteria", sa.Text(), nullable=False),
        sa.Column("exclude_criteria", sa.Text(), nullable=False),
        sa.Column("search_queries", sa.JSON(), nullable=False),
        sa.Column("sample_patient_ids", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_evaluation_sessions_status", "EvaluationSessions", ["status", "created_at"]
    )
    op.create_table(
        "LLMEvaluationResults",
        sa.Column("evaluation_result_id", sa.String(length=36), primary_key=True),
        sa.Column("eval_session_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=100), nullable=False),
        sa.Column("note_id", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=False),
        sa.Column("predicted_label", sa.String(length=100), nullable=False),
        sa.Column("classification_threshold", sa.Float(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("review_judgment", sa.String(length=20), nullable=True),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["eval_session_id"], ["EvaluationSessions.eval_session_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "idx_llm_eval_session", "LLMEvaluationResults", ["eval_session_id", "evaluated_at"]
    )
    op.create_index(
        "idx_llm_eval_patient", "LLMEvaluationResults", ["patient_id", "evaluated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_llm_eval_patient", table_name="LLMEvaluationResults")
    op.drop_index("idx_llm_eval_session", table_name="LLMEvaluationResults")
    op.drop_table("LLMEvaluationResults")
    op.drop_index("idx_evaluation_sessions_status", table_name="EvaluationSessions")
    op.drop_table("EvaluationSessions")