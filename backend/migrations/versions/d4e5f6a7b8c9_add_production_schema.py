"""Replace legacy annotation storage with the production schema.

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("annotation_predictions")
    op.drop_table("annotations")

    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(sa.Column("patient_id_ext", sa.String(length=100), nullable=True))
    op.execute(
        sa.text(
            "UPDATE notes SET patient_id_ext = "
            "(SELECT patients.patient_id_ext FROM patients WHERE patients.id = notes.patient_id)"
        )
    )
    with op.batch_alter_table("notes") as batch_op:
        batch_op.create_unique_constraint(
            "uq_note_project_text_patient", ["project_id", "text_id", "patient_id_ext"]
        )
        batch_op.create_foreign_key(
            "fk_notes_patient_external",
            "patients",
            ["project_id", "patient_id_ext"],
            ["project_id", "patient_id_ext"],
        )

    op.create_table(
        "production_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("completed_notes", sa.Integer(), nullable=False),
        sa.Column("failed_notes", sa.Integer(), nullable=False),
        sa.Column("progress_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_production_runs_project_id", "production_runs", ["project_id"])
    op.create_index("ix_production_runs_status", "production_runs", ["status"])
    op.create_index(
        "ix_production_runs_project_created", "production_runs", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_production_runs_project_status", "production_runs", ["project_id", "status"]
    )
    op.create_table(
        "production_states",
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("active_run_id", sa.String(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["active_run_id"], ["production_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("active_run_id"),
    )

    op.create_table(
        "Annotations",
        sa.Column("annotation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("text_id", sa.String(length=100), nullable=False),
        sa.Column("patient_id", sa.String(length=100), nullable=False),
        sa.Column("text_date", sa.Date(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("token", sa.String(length=200), nullable=False),
        sa.Column("isNegated", sa.Boolean(), nullable=False),
        sa.Column("note_start_index", sa.Integer(), nullable=False),
        sa.Column("note_end_index", sa.Integer(), nullable=False),
        sa.Column("sentence_number", sa.Integer(), nullable=False),
        sa.Column("sentence_start", sa.Integer(), nullable=False),
        sa.Column("sentence_end", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=1), server_default="U", nullable=False),
        sa.Column("patient_uuid", sa.String(), nullable=True),
        sa.Column("note_uuid", sa.String(), nullable=True),
        sa.Column("review_reason", sa.String(length=80), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=True),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column("duplicate_of", sa.Integer(), nullable=True),
        sa.Column("skipped_by_event_annotation_id", sa.Integer(), nullable=True),
        sa.Column("pipeline_run_id", sa.String(), nullable=True),
        sa.Column("production_run_id", sa.String(), nullable=True),
        sa.Column("patient_task_id", sa.Integer(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('U', 'R', 'S')", name="ck_annotations_status"),
        sa.ForeignKeyConstraint(["duplicate_of"], ["Annotations.annotation_id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["project_id", "patient_id"], ["patients.project_id", "patients.patient_id_ext"], name="fk_annotations_patient_external"),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["note_uuid"], ["notes.id"]),
        sa.ForeignKeyConstraint(["project_id", "text_id", "patient_id"], ["notes.project_id", "notes.text_id", "notes.patient_id_ext"], name="fk_annotations_note_patient_external"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["production_runs.id"]),
        sa.ForeignKeyConstraint(["patient_task_id"], ["patient_tasks.id"]),
        sa.ForeignKeyConstraint(["skipped_by_event_annotation_id"], ["Annotations.annotation_id"]),
        sa.PrimaryKeyConstraint("annotation_id"),
        sa.UniqueConstraint("project_id", "patient_id", "annotation_id", name="uq_annotations_project_patient_id"),
    )
    op.create_index("ix_Annotations_project_id", "Annotations", ["project_id"])
    op.create_index("ix_Annotations_patient_uuid", "Annotations", ["patient_uuid"])
    op.create_index("ix_Annotations_note_uuid", "Annotations", ["note_uuid"])
    op.create_index("ix_Annotations_pipeline_run_id", "Annotations", ["pipeline_run_id"])
    op.create_index("ix_annotations_project_patient_text", "Annotations", ["project_id", "patient_id", "text_id"])
    op.create_index("ix_annotations_project_patient_status_date", "Annotations", ["project_id", "patient_id", "status", "text_date"])
    op.create_index("ix_annotations_project_text_negated_sentence", "Annotations", ["project_id", "text_id", "isNegated", "sentence_number", "note_start_index"])

    op.create_table(
        "note_predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("text_id", sa.String(length=100), nullable=False),
        sa.Column("patient_id", sa.String(length=100), nullable=False),
        sa.Column("note_uuid", sa.String(), nullable=True),
        sa.Column("patient_uuid", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("label", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("evidence_spans", sa.JSON(), nullable=True),
        sa.Column("model_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'processing', 'succeeded', 'failed')", name="ck_note_predictions_status"),
        sa.CheckConstraint("label IS NULL OR label IN (0, 1)", name="ck_note_predictions_label"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["production_runs.id"]),
        sa.ForeignKeyConstraint(["note_uuid"], ["notes.id"]),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["project_id", "text_id", "patient_id"], ["notes.project_id", "notes.text_id", "notes.patient_id_ext"], name="fk_note_predictions_note_patient_external"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "text_id", name="uq_note_prediction_project_text"),
    )
    op.create_index("ix_note_predictions_project_id", "note_predictions", ["project_id"])
    op.create_index("ix_note_predictions_run_id", "note_predictions", ["run_id"])
    op.create_index("ix_note_predictions_note_uuid", "note_predictions", ["note_uuid"])
    op.create_index("ix_note_predictions_patient_uuid", "note_predictions", ["patient_uuid"])
    op.create_index("ix_note_predictions_run_status", "note_predictions", ["run_id", "status"])

    op.create_table(
        "RESULTS",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("patient_uuid", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(length=100), nullable=False),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("notes_total", sa.Integer(), nullable=False),
        sa.Column("notes_processed", sa.Integer(), nullable=False),
        sa.Column("notes_failed", sa.Integer(), nullable=False),
        sa.Column("annotations_total", sa.Integer(), nullable=False),
        sa.Column("annotations_pending", sa.Integer(), nullable=False),
        sa.Column("annotations_reviewed", sa.Integer(), nullable=False),
        sa.Column("annotations_skipped", sa.Integer(), nullable=False),
        sa.Column("reason_counts", sa.JSON(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("event_information", sa.JSON(), nullable=True),
        sa.Column("index_no", sa.Integer(), nullable=True),
        sa.Column("first_note_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_note_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("max_score_note_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_score_note_id", sa.String(length=100), nullable=True),
        sa.Column("reviewer", sa.String(), nullable=True),
        sa.Column("reviewed_notes", sa.Integer(), nullable=False),
        sa.Column("reviewed_sentences", sa.Integer(), nullable=False),
        sa.Column("total_notes", sa.Integer(), nullable=False),
        sa.Column("total_sentences", sa.Integer(), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_annotation_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(event_date IS NULL AND event_annotation_id IS NULL) OR (event_date IS NOT NULL AND event_annotation_id IS NOT NULL)", name="ck_results_event_all_or_none"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["patient_uuid"], ["patients.id"]),
        sa.ForeignKeyConstraint(["reviewer"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id", "patient_id"], ["patients.project_id", "patients.patient_id_ext"], name="fk_results_patient_external"),
        sa.ForeignKeyConstraint(["project_id", "patient_id", "event_annotation_id"], ["Annotations.project_id", "Annotations.patient_id", "Annotations.annotation_id"], name="fk_results_event_annotation_same_patient"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "patient_uuid", name="uq_results_project_patient_uuid"),
        sa.UniqueConstraint("project_id", "patient_id", name="uq_results_project_patient_ext"),
    )
    op.create_index("ix_RESULTS_project_id", "RESULTS", ["project_id"])
    op.create_index("ix_RESULTS_patient_uuid", "RESULTS", ["patient_uuid"])
    op.create_index("ix_results_project_status", "RESULTS", ["project_id", "processing_status"])

    with op.batch_alter_table("patients") as batch_op:
        batch_op.add_column(sa.Column("event_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("event_annotation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("event_reviewer", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "ck_patient_event_all_or_none",
            "(event_date IS NULL AND event_annotation_id IS NULL AND event_reviewer IS NULL) OR "
            "(event_date IS NOT NULL AND event_annotation_id IS NOT NULL AND event_reviewer IS NOT NULL)",
        )
        batch_op.create_foreign_key("fk_patient_event_reviewer", "users", ["event_reviewer"], ["id"])
    with op.batch_alter_table("patients") as batch_op:
        batch_op.create_foreign_key(
            "fk_patient_event_annotation_same_patient",
            "Annotations",
            ["project_id", "patient_id_ext", "event_annotation_id"],
            ["project_id", "patient_id", "annotation_id"],
        )

    op.execute(
        sa.text(
            "UPDATE patients SET status = 'NEW', review_source = NULL, review_reason = NULL, "
            "reviewed_by = NULL, reviewed_at = NULL, locked_by = NULL, locked_at = NULL, "
            "event_date = NULL, event_annotation_id = NULL, event_reviewer = NULL"
        )
    )
    op.execute(
        sa.text(
            'INSERT INTO "RESULTS" (project_id, patient_uuid, patient_id, '
            "processing_status, review_status, notes_total, notes_processed, notes_failed, "
            "annotations_total, annotations_pending, annotations_reviewed, "
            "annotations_skipped, reason_counts, failure_count, reviewed_notes, "
            "reviewed_sentences, total_notes, total_sentences, updated_at) "
            "SELECT project_id, id, patient_id_ext, 'queued', 'pending', 0, 0, 0, 0, 0, 0, 0, "
            "'{}', 0, 0, 0, 0, 0, CURRENT_TIMESTAMP FROM patients WHERE deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_constraint("fk_patient_event_annotation_same_patient", type_="foreignkey")
        batch_op.drop_constraint("fk_patient_event_reviewer", type_="foreignkey")
        batch_op.drop_constraint("ck_patient_event_all_or_none", type_="check")
        batch_op.drop_column("event_reviewer")
        batch_op.drop_column("event_annotation_id")
        batch_op.drop_column("event_date")

    for index in ("ix_results_project_status", "ix_RESULTS_patient_uuid", "ix_RESULTS_project_id"):
        op.drop_index(index, table_name="RESULTS")
    op.drop_table("RESULTS")
    for index in (
        "ix_note_predictions_run_status",
        "ix_note_predictions_patient_uuid",
        "ix_note_predictions_note_uuid",
        "ix_note_predictions_run_id",
        "ix_note_predictions_project_id",
    ):
        op.drop_index(index, table_name="note_predictions")
    op.drop_table("note_predictions")
    for index in (
        "ix_annotations_project_text_negated_sentence",
        "ix_annotations_project_patient_status_date",
        "ix_annotations_project_patient_text",
        "ix_Annotations_pipeline_run_id",
        "ix_Annotations_note_uuid",
        "ix_Annotations_patient_uuid",
        "ix_Annotations_project_id",
    ):
        op.drop_index(index, table_name="Annotations")
    op.drop_table("Annotations")
    op.drop_table("production_states")
    for index in (
        "ix_production_runs_project_status",
        "ix_production_runs_project_created",
        "ix_production_runs_status",
        "ix_production_runs_project_id",
    ):
        op.drop_index(index, table_name="production_runs")
    op.drop_table("production_runs")

    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_constraint("fk_notes_patient_external", type_="foreignkey")
        batch_op.drop_constraint("uq_note_project_text_patient", type_="unique")
        batch_op.drop_column("patient_id_ext")

    op.create_table(
        "annotations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("note_id", sa.String(), nullable=False),
        sa.Column("sentence_id", sa.String(), nullable=False),
        sa.Column("sentence_text", sa.Text(), nullable=False),
        sa.Column("matched_tokens", sa.String(), nullable=False),
        sa.Column("is_negated", sa.Boolean(), nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("predicted_label", sa.Integer(), nullable=True),
        sa.Column("predictor_model", sa.String(), nullable=False),
        sa.Column("reasoning", sa.Text(), server_default="", nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("manual_review_override", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pipeline_run_id", sa.String(), nullable=True),
        sa.Column("patient_task_id", sa.Integer(), nullable=True),
        sa.Column("predicted_reasoning", sa.Text(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=20), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("token", sa.String(), nullable=True),
        sa.Column("note_start_index", sa.Integer(), nullable=True),
        sa.Column("note_end_index", sa.Integer(), nullable=True),
        sa.Column("sentence_number", sa.Integer(), nullable=True),
        sa.Column("sentence_start", sa.Integer(), nullable=True),
        sa.Column("sentence_end", sa.Integer(), nullable=True),
        sa.Column("text_date", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["patient_task_id"], ["patient_tasks.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["sentence_id"], ["sentences.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("note_id", "patient_id", "project_id", "sentence_id", "pipeline_run_id", "patient_task_id"):
        op.create_index(f"ix_annotations_{column}", "annotations", [column])
    op.create_table(
        "annotation_predictions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("annotation_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("predictor_config_id", sa.String(), nullable=True),
        sa.Column("predictor_model", sa.String(), server_default="", nullable=False),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("predicted_label", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), server_default="", nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["predictor_config_id"], ["predictor_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("annotation_id", "predictor_config_id", name="uq_annotation_prediction"),
    )
    for column in ("annotation_id", "project_id", "predictor_config_id"):
        op.create_index(f"ix_annotation_predictions_{column}", "annotation_predictions", [column])
