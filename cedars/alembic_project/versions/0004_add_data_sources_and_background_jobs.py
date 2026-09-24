"""Add project-local data sources, durable jobs, and v2 workflow lineage.

All tables and columns in this revision live in an individual project's
database. Existing records remain untouched; the nullable lineage/status
columns are populated only for data created after the ARQ cutover.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_add_data_sources_and_background_jobs"
down_revision = "0003_add_pines_workflow_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "DataSources",
        sa.Column("source_id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_data_sources_active", "DataSources", ["deleted_at", "created_at"])

    op.create_table(
        "BackgroundJobs",
        sa.Column("job_id", sa.String(length=36), primary_key=True),
        sa.Column("arq_job_id", sa.String(length=128), unique=True, nullable=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_background_jobs_recent", "BackgroundJobs", ["created_at"])
    op.create_index("idx_background_jobs_status", "BackgroundJobs", ["status", "created_at"])

    op.add_column("Patients", sa.Column("data_source_id", sa.String(length=36), nullable=True))
    op.add_column("Patients", sa.Column("workflow_status", sa.String(length=20), nullable=True))
    op.add_column("Patients", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("Patients", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_patients_data_source_id_data_sources",
        "Patients",
        "DataSources",
        ["data_source_id"],
        ["source_id"],
    )
    op.create_index("idx_patients_workflow_status", "Patients", ["workflow_status"])

    op.add_column("Notes", sa.Column("data_source_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_notes_data_source_id_data_sources",
        "Notes",
        "DataSources",
        ["data_source_id"],
        ["source_id"],
    )
    op.create_index("idx_notes_data_source", "Notes", ["data_source_id"])


def downgrade() -> None:
    op.drop_index("idx_notes_data_source", table_name="Notes")
    op.drop_constraint("fk_notes_data_source_id_data_sources", "Notes", type_="foreignkey")
    op.drop_column("Notes", "data_source_id")

    op.drop_index("idx_patients_workflow_status", table_name="Patients")
    op.drop_constraint("fk_patients_data_source_id_data_sources", "Patients", type_="foreignkey")
    op.drop_column("Patients", "updated_at")
    op.drop_column("Patients", "created_at")
    op.drop_column("Patients", "workflow_status")
    op.drop_column("Patients", "data_source_id")

    op.drop_index("idx_background_jobs_status", table_name="BackgroundJobs")
    op.drop_index("idx_background_jobs_recent", table_name="BackgroundJobs")
    op.drop_table("BackgroundJobs")

    op.drop_index("idx_data_sources_active", table_name="DataSources")
    op.drop_table("DataSources")