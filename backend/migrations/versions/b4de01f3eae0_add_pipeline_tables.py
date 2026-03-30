"""add pipeline tables

Revision ID: b4de01f3eae0
Revises: c3a1e7f82d9b
Create Date: 2026-03-05 14:04:20.650086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4de01f3eae0'
down_revision: Union[str, Sequence[str], None] = 'c3a1e7f82d9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline tables: event_configs, pipeline_runs, patient_tasks, evidence."""
    op.create_table(
        'event_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('include_criteria', sa.Text(), nullable=False),
        sa.Column('exclude_criteria', sa.Text(), nullable=False, server_default=''),
        sa.Column('search_patterns', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_model', sa.String(length=200), nullable=False),
        sa.Column('llm_api_base', sa.String(length=500), nullable=True),
        sa.Column('confidence_threshold', sa.Float(), nullable=True),
        sa.Column('is_committed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_event_configs_project_id'), 'event_configs', ['project_id'])

    op.create_table(
        'pipeline_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('event_config_id', sa.String(), nullable=False),
        sa.Column('run_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.Enum('queued', 'running', 'completed', 'failed', 'cancelled', name='pipelinerunstatus'), nullable=False),
        sa.Column('config_snapshot', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('snapshot_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('sample_size', sa.Integer(), nullable=True),
        sa.Column('total_patients', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('result_summary', sa.JSON(), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', sa.String(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['event_config_id'], ['event_configs.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pipeline_runs_project_id'), 'pipeline_runs', ['project_id'])
    op.create_index(op.f('ix_pipeline_runs_event_config_id'), 'pipeline_runs', ['event_config_id'])

    op.create_table(
        'patient_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pipeline_run_id', sa.String(), nullable=False),
        sa.Column('patient_id', sa.String(), nullable=False),
        sa.Column('status', sa.Enum('queued', 'processing', 'completed', 'failed', 'no_match', name='patienttaskstatus'), nullable=False),
        sa.Column('notes_searched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes_matched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('finding_label', sa.String(length=20), nullable=True),
        sa.Column('finding_reasoning', sa.Text(), nullable=True),
        sa.Column('finding_evidence', sa.JSON(), nullable=True),
        sa.Column('predicted_score', sa.Float(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_patient_tasks_pipeline_run_id'), 'patient_tasks', ['pipeline_run_id'])
    op.create_index(op.f('ix_patient_tasks_patient_id'), 'patient_tasks', ['patient_id'])
    op.create_index('ix_patient_tasks_run_status', 'patient_tasks', ['pipeline_run_id', 'status'])

    op.create_table(
        'evidence',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('patient_task_id', sa.Integer(), nullable=False),
        sa.Column('note_id', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('start_pos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('end_pos', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('match_source', sa.String(length=20), nullable=False),
        sa.Column('match_pattern', sa.String(length=500), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id']),
        sa.ForeignKeyConstraint(['patient_task_id'], ['patient_tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_evidence_patient_task_id'), 'evidence', ['patient_task_id'])
    op.create_index(op.f('ix_evidence_note_id'), 'evidence', ['note_id'])


def downgrade() -> None:
    """Drop pipeline tables."""
    op.drop_table('evidence')
    op.drop_table('patient_tasks')
    op.drop_table('pipeline_runs')
    op.drop_table('event_configs')
