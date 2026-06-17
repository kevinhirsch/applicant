"""hot-path indexes + pending_actions.dedup_key column (S3 scale).

Promotes ``pending_actions.dedup_key`` from inside the JSONB ``payload`` to a real,
indexed column so dedup matching is a direct ``(campaign_id, dedup_key)`` lookup
instead of an O(open) payload scan. Also adds composite indexes for the hot
campaign-scoped lookups (applications-by-status, open pending actions,
field-mapping-by-site, agent-runs-by-time, unscored postings).

Revision ID: 0004_indexes
Revises: 0003_credentials
Create Date: 2026-06-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_indexes"
down_revision = "0003_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- pending_actions.dedup_key: real indexed column + backfill from payload ---
    op.add_column(
        "pending_actions",
        sa.Column("dedup_key", sa.String(length=255), nullable=True),
    )
    # Backfill the new column from the existing JSONB/JSON payload so historical
    # rows keep deduplicating. Use a dialect-portable JSON extraction.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ``payload`` is a portable JSON (not jsonb) column, so the jsonb-only
        # key-exists operator ``?`` is unavailable ("operator does not exist:
        # json ? unknown"). ``->>`` works on json and yields NULL for a missing
        # key, so test that instead — no jsonb cast needed.
        op.execute(
            "UPDATE pending_actions "
            "SET dedup_key = payload->>'dedup_key' "
            "WHERE payload->>'dedup_key' IS NOT NULL"
        )
    else:
        # SQLite (and others with json_extract): pull the same key out of JSON text.
        op.execute(
            "UPDATE pending_actions "
            "SET dedup_key = json_extract(payload, '$.dedup_key') "
            "WHERE json_extract(payload, '$.dedup_key') IS NOT NULL"
        )

    # --- hot-path composite indexes ---
    op.create_index(
        "ix_applications_campaign_status",
        "applications",
        ["campaign_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_pending_actions_campaign_resolved",
        "pending_actions",
        ["campaign_id", "resolved"],
        unique=False,
    )
    op.create_index(
        "ix_pending_actions_campaign_dedup",
        "pending_actions",
        ["campaign_id", "dedup_key"],
        unique=False,
    )
    op.create_index(
        "ix_field_mappings_site_key",
        "field_mappings",
        ["site_key"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_campaign_timestamp",
        "agent_runs",
        ["campaign_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_job_postings_campaign_viability",
        "job_postings",
        ["campaign_id", "viability_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_postings_campaign_viability", table_name="job_postings")
    op.drop_index("ix_agent_runs_campaign_timestamp", table_name="agent_runs")
    op.drop_index("ix_field_mappings_site_key", table_name="field_mappings")
    op.drop_index("ix_pending_actions_campaign_dedup", table_name="pending_actions")
    op.drop_index("ix_pending_actions_campaign_resolved", table_name="pending_actions")
    op.drop_index("ix_applications_campaign_status", table_name="applications")
    op.drop_column("pending_actions", "dedup_key")
