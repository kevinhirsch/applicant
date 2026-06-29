"""add generated_materials.provenance (FR-MIND-5/-11, FR-OBS-2 transparency).

Records WHICH learned items (curated-memory lines, saved-playbook names, a prior
similar application recall) actually shaped a generated draft, so the review UI
can surface a "What I drew on" panel. Advisory-only and additive: defaults to an
empty list so existing rows and substrate-less drafts are unchanged.

Revision ID: 0006_material_provenance
Revises: 0005_job_postings_campaign_index
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_material_provenance"
down_revision = "0005_job_postings_campaign_index"
branch_labels = None
depends_on = None

#: Mirror models.JSONType so the column type matches the ORM exactly (JSONB on
#: Postgres, generic JSON elsewhere).
_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "generated_materials",
        sa.Column(
            "provenance",
            _JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("generated_materials", "provenance")
