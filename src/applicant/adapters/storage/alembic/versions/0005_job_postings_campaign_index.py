"""plain index on job_postings(campaign_id) for filter-only queries.

``0004_indexes`` added a *composite* ``(campaign_id, viability_score)`` index, which
serves campaign-scoped score-ordered reads. Filter-only queries that just select a
campaign's postings (no score predicate/order) want a single-column index so the plan
stays cheap as the table grows.

NOTE on naming: the ORM model declares ``job_postings.campaign_id`` with
``index=True``, so ``0001_initial`` already created ``ix_job_postings_campaign_id``.
To deliver an EXPLICIT, owned, cleanly-reversible single-column index without colliding
with that baseline index, this migration creates a distinctly-named index
(``ix_job_postings_campaign_id_filter``). upgrade() guards with a presence check so a
re-run / partially-migrated DB never errors; downgrade() drops only what it created.

Revision ID: 0005_job_postings_campaign_index
Revises: 0004_indexes
Create Date: 2026-06-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_job_postings_campaign_index"
down_revision = "0004_indexes"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_job_postings_campaign_id_filter"
_TABLE = "job_postings"


def _existing_indexes(bind) -> set[str]:
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME not in _existing_indexes(bind):
        op.create_index(_INDEX_NAME, _TABLE, ["campaign_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX_NAME in _existing_indexes(bind):
        op.drop_index(_INDEX_NAME, table_name=_TABLE)
