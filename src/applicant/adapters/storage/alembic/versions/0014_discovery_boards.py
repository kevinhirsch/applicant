"""discovery_boards table for runtime add/remove keyless ATS boards.

Adds the persisted store backing the user-added Greenhouse board token / Lever
company slug runtime registry. The table is keyed by ``source_key``
(``greenhouse:{token}`` / ``lever:{company}``) which is the dedup identity used
by the discovery aggregator and the service add/remove flow.

Revision ID: 0014_discovery_boards
Revises: 0013_job_postings_freshness
Create Date: 2026-08-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_discovery_boards"
down_revision = "0013_job_postings_freshness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_boards",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", name="uq_discovery_boards_source_key"),
    )
    op.create_index(
        op.f("ix_discovery_boards_campaign_id"),
        "discovery_boards",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_discovery_boards_campaign_id"), table_name="discovery_boards")
    op.drop_table("discovery_boards")
