"""add application_screenshots.page_url (FR-LOG-2 per-page archive URL).

Phase 2 logs the page URL alongside each archived per-page screenshot so the
debug/history surface (FR-LOG-3 / FR-OBS-2) can label each shot with its page.

Revision ID: 0002_screenshot_page_url
Revises: 0001_initial
Create Date: 2026-06-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_screenshot_page_url"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_screenshots",
        sa.Column("page_url", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("application_screenshots", "page_url")
