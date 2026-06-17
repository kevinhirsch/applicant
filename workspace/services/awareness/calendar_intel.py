"""Calendar intelligence for the awareness snapshot (Phase 3).

Pure functions over a list of upcoming-event dicts (``{"title": str, "start":
ISO-8601}``, soonest first — the shape returned by
``core.database.get_upcoming_events``). They derive the signal fields that
awareness triggers reference (e.g. ``next_event_minutes``). No IO, so fully
unit-testable; the live wiring (reading the calendar) lives in
``services.awareness.service.collect_signals`` and is best-effort/guarded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _parse(start: str) -> Optional[datetime]:
    """Parse an ISO start into a naive-UTC datetime (tz-aware -> stripped)."""
    if not start:
        return None
    s = start.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def minutes_until_next(events: List[Dict[str, Any]], now: datetime) -> Tuple[Optional[int], Optional[str]]:
    """Whole minutes until the soonest event at/after ``now`` (and its title).

    Returns ``(None, None)`` when there is no upcoming event. Events need not be
    pre-sorted.
    """
    best_dt: Optional[datetime] = None
    best_title: Optional[str] = None
    for e in events:
        dt = _parse(e.get("start", ""))
        if dt is None or dt < now:
            continue
        if best_dt is None or dt < best_dt:
            best_dt = dt
            best_title = e.get("title") or ""
    if best_dt is None:
        return None, None
    return int((best_dt - now).total_seconds() // 60), best_title


def count_within(events: List[Dict[str, Any]], now: datetime, hours: float) -> int:
    """How many events start in the window ``[now, now + hours]``."""
    from datetime import timedelta
    end = now + timedelta(hours=hours)
    n = 0
    for e in events:
        dt = _parse(e.get("start", ""))
        if dt is not None and now <= dt <= end:
            n += 1
    return n


def count_today(events: List[Dict[str, Any]], now: datetime) -> int:
    """Events whose start falls on the same calendar day as ``now`` (>= now)."""
    n = 0
    for e in events:
        dt = _parse(e.get("start", ""))
        if dt is not None and dt >= now and dt.date() == now.date():
            n += 1
    return n


def infer_wake_hour(event_starts: List[str]) -> Optional[int]:
    """Rough wake/active-window start: the earliest hour at which events
    typically begin (min of per-event start hours). ``None`` if no data.

    Used to avoid firing proactive nudges in the middle of the night.
    """
    hours = [dt.hour for dt in (_parse(s) for s in event_starts) if dt is not None]
    return min(hours) if hours else None


def build_snapshot(events: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Assemble the calendar portion of the awareness signal snapshot."""
    snap: Dict[str, Any] = {
        "events_next_24h": count_within(events, now, 24),
        "events_today": count_today(events, now),
    }
    mins, title = minutes_until_next(events, now)
    if mins is not None:
        snap["next_event_minutes"] = mins
        snap["next_event_title"] = title
    return snap
