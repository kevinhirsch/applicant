"""G16: post-submission lifecycle tables (#190).

Adds the five tables that track what happens after a submission is recorded:
submission_snapshots, rejection_signals, ghosting_signals, follow_ups,
portfolio_attachments.

Revision ID: 0008_g16_post_submission
Revises: 0007_pii_retention_timestamps
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_g16_post_submission"
down_revision = "0007_pii_retention_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "submission_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("materials", sa.JSON(), nullable=True),
        sa.Column("ats_metadata", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_submission_snapshot_application", "submission_snapshots", ["application_id"])

    op.create_table(
        "rejection_signals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("signal_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rejection_signals_application_id", "rejection_signals", ["application_id"])

    op.create_table(
        "ghosting_signals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("sla_days", sa.Integer(), nullable=True),
        sa.Column("submission_age_days", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ghosting_signals_campaign_id", "ghosting_signals", ["campaign_id"])
    op.create_index("ix_ghosting_signals_application_id", "ghosting_signals", ["application_id"])

    op.create_table(
        "follow_ups",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("template", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_follow_ups_campaign_id", "follow_ups", ["campaign_id"])
    op.create_index("ix_follow_ups_application_id", "follow_ups", ["application_id"])
    op.create_index("ix_follow_ups_due", "follow_ups", ["scheduled_at", "status"])

    op.create_table(
        "portfolio_attachments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("application_id", sa.String(64), sa.ForeignKey("applications.id"), nullable=True),
        sa.Column("attachment_type", sa.String(32), nullable=True),
        sa.Column("file_name", sa.String(512), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_portfolio_attachments_campaign_id", "portfolio_attachments", ["campaign_id"])
    op.create_index("ix_portfolio_attachments_application", "portfolio_attachments", ["application_id"])


def downgrade() -> None:
    op.drop_table("portfolio_attachments")
    op.drop_table("follow_ups")
    op.drop_table("ghosting_signals")
    op.drop_table("rejection_signals")
    op.drop_table("submission_snapshots")
