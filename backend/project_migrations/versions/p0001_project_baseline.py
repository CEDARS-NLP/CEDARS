"""Frozen tenant schema baseline, independent of the historical combined chain."""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "p0001_project_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ProjectUsers",
        sa.Column("global_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_investigator", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("added_by_kind", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("added_by_user_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("membership_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("global_user_id"),
    )
    op.create_index(op.f("ix_ProjectUsers_email"), "ProjectUsers", ["email"])
    op.create_index(op.f("ix_ProjectUsers_project_id"), "ProjectUsers", ["project_id"])
    op.create_table(
        "data_sources",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "connector_type",
            sa.Enum("FILE_UPLOAD", "DATABRICKS", name="connectortype"),
            nullable=False,
        ),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("last_sync", sa.DateTime(timezone=True)),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="ingestionstatus"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer()),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_data_sources_project_id"), "data_sources", ["project_id"])
    op.create_table(
        "event_configs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("include_criteria", sa.Text(), nullable=False),
        sa.Column("exclude_criteria", sa.Text(), server_default="", nullable=False),
        sa.Column("search_patterns", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("llm_provider", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column("llm_model", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("llm_api_base", sqlmodel.sql.sqltypes.AutoString(length=500)),
        sa.Column("llm_api_key", sqlmodel.sql.sqltypes.AutoString(length=500)),
        sa.Column("confidence_threshold", sa.Float()),
        sa.Column("is_committed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_event_configs_project_id"), "event_configs", ["project_id"])
    op.create_table(
        "nlp_jobs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", name="nlpjobstatus"),
            nullable=False,
        ),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("processed_notes", sa.Integer(), nullable=False),
        sa.Column("error_message", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_nlp_jobs_project_id"), "nlp_jobs", ["project_id"])
    op.create_table(
        "background_jobs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column(
            "job_type",
            sa.Enum("NLP", "PREDICTION", "EXPORT", "INGESTION", name="jobtype"),
            nullable=False,
        ),
        sa.Column("arq_job_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("result_summary", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_background_jobs_arq_job_id"), "background_jobs", ["arq_job_id"])
    op.create_index(op.f("ix_background_jobs_project_id"), "background_jobs", ["project_id"])
    op.create_table(
        "evaluation_sessions_v2",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("search_queries", sa.JSON()),
        sa.Column("exclude_negated", sa.Boolean(), nullable=False),
        sa.Column("event_name", sqlmodel.sql.sqltypes.AutoString(length=200)),
        sa.Column("event_description", sa.Text()),
        sa.Column("include_criteria", sa.Text()),
        sa.Column("exclude_criteria", sa.Text()),
        sa.Column("sample_patient_ids", sa.JSON()),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON()),
        sa.Column("committed_config", sa.JSON()),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("committed_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("cloned_from_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["cloned_from_id"], ["evaluation_sessions_v2.id"]),
        sa.ForeignKeyConstraint(["committed_by"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_sessions_v2_project_id"), "evaluation_sessions_v2", ["project_id"]
    )
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("ref_id", sqlmodel.sql.sqltypes.AutoString(length=64)),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(length=50)),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(length=200)),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_project_created", "llm_usage", ["project_id", "created_at"])
    op.create_index(op.f("ix_llm_usage_project_id"), "llm_usage", ["project_id"])
    op.create_table(
        "patients",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id_ext", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "NLP_PROCESSING",
                "NLP_COMPLETE",
                "REVIEWING",
                "REVIEWED",
                name="patientstatus",
            ),
            nullable=False,
        ),
        sa.Column("review_source", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("review_reason", sqlmodel.sql.sqltypes.AutoString(length=80)),
        sa.Column("review_type", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("event_date", sa.Date()),
        sa.Column("event_annotation_id", sa.Integer()),
        sa.Column("event_reviewer", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("data_source_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(event_date IS NULL AND event_annotation_id IS NULL AND event_reviewer IS NULL) OR (event_date IS NOT NULL AND event_annotation_id IS NOT NULL AND event_reviewer IS NOT NULL)",
            name="ck_patient_event_all_or_none",
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["event_reviewer"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(["locked_by"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "patient_id_ext", "event_annotation_id"],
            ["Annotations.project_id", "Annotations.patient_id", "Annotations.annotation_id"],
            name="fk_patient_event_annotation_same_patient",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "patient_id_ext", name="uq_patient_ext_id"),
    )
    op.create_index(op.f("ix_patients_patient_id_ext"), "patients", ["patient_id_ext"])
    op.create_index(op.f("ix_patients_project_id"), "patients", ["project_id"])
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("event_config_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("run_type", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "completed", "failed", "cancelled", name="pipelinerunstatus"
            ),
            nullable=False,
        ),
        sa.Column("config_snapshot", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("total_patients", sa.Integer(), nullable=False),
        sa.Column("processed_patients", sa.Integer(), nullable=False),
        sa.Column("failed_patients", sa.Integer(), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("result_summary", sa.JSON()),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["event_config_id"], ["event_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipeline_runs_event_config_id"), "pipeline_runs", ["event_config_id"])
    op.create_index(op.f("ix_pipeline_runs_project_id"), "pipeline_runs", ["project_id"])
    op.create_table(
        "predictor_configs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("predictor_type", sa.Enum("LLM", "PINES", name="predictortype"), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["created_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_predictor_configs_project_id"), "predictor_configs", ["project_id"])
    op.create_table(
        "production_runs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("config_fingerprint", sqlmodel.sql.sqltypes.AutoString(length=128)),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("completed_notes", sa.Integer(), nullable=False),
        sa.Column("failed_notes", sa.Integer(), nullable=False),
        sa.Column("progress_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["created_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_production_runs_project_created", "production_runs", ["project_id", "created_at"]
    )
    op.create_index(op.f("ix_production_runs_project_id"), "production_runs", ["project_id"])
    op.create_index(
        "ix_production_runs_project_status", "production_runs", ["project_id", "status"]
    )
    op.create_index(op.f("ix_production_runs_status"), "production_runs", ["status"])
    op.create_table(
        "search_queries",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("query", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("nlp_apply", sa.Boolean(), nullable=False),
        sa.Column("hide_duplicates", sa.Boolean(), nullable=False),
        sa.Column("skip_after_event", sa.Boolean(), nullable=False),
        sa.Column("exclude_negated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["created_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_search_queries_project_id"), "search_queries", ["project_id"])
    op.create_index(
        "uq_search_queries_project_active",
        "search_queries",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_active AND deleted_at IS NULL"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column(
            "action",
            sa.Enum(
                "ANNOTATION_REVIEWED",
                "ANNOTATION_SKIPPED",
                "EVENT_DATE_SET",
                "EVENT_DATE_DELETED",
                "PATIENT_LOCKED",
                "PATIENT_UNLOCKED",
                "PATIENT_REOPENED",
                "PREDICTION_RAN",
                "AUTO_ADJUDICATED",
                "DATA_INGESTED",
                "DATA_PURGED",
                "DATA_RESYNCED",
                name="auditaction",
            ),
            nullable=False,
        ),
        sa.Column("detail", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_project_id"), "audit_log", ["project_id"])
    op.create_index("ix_audit_project_created", "audit_log", ["project_id", "created_at"])
    op.create_index("ix_audit_project_patient", "audit_log", ["project_id", "patient_id"])
    op.create_table(
        "evaluation_session_query_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "position", name="uq_eval_query_section_position"),
    )
    op.create_index(
        op.f("ix_evaluation_session_query_sections_session_id"),
        "evaluation_session_query_sections",
        ["session_id"],
    )
    op.create_table(
        "notes",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id_ext", sqlmodel.sql.sqltypes.AutoString(length=100)),
        sa.Column("note_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("source_ref", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("data_source_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("review_status", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("review_type", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "patient_id_ext"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_notes_patient_external",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "text_id", "patient_id_ext", name="uq_note_project_text_patient"
        ),
        sa.UniqueConstraint("project_id", "text_id", name="uq_note_text_id"),
    )
    op.create_index(op.f("ix_notes_patient_id"), "notes", ["patient_id"])
    op.create_index("ix_notes_patient_notedate", "notes", ["patient_id", "note_date"])
    op.create_index(op.f("ix_notes_project_id"), "notes", ["project_id"])
    op.create_index(
        "ix_notes_project_patient_deleted", "notes", ["project_id", "patient_id", "deleted_at"]
    )
    op.create_index(op.f("ix_notes_text_id"), "notes", ["text_id"])
    op.create_table(
        "patient_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pipeline_run_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("notes_searched", sa.Integer(), nullable=False),
        sa.Column("notes_matched", sa.Integer(), nullable=False),
        sa.Column("finding_label", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("finding_reasoning", sa.Text()),
        sa.Column("finding_evidence", sa.JSON()),
        sa.Column("event_date", sqlmodel.sql.sqltypes.AutoString(length=10)),
        sa.Column("predicted_score", sa.Float()),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("review_judgment", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("reviewer_date_override", sqlmodel.sql.sqltypes.AutoString(length=10)),
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_results_patient_id"), "patient_results", ["patient_id"])
    op.create_index(
        op.f("ix_patient_results_pipeline_run_id"), "patient_results", ["pipeline_run_id"]
    )
    op.create_index(
        "ix_patient_results_run_status", "patient_results", ["pipeline_run_id", "status"]
    )
    op.create_index(op.f("ix_patient_results_session_id"), "patient_results", ["session_id"])
    op.create_index(
        "ix_patient_results_session_status", "patient_results", ["session_id", "status"]
    )
    op.create_table(
        "patient_review_jobs",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_uuid", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reviewer_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("production_run_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("idempotency_key", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("skip_after_event", sa.Boolean(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("retry_requested_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("retry_requested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'discarded')",
            name="ck_patient_review_job_status",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_patient_review_attempts"),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["production_runs.id"]),
        sa.ForeignKeyConstraint(["retry_requested_by"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "reviewer_id", "idempotency_key", name="uq_patient_review_job_idempotency"
        ),
    )
    op.create_index(
        "ix_patient_review_jobs_patient_status", "patient_review_jobs", ["patient_uuid", "status"]
    )
    op.create_index(
        op.f("ix_patient_review_jobs_patient_uuid"), "patient_review_jobs", ["patient_uuid"]
    )
    op.create_index(
        op.f("ix_patient_review_jobs_project_id"), "patient_review_jobs", ["project_id"]
    )
    op.create_index(
        "ix_patient_review_jobs_project_status",
        "patient_review_jobs",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        op.f("ix_patient_review_jobs_reviewer_id"), "patient_review_jobs", ["reviewer_id"]
    )
    op.create_index(op.f("ix_patient_review_jobs_status"), "patient_review_jobs", ["status"])
    op.create_table(
        "patient_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "processing", "completed", "failed", "no_match", name="patienttaskstatus"
            ),
            nullable=False,
        ),
        sa.Column("notes_searched", sa.Integer(), nullable=False),
        sa.Column("notes_matched", sa.Integer(), nullable=False),
        sa.Column("finding_label", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("finding_reasoning", sa.Text()),
        sa.Column("finding_evidence", sa.JSON()),
        sa.Column("predicted_score", sa.Float()),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_tasks_patient_id"), "patient_tasks", ["patient_id"])
    op.create_index(op.f("ix_patient_tasks_pipeline_run_id"), "patient_tasks", ["pipeline_run_id"])
    op.create_index("ix_patient_tasks_run_status", "patient_tasks", ["pipeline_run_id", "status"])
    op.create_table(
        "production_states",
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("active_run_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["active_run_id"], ["production_runs.id"]),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("active_run_id"),
    )
    op.create_table(
        "Annotations",
        sa.Column("annotation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("text_date", sa.Date(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("token", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column("isNegated", sa.Boolean(), nullable=False),
        sa.Column("note_start_index", sa.Integer(), nullable=False),
        sa.Column("note_end_index", sa.Integer(), nullable=False),
        sa.Column("sentence_number", sa.Integer(), nullable=False),
        sa.Column("sentence_start", sa.Integer(), nullable=False),
        sa.Column("sentence_end", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=1), server_default="U", nullable=False),
        sa.Column("patient_uuid", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("note_uuid", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("review_reason", sqlmodel.sql.sqltypes.AutoString(length=80)),
        sa.Column("reviewed_by", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_type", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("actor_type", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("prediction_id", sa.Integer()),
        sa.Column("duplicate_of", sa.Integer()),
        sa.Column("skipped_by_event_annotation_id", sa.Integer()),
        sa.Column("pipeline_run_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("production_run_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("patient_task_id", sa.Integer()),
        sa.Column("reviewer_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('U', 'R', 'S')", name="ck_annotations_status"),
        sa.ForeignKeyConstraint(["duplicate_of"], ["Annotations.annotation_id"]),
        sa.ForeignKeyConstraint(["note_uuid"], ["notes.id"]),
        sa.ForeignKeyConstraint(["patient_task_id"], ["patient_tasks.id"]),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["production_runs.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "patient_id"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_annotations_patient_external",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "text_id", "patient_id"],
            ["notes.project_id", "notes.text_id", "notes.patient_id_ext"],
            name="fk_annotations_note_patient_external",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["ProjectUsers.global_user_id"]),
        sa.ForeignKeyConstraint(["skipped_by_event_annotation_id"], ["Annotations.annotation_id"]),
        sa.PrimaryKeyConstraint("annotation_id"),
        sa.UniqueConstraint(
            "project_id", "patient_id", "annotation_id", name="uq_annotations_project_patient_id"
        ),
    )
    op.create_index(op.f("ix_Annotations_note_uuid"), "Annotations", ["note_uuid"])
    op.create_index(op.f("ix_Annotations_patient_uuid"), "Annotations", ["patient_uuid"])
    op.create_index(op.f("ix_Annotations_pipeline_run_id"), "Annotations", ["pipeline_run_id"])
    op.create_index(op.f("ix_Annotations_project_id"), "Annotations", ["project_id"])
    op.create_index(
        "ix_annotations_project_patient_status_date",
        "Annotations",
        ["project_id", "patient_id", "status", "text_date"],
    )
    op.create_index(
        "ix_annotations_project_patient_text",
        "Annotations",
        ["project_id", "patient_id", "text_id"],
    )
    op.create_index(
        "ix_annotations_project_text_negated_sentence",
        "Annotations",
        ["project_id", "text_id", "isNegated", "sentence_number", "note_start_index"],
    )
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("patients") as batch_op:
            batch_op.create_foreign_key(
                "fk_patient_event_annotation_same_patient",
                "Annotations",
                ["project_id", "patient_id_ext", "event_annotation_id"],
                ["project_id", "patient_id", "annotation_id"],
            )
    else:
        op.create_foreign_key(
            "fk_patient_event_annotation_same_patient",
            "patients",
            "Annotations",
            ["project_id", "patient_id_ext", "event_annotation_id"],
            ["project_id", "patient_id", "annotation_id"],
        )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patient_task_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_pos", sa.Integer(), nullable=False),
        sa.Column("end_pos", sa.Integer(), nullable=False),
        sa.Column("match_source", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("match_pattern", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.ForeignKeyConstraint(["patient_task_id"], ["patient_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_note_id"), "evidence", ["note_id"])
    op.create_index(op.f("ix_evidence_patient_task_id"), "evidence", ["patient_task_id"])
    op.create_table(
        "note_predictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("note_uuid", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("patient_uuid", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("label", sa.Integer()),
        sa.Column("score", sa.Float()),
        sa.Column("reasoning", sa.Text()),
        sa.Column("evidence_spans", sa.JSON()),
        sa.Column("model_fingerprint", sqlmodel.sql.sqltypes.AutoString(length=128)),
        sa.Column("config_fingerprint", sqlmodel.sql.sqltypes.AutoString(length=128)),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_note_predictions_status",
        ),
        sa.CheckConstraint("label IS NULL OR label IN (0, 1)", name="ck_note_predictions_label"),
        sa.ForeignKeyConstraint(["note_uuid"], ["notes.id"]),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "text_id", "patient_id"],
            ["notes.project_id", "notes.text_id", "notes.patient_id_ext"],
            name="fk_note_predictions_note_patient_external",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "text_id", name="uq_note_prediction_project_text"),
    )
    op.create_index(op.f("ix_note_predictions_note_uuid"), "note_predictions", ["note_uuid"])
    op.create_index(op.f("ix_note_predictions_patient_uuid"), "note_predictions", ["patient_uuid"])
    op.create_index(op.f("ix_note_predictions_project_id"), "note_predictions", ["project_id"])
    op.create_index(op.f("ix_note_predictions_run_id"), "note_predictions", ["run_id"])
    op.create_index("ix_note_predictions_run_status", "note_predictions", ["run_id", "status"])
    op.create_table(
        "search_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("query_index", sa.Integer(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("matched_tokens", sa.JSON()),
        sa.Column("match_positions", sa.JSON()),
        sa.Column("is_negated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["evaluation_sessions_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_search_matches_note_id"), "search_matches", ["note_id"])
    op.create_index(op.f("ix_search_matches_patient_id"), "search_matches", ["patient_id"])
    op.create_index(op.f("ix_search_matches_session_id"), "search_matches", ["session_id"])
    op.create_index(
        "ix_search_matches_session_patient", "search_matches", ["session_id", "patient_id"]
    )
    op.create_index(
        "ix_search_matches_session_query", "search_matches", ["session_id", "query_index"]
    )
    op.create_table(
        "sentences",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sentence_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_pos", sa.Integer(), nullable=False),
        sa.Column("end_pos", sa.Integer(), nullable=False),
        sa.Column("is_negated", sa.Boolean(), nullable=False),
        sa.Column("is_target", sa.Boolean(), nullable=False),
        sa.Column("matched_tokens", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "sentence_number", name="uq_sentence_note_pos"),
    )
    op.create_index(op.f("ix_sentences_note_id"), "sentences", ["note_id"])
    op.create_index(op.f("ix_sentences_project_id"), "sentences", ["project_id"])
    op.create_index(
        "ix_sentences_project_target_created",
        "sentences",
        ["project_id", "is_target", "created_at"],
    )
    op.create_index(
        "ix_sentences_project_target_negated",
        "sentences",
        ["project_id", "is_target", "is_negated"],
    )
    op.create_table(
        "RESULTS",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_uuid", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("processing_status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("review_status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("review_type", sqlmodel.sql.sqltypes.AutoString(length=20)),
        sa.Column("notes_total", sa.Integer(), nullable=False),
        sa.Column("notes_processed", sa.Integer(), nullable=False),
        sa.Column("notes_failed", sa.Integer(), nullable=False),
        sa.Column("annotations_total", sa.Integer(), nullable=False),
        sa.Column("annotations_pending", sa.Integer(), nullable=False),
        sa.Column("annotations_reviewed", sa.Integer(), nullable=False),
        sa.Column("annotations_skipped", sa.Integer(), nullable=False),
        sa.Column("reason_counts", sa.JSON(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Text()),
        sa.Column("event_information", sa.JSON()),
        sa.Column("index_no", sa.Integer()),
        sa.Column("first_note_date", sa.DateTime(timezone=True)),
        sa.Column("last_note_date", sa.DateTime(timezone=True)),
        sa.Column("max_score", sa.Float()),
        sa.Column("max_score_note_date", sa.DateTime(timezone=True)),
        sa.Column("max_score_note_id", sqlmodel.sql.sqltypes.AutoString(length=100)),
        sa.Column("reviewer", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("reviewed_notes", sa.Integer(), nullable=False),
        sa.Column("reviewed_sentences", sa.Integer(), nullable=False),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("total_sentences", sa.Integer(), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True)),
        sa.Column("event_date", sa.Date()),
        sa.Column("event_annotation_id", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(event_date IS NULL AND event_annotation_id IS NULL) OR (event_date IS NOT NULL AND event_annotation_id IS NOT NULL)",
            name="ck_results_event_all_or_none",
        ),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "patient_id", "event_annotation_id"],
            ["Annotations.project_id", "Annotations.patient_id", "Annotations.annotation_id"],
            name="fk_results_event_annotation_same_patient",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "patient_id"],
            ["patients.project_id", "patients.patient_id_ext"],
            name="fk_results_patient_external",
        ),
        sa.ForeignKeyConstraint(["reviewer"], ["ProjectUsers.global_user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "patient_id", name="uq_results_project_patient_ext"),
        sa.UniqueConstraint("project_id", "patient_uuid", name="uq_results_project_patient_uuid"),
    )
    op.create_index(op.f("ix_RESULTS_patient_uuid"), "RESULTS", ["patient_uuid"])
    op.create_index(op.f("ix_RESULTS_project_id"), "RESULTS", ["project_id"])
    op.create_index("ix_results_project_status", "RESULTS", ["project_id", "processing_status"])
    op.create_table(
        "annotation_predictions",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("annotation_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("predictor_config_id", sqlmodel.sql.sqltypes.AutoString()),
        sa.Column("predictor_model", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("predicted_score", sa.Float()),
        sa.Column("predicted_label", sa.Integer()),
        sa.Column("reasoning", sa.Text(), server_default="", nullable=False),
        sa.Column("token_usage", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["Annotations.annotation_id"]),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "annotation_id", "predictor_config_id", name="uq_annotation_prediction"
        ),
    )
    op.create_index(
        op.f("ix_annotation_predictions_annotation_id"), "annotation_predictions", ["annotation_id"]
    )
    op.create_index(
        op.f("ix_annotation_predictions_predictor_config_id"),
        "annotation_predictions",
        ["predictor_config_id"],
    )
    op.create_index(
        op.f("ix_annotation_predictions_project_id"), "annotation_predictions", ["project_id"]
    )
def downgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        with op.batch_alter_table("patients") as batch_op:
            batch_op.drop_constraint("fk_patient_event_annotation_same_patient", type_="foreignkey")
    else:
        op.drop_constraint(
            "fk_patient_event_annotation_same_patient",
            "patients",
            type_="foreignkey",
        )
    for table_name in (
        "annotation_predictions",
        "RESULTS",
        "sentences",
        "search_matches",
        "note_predictions",
        "evidence",
        "Annotations",
        "production_states",
        "patient_tasks",
        "patient_review_jobs",
        "patient_results",
        "notes",
        "evaluation_session_query_sections",
        "audit_log",
        "search_queries",
        "production_runs",
        "predictor_configs",
        "pipeline_runs",
        "patients",
        "llm_usage",
        "evaluation_sessions_v2",
        "background_jobs",
        "nlp_jobs",
        "event_configs",
        "data_sources",
        "ProjectUsers",
    ):
        op.drop_table(table_name)
