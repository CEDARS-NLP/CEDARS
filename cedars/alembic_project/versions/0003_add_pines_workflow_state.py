"""Add fail-closed PINES workflow state and prediction metadata."""
from alembic import op
import sqlalchemy as sa


revision = "0003_add_pines_workflow_state"
down_revision = "0002_seed_system_reviewers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("Patients", sa.Column("pines_query_id", sa.Integer(), nullable=True))
    op.add_column("Patients", sa.Column("pines_status", sa.String(length=20), nullable=True))
    op.add_column("Patients", sa.Column("pines_error", sa.String(length=500), nullable=True))
    op.create_foreign_key(
        "fk_patients_pines_query_id_query",
        "Patients",
        "Query",
        ["pines_query_id"],
        ["query_id"],
    )
    op.create_index(
        "idx_patients_pines_query_status",
        "Patients",
        ["pines_query_id", "pines_status"],
    )

    op.add_column("PINES", sa.Column("predicted_label", sa.String(length=100), nullable=True))
    op.add_column("PINES", sa.Column("model_name", sa.String(length=255), nullable=True))
    op.add_column("PINES", sa.Column("classification_threshold", sa.Float(), nullable=True))
    op.execute('DELETE FROM "PINES"')
    op.alter_column("PINES", "predicted_label", nullable=False)
    op.alter_column("PINES", "model_name", nullable=False)
    op.alter_column("PINES", "classification_threshold", nullable=False)


def downgrade() -> None:
    op.drop_column("PINES", "classification_threshold")
    op.drop_column("PINES", "model_name")
    op.drop_column("PINES", "predicted_label")
    op.drop_index("idx_patients_pines_query_status", table_name="Patients")
    op.drop_constraint("fk_patients_pines_query_id_query", "Patients", type_="foreignkey")
    op.drop_column("Patients", "pines_error")
    op.drop_column("Patients", "pines_status")
    op.drop_column("Patients", "pines_query_id")