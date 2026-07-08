"""Easy-Apply channel tag on job_postings (P1-11).

Adds ``job_postings.easy_apply`` — a detection-only boolean set at discovery
time when a posting supports the source board's built-in quick-apply flow
(e.g. LinkedIn Easy Apply). Existing rows backfill to ``false`` via the server
default (nothing was detected for them); the ORM supplies the value for all
new rows, so the server default is purely the backfill vehicle.

upgrade() guards with a column-presence check so a re-run / partially-migrated
DB never errors; downgrade() drops only what it created (mirrors
``0005_job_postings_campaign_index``).

Revision ID: 0012_job_postings_easy_apply
Revises: 0011_screening_answer_library
Create Date: 2026-07-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_job_postings_easy_apply"
down_revision = "0011_screening_answer_library"
branch_labels = None
depends_on = None

_TABLE = "job_postings"
_COLUMN = "easy_apply"


def _existing_columns(bind) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if _COLUMN not in _existing_columns(bind):
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN in _existing_columns(bind):
        op.drop_column(_TABLE, _COLUMN)
