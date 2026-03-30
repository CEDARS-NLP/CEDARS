"""add unified evaluation session tables

Revision ID: 9e2b3d31be5d
Revises: aaf4b96ac757
Create Date: 2026-03-30 11:13:32.921921

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9e2b3d31be5d'
down_revision: Union[str, Sequence[str], None] = 'aaf4b96ac757'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create evaluation_sessions_v2 table
    op.create_table(
        'evaluation_sessions_v2',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='draft'),
        sa.Column('search_queries', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('event_name', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column('event_description', sa.Text(), nullable=True),
        sa.Column('include_criteria', sa.Text(), nullable=True),
        sa.Column('exclude_criteria', sa.Text(), nullable=True),
        sa.Column('llm_provider', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column('llm_model', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column('llm_api_base', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('sample_patient_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('sample_size', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('committed_config', sa.JSON(), nullable=True),
        sa.Column('committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('committed_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('cloned_from_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_by', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['committed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['cloned_from_id'], ['evaluation_sessions_v2.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_evaluation_sessions_v2_project_id'), 'evaluation_sessions_v2', ['project_id'], unique=False)

    # Create search_matches table
    op.create_table(
        'search_matches',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('session_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('query_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('patient_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('note_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('matched_tokens', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('match_positions', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_negated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['evaluation_sessions_v2.id'], ),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_search_matches_session_id'), 'search_matches', ['session_id'], unique=False)
    op.create_index(op.f('ix_search_matches_patient_id'), 'search_matches', ['patient_id'], unique=False)
    op.create_index(op.f('ix_search_matches_note_id'), 'search_matches', ['note_id'], unique=False)
    op.create_index('ix_search_matches_session_query', 'search_matches', ['session_id', 'query_index'], unique=False)
    op.create_index('ix_search_matches_session_patient', 'search_matches', ['session_id', 'patient_id'], unique=False)

    # Create patient_results table
    op.create_table(
        'patient_results',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('session_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('pipeline_run_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('patient_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('notes_searched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes_matched', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('finding_label', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column('finding_reasoning', sa.Text(), nullable=True),
        sa.Column('finding_evidence', sa.JSON(), nullable=True),
        sa.Column('event_date', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=True),
        sa.Column('predicted_score', sa.Float(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('review_judgment', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column('reviewer_date_override', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=True),
        sa.Column('reviewed_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default='queued'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['evaluation_sessions_v2.id'], ),
        sa.ForeignKeyConstraint(['pipeline_run_id'], ['pipeline_runs.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_patient_results_session_id'), 'patient_results', ['session_id'], unique=False)
    op.create_index(op.f('ix_patient_results_pipeline_run_id'), 'patient_results', ['pipeline_run_id'], unique=False)
    op.create_index(op.f('ix_patient_results_patient_id'), 'patient_results', ['patient_id'], unique=False)
    op.create_index('ix_patient_results_session_status', 'patient_results', ['session_id', 'status'], unique=False)
    op.create_index('ix_patient_results_run_status', 'patient_results', ['pipeline_run_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop tables in reverse order (handle foreign key constraints)
    op.drop_index('ix_patient_results_run_status', table_name='patient_results')
    op.drop_index('ix_patient_results_session_status', table_name='patient_results')
    op.drop_index(op.f('ix_patient_results_patient_id'), table_name='patient_results')
    op.drop_index(op.f('ix_patient_results_pipeline_run_id'), table_name='patient_results')
    op.drop_index(op.f('ix_patient_results_session_id'), table_name='patient_results')
    op.drop_table('patient_results')

    op.drop_index('ix_search_matches_session_patient', table_name='search_matches')
    op.drop_index('ix_search_matches_session_query', table_name='search_matches')
    op.drop_index(op.f('ix_search_matches_note_id'), table_name='search_matches')
    op.drop_index(op.f('ix_search_matches_patient_id'), table_name='search_matches')
    op.drop_index(op.f('ix_search_matches_session_id'), table_name='search_matches')
    op.drop_table('search_matches')

    op.drop_index(op.f('ix_evaluation_sessions_v2_project_id'), table_name='evaluation_sessions_v2')
    op.drop_table('evaluation_sessions_v2')
