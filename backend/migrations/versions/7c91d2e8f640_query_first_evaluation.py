"""Add immutable evaluation revisions and attempt lineage without inferred ownership."""

import sqlalchemy as sa
from alembic import op

revision = "7c91d2e8f640"
down_revision = "f4a9c21e7b83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluation_sessions_v2",
        sa.Column("workflow_version", sa.Integer(), nullable=False, server_default="1"),
    )
    with op.batch_alter_table("search_queries") as batch:
        batch.add_column(sa.Column("evaluation_session_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("syntax_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(
            sa.Column("source_queries", sa.JSON(), nullable=False, server_default="[]")
        )
        batch.create_foreign_key(
            "fk_query_evaluation_session",
            "evaluation_sessions_v2",
            ["evaluation_session_id"],
            ["id"],
        )
        batch.create_index("ix_search_queries_evaluation_session_id", ["evaluation_session_id"])
        batch.create_unique_constraint(
            "uq_query_session_revision", ["evaluation_session_id", "revision"]
        )
    op.create_table(
        "llm_prompt_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id", sa.String(), sa.ForeignKey("evaluation_sessions_v2.id"), nullable=False
        ),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("event_description", sa.String(), nullable=False),
        sa.Column("include_criteria", sa.String(), nullable=False),
        sa.Column("exclude_criteria", sa.String(), nullable=False),
        sa.Column("llm_provider", sa.String(), nullable=False),
        sa.Column("llm_model", sa.String(), nullable=False),
        sa.Column("llm_api_base", sa.String(), nullable=True),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("generation_settings", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "revision", name="uq_prompt_session_revision"),
    )
    op.create_index("ix_llm_prompt_revisions_session_id", "llm_prompt_revisions", ["session_id"])
    op.create_index("ix_llm_prompt_revisions_project_id", "llm_prompt_revisions", ["project_id"])
    op.create_table(
        "evaluation_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id", sa.String(), sa.ForeignKey("evaluation_sessions_v2.id"), nullable=False
        ),
        sa.Column("query_id", sa.String(), sa.ForeignKey("search_queries.id"), nullable=False),
        sa.Column("prompt_revision_id", sa.String(), sa.ForeignKey("llm_prompt_revisions.id")),
        sa.Column("source_attempt_id", sa.String(), sa.ForeignKey("evaluation_attempts.id")),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("sample_patient_ids", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String()),
        sa.Column("claim_token", sa.String()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "sequence", name="uq_attempt_session_sequence"),
    )
    op.create_index("ix_evaluation_attempts_session_id", "evaluation_attempts", ["session_id"])
    for table in ("search_matches", "patient_results", "pipeline_runs", "annotations"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("attempt_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_attempt", "evaluation_attempts", ["attempt_id"], ["id"]
            )
            batch.create_index(f"ix_{table}_attempt_id", ["attempt_id"])
            if table in ("pipeline_runs", "annotations"):
                batch.add_column(sa.Column("evaluation_session_id", sa.String(), nullable=True))
                batch.create_foreign_key(
                    f"fk_{table}_evaluation_session",
                    "evaluation_sessions_v2",
                    ["evaluation_session_id"],
                    ["id"],
                )
                batch.create_index(f"ix_{table}_evaluation_session_id", ["evaluation_session_id"])
            if table == "search_matches":
                batch.add_column(sa.Column("query_id", sa.String(), nullable=True))
                batch.create_foreign_key(
                    "fk_search_matches_query", "search_queries", ["query_id"], ["id"]
                )
            if table == "patient_results":
                batch.add_column(sa.Column("input_snapshot", sa.JSON(), nullable=True))
                batch.create_unique_constraint(
                    "uq_result_attempt_patient", ["attempt_id", "patient_id"]
                )
            if table == "annotations":
                batch.create_unique_constraint(
                    "uq_annotation_attempt_sentence",
                    ["attempt_id", "note_id", "sentence_start", "sentence_end"],
                )


def downgrade() -> None:
    for table in ("annotations", "pipeline_runs", "patient_results", "search_matches"):
        with op.batch_alter_table(table) as batch:
            if table == "annotations":
                batch.drop_constraint("uq_annotation_attempt_sentence", type_="unique")
            if table == "patient_results":
                batch.drop_constraint("uq_result_attempt_patient", type_="unique")
                batch.drop_column("input_snapshot")
            if table == "search_matches":
                batch.drop_constraint("fk_search_matches_query", type_="foreignkey")
                batch.drop_column("query_id")
            if table in ("pipeline_runs", "annotations"):
                batch.drop_index(f"ix_{table}_evaluation_session_id")
                batch.drop_constraint(f"fk_{table}_evaluation_session", type_="foreignkey")
                batch.drop_column("evaluation_session_id")
            batch.drop_index(f"ix_{table}_attempt_id")
            batch.drop_constraint(f"fk_{table}_attempt", type_="foreignkey")
            batch.drop_column("attempt_id")
    op.drop_table("evaluation_attempts")
    op.drop_table("llm_prompt_revisions")
    with op.batch_alter_table("search_queries") as batch:
        batch.drop_constraint("uq_query_session_revision", type_="unique")
        batch.drop_index("ix_search_queries_evaluation_session_id")
        batch.drop_constraint("fk_query_evaluation_session", type_="foreignkey")
        for column in ("source_queries", "syntax_version", "revision", "evaluation_session_id"):
            batch.drop_column(column)
    op.drop_column("evaluation_sessions_v2", "workflow_version")
