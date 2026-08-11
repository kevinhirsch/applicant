"""Durable agent-memory tables (curated memory / skills / recall) — #286.

Creates the three tables backing ``MIND_BACKEND=sql`` so the curated-memory trio
persists across an engine restart (the prior durable option, the bridge->companion
callback, was disabled for stalling the read path). Reads are single-query +
indexed, so the tables ship the indexes the adapter's hot paths rely on.

Portable across SQLite (test lane) and Postgres (prod): JSON columns use the
portable ``sa.JSON`` type (JSONB on Postgres via the model's ``with_variant``; the
create_table here uses ``sa.JSON`` which maps to each dialect's native JSON).

Revision ID: 0015_agent_memory
Revises: 0014_discovery_boards
Create Date: 2026-08-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_agent_memory"
down_revision = "0014_discovery_boards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- memory_entries (FR-MIND-1) -----------------------------------------
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_memory_entries_campaign_id"),
        "memory_entries",
        ["campaign_id"],
        unique=False,
    )
    # Single-query snapshot(): (scope, campaign_id, kind).
    op.create_index(
        "ix_memory_entries_scope_campaign_kind",
        "memory_entries",
        ["scope", "campaign_id", "kind"],
        unique=False,
    )

    # --- skills (FR-MIND-2) -------------------------------------------------
    op.create_table(
        "skills",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=True),
        sa.Column("when_to_use", sa.Text(), nullable=True),
        sa.Column("procedure", sa.JSON(), nullable=True),
        sa.Column("pitfalls", sa.JSON(), nullable=True),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=True),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(
        op.f("ix_skills_campaign_id"), "skills", ["campaign_id"], unique=False
    )
    op.create_index(
        "ix_skills_scope_campaign", "skills", ["scope", "campaign_id"], unique=False
    )

    # --- recall_entries (FR-MIND-3) -----------------------------------------
    op.create_table(
        "recall_entries",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_recall_entries_campaign", "recall_entries", ["campaign_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_recall_entries_campaign", table_name="recall_entries")
    op.drop_table("recall_entries")

    op.drop_index("ix_skills_scope_campaign", table_name="skills")
    op.drop_index(op.f("ix_skills_campaign_id"), table_name="skills")
    op.drop_table("skills")

    op.drop_index(
        "ix_memory_entries_scope_campaign_kind", table_name="memory_entries"
    )
    op.drop_index(op.f("ix_memory_entries_campaign_id"), table_name="memory_entries")
    op.drop_table("memory_entries")
