"""Freshness columns on job_postings (recency-aware ranking).

Adds two NULLABLE datetime columns so discovery can rank fresh high-fit roles
first (the fix for "I find the right jobs at the wrong time"):

* ``first_seen``  — when Applicant's discovery first saw the posting.
* ``date_posted`` — the board-reported post date (from jobspy), when available.

Both nullable; existing rows backfill to NULL and simply carry no freshness
boost until re-seen. upgrade() guards with a column-presence check so a re-run
never errors; downgrade() drops only what it created.

Revision ID: 0013_job_postings_freshness
Revises: 0012_job_postings_easy_apply
Create Date: 2026-08-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_job_postings_freshness"
down_revision = "0012_job_postings_easy_apply"
branch_labels = None
depends_on = None

_TABLE = "job_postings"


def _existing_columns(bind) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)
    if "first_seen" not in cols:
        op.add_column(_TABLE, sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True))
    if "date_posted" not in cols:
        op.add_column(_TABLE, sa.Column("date_posted", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = _existing_columns(bind)
    if "date_posted" in cols:
        op.drop_column(_TABLE, "date_posted")
    if "first_seen" in cols:
        op.drop_column(_TABLE, "first_seen")
