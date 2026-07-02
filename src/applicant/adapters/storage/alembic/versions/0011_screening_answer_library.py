"""Add screening_answer_library table (product-gaps backlog #20, FR-ANSWER-1).

Reusable, campaign-scoped library of screening-question answers, keyed by the
normalized question text, so a previously-generated answer to a common question
("Why do you want to work here?") can be reused/edited for a new application
instead of being regenerated fresh every time. Mirrors ``discovery_sources``'
(campaign_id, key) shape.

Revision ID: 0011_screening_answer_library
Revises: 0010_action_events
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_screening_answer_library"
down_revision = "0010_action_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "screening_answer_library",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("campaign_id", sa.String(64), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("question_key", sa.String(512), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("essay", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint(
            "campaign_id", "question_key", name="uq_screening_answer_library_campaign_key"
        ),
    )
    op.create_index(
        op.f("ix_screening_answer_library_campaign_id"),
        "screening_answer_library",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_screening_answer_library_campaign_id"),
        table_name="screening_answer_library",
    )
    op.drop_table("screening_answer_library")
