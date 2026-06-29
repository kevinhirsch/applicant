"""schema hardening: drop dead columns, add seq+constraints (#244, #245, #243, #242).

For EXISTING databases created before the 0001_initial fix, this migration:
- Drops dead columns ``job_postings.normalized`` and ``generated_materials.redline_state`` (#245)
- Adds ``agent_runs.seq`` with a backfill so existing rows get seq=0 (#242)
- Adds unique constraints on ``discovery_sources(campaign_id, source_key)`` and
  ``onboarding_profiles(campaign_id)`` (#243)

For FRESH databases (created with the fixed 0001_initial), this migration is a
no-op: columns already absent, seq already present, constraints already in place.

Revision ID: 0008_schema_hardening
Revises: 0007_pii_retention_timestamps
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0008_schema_hardening"
down_revision = "0007_pii_retention_timestamps"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector: Inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns(table)}
    return column in cols


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector: Inspector = sa.inspect(bind)
    for uc in inspector.get_unique_constraints(table):
        if uc.get("name") == name:
            return True
    return False


def upgrade() -> None:
    # --- #245: Drop dead columns (if they exist) ---
    if _column_exists("job_postings", "normalized"):
        op.drop_column("job_postings", "normalized")
    if _column_exists("generated_materials", "redline_state"):
        op.drop_column("generated_materials", "redline_state")

    # --- #242: Add agent_runs.seq (if missing) ---
    if not _column_exists("agent_runs", "seq"):
        op.add_column(
            "agent_runs",
            sa.Column("seq", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        # Backfill existing rows; the server_default already handles new inserts.
        # Existing rows with NULL get 0 via the server_default on add, but for
        # rows already in the table before the column existed they'll be NULL
        # unless the DB backfills. Update any NULLs.
        op.execute("UPDATE agent_runs SET seq = 0 WHERE seq IS NULL")

    # --- #243: Add unique constraints (if missing) ---
    if not _constraint_exists("discovery_sources", "uq_discovery_sources_campaign_source"):
        # Deduplicate first: keep the row with the lowest id for each (campaign_id, source_key).
        op.execute(
            "DELETE FROM discovery_sources WHERE id NOT IN ("
            "  SELECT MIN(id) FROM discovery_sources GROUP BY campaign_id, source_key"
            ")"
        )
        op.create_unique_constraint(
            "uq_discovery_sources_campaign_source",
            "discovery_sources",
            ["campaign_id", "source_key"],
        )
    if not _constraint_exists("onboarding_profiles", "uq_onboarding_profiles_campaign"):
        op.execute(
            "DELETE FROM onboarding_profiles WHERE id NOT IN ("
            "  SELECT MIN(id) FROM onboarding_profiles GROUP BY campaign_id"
            ")"
        )
        op.create_unique_constraint(
            "uq_onboarding_profiles_campaign",
            "onboarding_profiles",
            ["campaign_id"],
        )


def downgrade() -> None:
    # Constraints
    if _constraint_exists("onboarding_profiles", "uq_onboarding_profiles_campaign"):
        op.drop_constraint("uq_onboarding_profiles_campaign", "onboarding_profiles", type_="unique")
    if _constraint_exists("discovery_sources", "uq_discovery_sources_campaign_source"):
        op.drop_constraint("uq_discovery_sources_campaign_source", "discovery_sources", type_="unique")

    # seq column
    if _column_exists("agent_runs", "seq"):
        op.drop_column("agent_runs", "seq")

    # Dead columns (restore them as nullable JSON so the downgrade doesn't lose data)
    if not _column_exists("generated_materials", "redline_state"):
        op.add_column(
            "generated_materials",
            sa.Column("redline_state", sa.JSON(), nullable=True),
        )
    if not _column_exists("job_postings", "normalized"):
        op.add_column(
            "job_postings",
            sa.Column("normalized", sa.JSON(), nullable=True),
        )
