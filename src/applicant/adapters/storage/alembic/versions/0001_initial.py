"""initial schema — all 19 base tables + derived pending_actions (docs/data-model.md §8).

Written explicitly (autogen-equivalent). Campaign-scoped (FR-CRIT-4); JSON columns
map to JSONB on Postgres via the model-level type variant. DBOS state co-resides in
the same Postgres (FR-DUR-3) and is managed by DBOS itself, not this migration.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'app_config',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_table(
        'campaigns',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('run_mode', sa.String(length=32), nullable=False),
        sa.Column('throughput_target', sa.Integer(), nullable=False),
        sa.Column('exploration_budget', sa.Float(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('criteria', sa.JSON(), nullable=False),
        sa.Column('schedule', sa.JSON(), nullable=False),
        sa.Column('learning_state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'dormant_surface_backlog',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('surface_name', sa.String(length=255), nullable=False),
        sa.Column('requirement_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('wiring_notes', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'fonts',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('install_status', sa.String(length=32), nullable=False),
        sa.Column('environment', sa.String(length=64), nullable=False),
        sa.Column('font_metadata', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'tool_settings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tool_key', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tool_key'),
    )
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('intent_sentence', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
    )
    op.create_index(op.f('ix_agent_runs_campaign_id'), 'agent_runs', ['campaign_id'], unique=False)
    op.create_table(
        'attributes',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('is_integral', sa.Boolean(), nullable=False),
        sa.Column('is_sensitive', sa.Boolean(), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
    )
    op.create_index(op.f('ix_attributes_campaign_id'), 'attributes', ['campaign_id'], unique=False)
    op.create_table(
        'discovery_sources',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('source_key', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('yield_stats', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
    )
    op.create_index(op.f('ix_discovery_sources_campaign_id'), 'discovery_sources', ['campaign_id'], unique=False)
    op.create_table(
        'job_postings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=512), nullable=False),
        sa.Column('company', sa.String(length=512), nullable=False),
        sa.Column('location', sa.String(length=512), nullable=True),
        sa.Column('work_mode', sa.String(length=64), nullable=True),
        sa.Column('salary', sa.String(length=128), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('source_key', sa.String(length=128), nullable=True),
        sa.Column('viability_score', sa.Float(), nullable=True),
        sa.Column('normalized', sa.JSON(), nullable=False),
        sa.Column('rationale', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
    )
    op.create_index(op.f('ix_job_postings_campaign_id'), 'job_postings', ['campaign_id'], unique=False)
    op.create_table(
        'onboarding_profiles',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('completion_flag', sa.Boolean(), nullable=False),
        sa.Column('wizard_state', sa.JSON(), nullable=False),
        sa.Column('intake', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
    )
    op.create_index(op.f('ix_onboarding_profiles_campaign_id'), 'onboarding_profiles', ['campaign_id'], unique=False)
    op.create_table(
        'resume_variants',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('parent_id', sa.String(length=64), nullable=True),
        sa.Column('targeted_jd_signature', sa.Text(), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('fit_scores', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['parent_id'], ['resume_variants.id']),
    )
    op.create_index(op.f('ix_resume_variants_campaign_id'), 'resume_variants', ['campaign_id'], unique=False)
    op.create_table(
        'applications',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('posting_id', sa.String(length=64), nullable=True),
        sa.Column('role_name', sa.String(length=512), nullable=True),
        sa.Column('job_title', sa.String(length=512), nullable=True),
        sa.Column('work_mode', sa.String(length=64), nullable=True),
        sa.Column('root_url', sa.Text(), nullable=True),
        sa.Column('resume_variant_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=64), nullable=False),
        sa.Column('sandbox_session_url', sa.Text(), nullable=True),
        sa.Column('attributes_used', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['posting_id'], ['job_postings.id']),
        sa.ForeignKeyConstraint(['resume_variant_id'], ['resume_variants.id']),
    )
    op.create_index(op.f('ix_applications_campaign_id'), 'applications', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_applications_posting_id'), 'applications', ['posting_id'], unique=False)
    op.create_table(
        'field_mappings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=True),
        sa.Column('attribute_id', sa.String(length=64), nullable=True),
        sa.Column('site_key', sa.String(length=255), nullable=False),
        sa.Column('field_selector', sa.Text(), nullable=False),
        sa.Column('mapping_metadata', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['attribute_id'], ['attributes.id']),
    )
    op.create_index(op.f('ix_field_mappings_campaign_id'), 'field_mappings', ['campaign_id'], unique=False)
    op.create_table(
        'application_screenshots',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('page_ref', sa.Text(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_application_screenshots_application_id'), 'application_screenshots', ['application_id'], unique=False)
    op.create_table(
        'decisions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('feedback_text', sa.Text(), nullable=False),
        sa.Column('criteria_delta', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_decisions_application_id'), 'decisions', ['application_id'], unique=False)
    op.create_table(
        'detection_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('signal_type', sa.String(length=64), nullable=False),
        sa.Column('signal_detail', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_detection_events_application_id'), 'detection_events', ['application_id'], unique=False)
    op.create_table(
        'generated_materials',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=True),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('storage_path', sa.Text(), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('redline_state', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_generated_materials_campaign_id'), 'generated_materials', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_generated_materials_application_id'), 'generated_materials', ['application_id'], unique=False)
    op.create_table(
        'outcome_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_outcome_events_application_id'), 'outcome_events', ['application_id'], unique=False)
    op.create_table(
        'pending_actions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('campaign_id', sa.String(length=64), nullable=False),
        sa.Column('application_id', sa.String(length=64), nullable=True),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('resolved', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id']),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id']),
    )
    op.create_index(op.f('ix_pending_actions_campaign_id'), 'pending_actions', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_pending_actions_application_id'), 'pending_actions', ['application_id'], unique=False)
    op.create_table(
        'revision_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('material_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('redline_state', sa.JSON(), nullable=False),
        sa.Column('turns', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['material_id'], ['generated_materials.id']),
    )
    op.create_index(op.f('ix_revision_sessions_material_id'), 'revision_sessions', ['material_id'], unique=False)


def downgrade() -> None:
    op.drop_table('revision_sessions')
    op.drop_table('pending_actions')
    op.drop_table('outcome_events')
    op.drop_table('generated_materials')
    op.drop_table('detection_events')
    op.drop_table('decisions')
    op.drop_table('application_screenshots')
    op.drop_table('field_mappings')
    op.drop_table('applications')
    op.drop_table('resume_variants')
    op.drop_table('onboarding_profiles')
    op.drop_table('job_postings')
    op.drop_table('discovery_sources')
    op.drop_table('attributes')
    op.drop_table('agent_runs')
    op.drop_table('tool_settings')
    op.drop_table('fonts')
    op.drop_table('dormant_surface_backlog')
    op.drop_table('campaigns')
    op.drop_table('app_config')
