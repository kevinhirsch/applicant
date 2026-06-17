"""Pure calendar-intelligence analyzers (Phase 3). No app deps."""

import importlib.util as _u
from datetime import datetime

# Load the module directly so importing the `services` package (which pulls
# httpx via services.search) isn't required to run these pure tests.
_spec = _u.spec_from_file_location(
    "calendar_intel",
    __file__.rsplit("/tests/", 1)[0] + "/services/awareness/calendar_intel.py",
)
ci = _u.module_from_spec(_spec)
_spec.loader.exec_module(ci)

NOW = datetime(2026, 6, 2, 9, 0, 0)


def ev(title, start):
    return {"title": title, "start": start}


def test_minutes_until_next_picks_soonest_future():
    events = [
        ev("later", "2026-06-02T11:00:00"),
        ev("soon", "2026-06-02T09:25:00"),
        ev("past", "2026-06-02T08:00:00"),
    ]
    mins, title = ci.minutes_until_next(events, NOW)
    assert mins == 25 and title == "soon"


def test_minutes_until_next_none_when_no_future():
    assert ci.minutes_until_next([ev("past", "2026-06-02T08:00:00")], NOW) == (None, None)
    assert ci.minutes_until_next([], NOW) == (None, None)


def test_parse_handles_tz_aware_and_z():
    # tz-aware inputs shouldn't crash the comparison
    mins, _ = ci.minutes_until_next([ev("z", "2026-06-02T09:30:00Z")], NOW)
    assert isinstance(mins, int)


def test_count_within_and_today():
    events = [
        ev("a", "2026-06-02T10:00:00"),   # +1h, today
        ev("b", "2026-06-02T23:00:00"),   # +14h, today
        ev("c", "2026-06-03T08:00:00"),   # tomorrow
    ]
    assert ci.count_within(events, NOW, 24) == 3
    assert ci.count_within(events, NOW, 2) == 1
    assert ci.count_today(events, NOW) == 2


def test_infer_wake_hour():
    assert ci.infer_wake_hour(["2026-06-02T09:00:00", "2026-06-02T07:30:00"]) == 7
    assert ci.infer_wake_hour([]) is None


def test_build_snapshot_shape():
    events = [ev("standup", "2026-06-02T09:15:00"), ev("lunch", "2026-06-02T12:00:00")]
    snap = ci.build_snapshot(events, NOW)
    assert snap["next_event_minutes"] == 15
    assert snap["next_event_title"] == "standup"
    assert snap["events_today"] == 2
    assert snap["events_next_24h"] == 2


def test_build_snapshot_no_upcoming_omits_next_fields():
    snap = ci.build_snapshot([ev("past", "2026-06-02T08:00:00")], NOW)
    assert "next_event_minutes" not in snap
    assert snap["events_today"] == 0
