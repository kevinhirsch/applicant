"""Add action_events table for the unified audit log (FR-LOG-4, FR-OBS-2).

Append-only action trail: one row per action the engine takes, in sequence,
with the why. Fields: id, occurred_at, application_id?, campaign_id?, actor,
action, reason (text), context (jsonb).

Revision ID: 0010_action_events
Revises: 0009_g16_post_submission
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_action_events"
down_revision = "0009_g16_post_submission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=True),
        sa.Column("actor", sa.String(16), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
    )
    op.create_index("ix_action_events_campaign_occurred", "action_events", ["campaign_id", "occurred_at"])
    op.create_index("ix_action_events_application", "action_events", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_action_events_application", table_name="action_events")
    op.drop_index("ix_action_events_campaign_occurred", table_name="action_events")
    op.drop_table("action_events")
