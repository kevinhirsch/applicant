"""add credentials table (FR-VAULT-1/3, FR-CRIT-4, NFR-PRIV-1).

Persists libsodium-SEALED per-site/tenant credential sets so banked credentials
survive restarts (FR-VAULT-3 24/7 unattended). Campaign-scoped (FR-CRIT-4); the
row holds only the sealed ciphertext blobs + metadata — never plaintext.

Revision ID: 0003_credentials
Revises: 0002_screenshot_page_url
Create Date: 2026-06-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_credentials"
down_revision = "0002_screenshot_page_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_key", sa.String(length=255), nullable=False),
        sa.Column("sealed_username", sa.Text(), nullable=False),
        sa.Column("sealed_secret", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.UniqueConstraint("campaign_id", "tenant_key", name="uq_credentials_campaign_tenant"),
    )
    op.create_index(
        op.f("ix_credentials_campaign_id"), "credentials", ["campaign_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_credentials_campaign_id"), table_name="credentials")
    op.drop_table("credentials")
