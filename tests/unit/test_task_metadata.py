"""Pure task-metadata derivation (#295 — pending actions as a task system).

Tests the pure :mod:`applicant.core.task_metadata` helper in isolation: aging,
urgency banding (age-vs-SLA and explicit due_at), priority ordering, and snooze.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from applicant.core import task_metadata as tm


def _now():
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)


def test_age_label_humanizes():
    assert tm.humanize_age(10) == "just now"
    assert tm.humanize_age(120) == "2m ago"
    assert tm.humanize_age(3 * 3600) == "3h ago"
    assert tm.humanize_age(50 * 3600) == "2d ago"


def test_fresh_item_is_normal_priority():
    now = _now()
    meta = tm.derive(kind="agent_question", created_at=now - timedelta(minutes=5), payload={}, now=now)
    assert meta["urgency"] == "normal"
    assert meta["urgent"] is False
    assert meta["age_label"] == "5m ago"


def test_age_crosses_due_soon_then_overdue_band():
    now = _now()
    # digest_approval SLA is (24h due_soon, 72h overdue).
    due_soon = tm.derive(
        kind="digest_approval", created_at=now - timedelta(hours=30), payload={}, now=now
    )
    assert due_soon["urgency"] == "due_soon"
    assert due_soon["urgent"] is True
    overdue = tm.derive(
        kind="digest_approval", created_at=now - timedelta(hours=80), payload={}, now=now
    )
    assert overdue["urgency"] == "overdue"
    assert overdue["priority"] > due_soon["priority"]


def test_explicit_due_at_drives_urgency():
    now = _now()
    closing_soon = tm.derive(
        kind="material_review",
        created_at=now - timedelta(minutes=1),
        payload={"due_at": (now + timedelta(hours=6)).isoformat()},
        now=now,
    )
    assert closing_soon["urgency"] == "due_soon"
    past_due = tm.derive(
        kind="material_review",
        created_at=now,
        payload={"due_at": (now - timedelta(hours=1)).isoformat()},
        now=now,
    )
    assert past_due["urgency"] == "overdue"


def test_snoozed_item_reports_snoozed_and_lowest_priority():
    now = _now()
    meta = tm.derive(
        kind="agent_question",
        created_at=now - timedelta(days=5),
        payload={"snoozed_until": (now + timedelta(hours=12)).isoformat()},
        now=now,
    )
    assert meta["snoozed"] is True
    assert meta["urgency"] == "snoozed"
    # A snoozed item never out-prioritises a live one.
    live = tm.derive(kind="agent_question", created_at=now, payload={}, now=now)
    assert meta["priority"] < live["priority"]


def test_expired_snooze_is_not_snoozed():
    now = _now()
    payload = {"snoozed_until": (now - timedelta(minutes=1)).isoformat()}
    assert tm.is_snoozed(payload, now) is False
    meta = tm.derive(kind="agent_question", created_at=now, payload=payload, now=now)
    assert meta["snoozed"] is False
