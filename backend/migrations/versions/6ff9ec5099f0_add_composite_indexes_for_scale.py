"""add composite indexes for scale

Revision ID: 6ff9ec5099f0
Revises: cd56927de56d
Create Date: 2026-03-04 07:00:35.413378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6ff9ec5099f0'
down_revision: Union[str, Sequence[str], None] = 'cd56927de56d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes for 10M-note scale.

    Tier 1 (critical): annotation stats, next-unreviewed, patient review,
    note listing, event-date cascades.
    Tier 2 (high priority): bulk prediction anti-join, NLP stats.
    """
    # Tier 1
    op.create_index(
        "ix_annotations_project_review_created",
        "annotations",
        ["project_id", "review_status", "created_at"],
    )
    op.create_index(
        "ix_annotations_project_patient_review",
        "annotations",
        ["project_id", "patient_id", "review_status"],
    )
    op.create_index(
        "ix_notes_project_patient_deleted",
        "notes",
        ["project_id", "patient_id", "deleted_at"],
    )
    op.create_index(
        "ix_sentences_project_target_created",
        "sentences",
        ["project_id", "is_target", "created_at"],
    )
    op.create_index(
        "ix_notes_patient_notedate",
        "notes",
        ["patient_id", "note_date"],
    )
    # Tier 2
    op.create_index(
        "ix_annotations_sentence_project",
        "annotations",
        ["sentence_id", "project_id"],
    )
    op.create_index(
        "ix_sentences_project_target_negated",
        "sentences",
        ["project_id", "is_target", "is_negated"],
    )


def downgrade() -> None:
    """Drop composite indexes."""
    op.drop_index("ix_sentences_project_target_negated", table_name="sentences")
    op.drop_index("ix_annotations_sentence_project", table_name="annotations")
    op.drop_index("ix_notes_patient_notedate", table_name="notes")
    op.drop_index("ix_sentences_project_target_created", table_name="sentences")
    op.drop_index("ix_notes_project_patient_deleted", table_name="notes")
    op.drop_index("ix_annotations_project_patient_review", table_name="annotations")
    op.drop_index("ix_annotations_project_review_created", table_name="annotations")
