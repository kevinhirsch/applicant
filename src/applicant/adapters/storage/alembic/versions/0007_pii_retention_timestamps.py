"""add created_at to attributes + onboarding_profiles (#363 PII retention).

A configurable PII retention policy (PII_RETENTION_DAYS) prunes parsed PII / EEO
answers (attributes) and the onboarding intake (identity/EEO/history) older than the
window. That requires knowing WHEN each record was recorded, so this adds a
``created_at`` timestamp to both PII-bearing tables. Additive and backfilled to now()
so existing rows start their retention clock at the upgrade (never retroactively
pruned by an upgrade).

Revision ID: 0007_pii_retention_timestamps
Revises: 0006_material_provenance
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_pii_retention_timestamps"
down_revision = "0006_material_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = sa.text("CURRENT_TIMESTAMP")
    op.add_column(
        "attributes",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=now,
        ),
    )
    op.add_column(
        "onboarding_profiles",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=now,
        ),
    )


def downgrade() -> None:
    op.drop_column("onboarding_profiles", "created_at")
    op.drop_column("attributes", "created_at")
