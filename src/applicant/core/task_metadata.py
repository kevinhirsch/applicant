"""Pure task-metadata derivation for pending actions (#295 — Tasks integration).

Every pending action is a first-class *task*. This module turns a stored
``PendingAction`` into the extra, **derived** task fields the surfaces need — none
of which require a schema change: time-in-state (aging), an urgency flag, a coarse
priority, and the snooze state. Pure (no IO, no clock except the ``now`` passed
in) so it is trivially testable and reused identically by every caller.

The fields:

* ``age_seconds`` / ``age_label`` — how long the item has been waiting (FR aging).
* ``urgency`` — ``"normal"`` | ``"due_soon"`` | ``"overdue"``: derived from the
  item's age against a per-kind soft-SLA, OR from an explicit ``due_at`` the engine
  set on the payload (e.g. an application closing soon). Snoozed items report
  ``"snoozed"`` until they come due.
* ``priority`` — a small integer (higher = more urgent) the UI can sort on, so the
  most pressing tasks float to the top regardless of kind.
* ``snoozed`` / ``snoozed_until`` — reflects a "remind me later" reschedule.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Per-kind soft SLA (hours) after which an open task is "due soon", and a second,
# longer bound after which it is "overdue". A final-submit approval or a held
# emergency hand-off ages fastest; an informational confirm the slowest. Unknown
# kinds fall back to the default.
_SLA_HOURS: dict[str, tuple[float, float]] = {
    "final_approval": (12.0, 48.0),
    "request_final_approval": (12.0, 48.0),
    "request-final-approval": (12.0, 48.0),
    "emergency_handoff": (2.0, 12.0),
    "account_human_step": (6.0, 24.0),
    "account_creation": (6.0, 24.0),
    "two_factor": (1.0, 6.0),
    "missing_attr": (24.0, 96.0),
    "missing_attribute": (24.0, 96.0),
    "agent_question": (24.0, 96.0),
    "digest_approval": (24.0, 72.0),
    "material_review": (24.0, 72.0),
    "integral_change": (72.0, 168.0),
    "error": (12.0, 48.0),
}
_DEFAULT_SLA_HOURS: tuple[float, float] = (24.0, 96.0)

# Priority floor per urgency band, so urgency always dominates ordering; the kind's
# inherent weight is a tie-break within a band.
_URGENCY_PRIORITY: dict[str, int] = {
    "overdue": 300,
    "due_soon": 200,
    "normal": 100,
    "snoozed": 0,
}

# Inherent per-kind weight (0–99) layered on top of the urgency floor.
_KIND_WEIGHT: dict[str, int] = {
    "final_approval": 60,
    "request_final_approval": 60,
    "request-final-approval": 60,
    "emergency_handoff": 90,
    "two_factor": 80,
    "account_human_step": 50,
    "account_creation": 50,
    "missing_attr": 40,
    "missing_attribute": 40,
    "agent_question": 30,
    "digest_approval": 20,
    "material_review": 35,
    "integral_change": 25,
    "error": 55,
}


def _coerce_dt(value) -> datetime | None:
    """Best-effort parse of a stored datetime/ISO string into a naive-comparable dt."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _delta_seconds(a: datetime, b: datetime) -> float:
    """``(a - b)`` in seconds, tolerant of one side being tz-aware and one naive."""
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=None)
        b = b.replace(tzinfo=None)
    return (a - b).total_seconds()


def humanize_age(seconds: float) -> str:
    """Plain-language age label (e.g. ``"3h ago"``). White-label, no jargon."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"


def is_snoozed(payload: dict | None, now: datetime) -> bool:
    """True when the item carries a future ``snoozed_until``."""
    until = _coerce_dt((payload or {}).get("snoozed_until"))
    if until is None:
        return False
    return _delta_seconds(until, now) > 0


def derive(
    *,
    kind: str,
    created_at: datetime,
    payload: dict | None,
    now: datetime,
) -> dict:
    """Derive the task-metadata block for one pending action (pure).

    ``now`` is injected so the result is deterministic in tests. Returns a flat
    dict the router can merge straight onto the item.
    """
    payload = payload or {}
    age_seconds = max(0.0, _delta_seconds(now, created_at))

    snoozed = is_snoozed(payload, now)
    snoozed_until = payload.get("snoozed_until") if snoozed else None

    # An explicit deadline the engine attached (e.g. posting closes) wins for
    # urgency; otherwise age-vs-soft-SLA decides.
    due_at = _coerce_dt(payload.get("due_at"))
    due_soon_h, overdue_h = _SLA_HOURS.get(kind, _DEFAULT_SLA_HOURS)

    if snoozed:
        urgency = "snoozed"
    elif due_at is not None:
        remaining = _delta_seconds(due_at, now)
        if remaining <= 0:
            urgency = "overdue"
        elif remaining <= timedelta(hours=24).total_seconds():
            urgency = "due_soon"
        else:
            urgency = "normal"
    else:
        age_hours = age_seconds / 3600.0
        if age_hours >= overdue_h:
            urgency = "overdue"
        elif age_hours >= due_soon_h:
            urgency = "due_soon"
        else:
            urgency = "normal"

    priority = _URGENCY_PRIORITY.get(urgency, 100) + _KIND_WEIGHT.get(kind, 10)

    return {
        "age_seconds": int(age_seconds),
        "age_label": humanize_age(age_seconds),
        "urgency": urgency,
        "urgent": urgency in ("due_soon", "overdue"),
        "priority": priority,
        "snoozed": snoozed,
        "snoozed_until": snoozed_until,
        "due_at": payload.get("due_at"),
    }
