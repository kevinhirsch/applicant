"""Hermetic tests for AuditLogService's isolated-session write durability.

Targets exhaustive-audit lens 04 finding #47: an audit-log write failure on
the isolated-session (real DB) path was logged but silently dropped — no
retry, no failure counter — so audit entries could vanish under a transient
storage error with no operator-visible signal.

These tests exercise ``AuditLogService._persist_isolated`` directly (the
method the finding cites) with a fake ``session_factory`` and a monkeypatched
``SqlAlchemyStorage`` double, so no real database is needed:

* a write that fails once (a transient blip) is retried and lands on a later
  attempt, with NO drop counted;
* a write that keeps failing for every bounded attempt is still swallowed
  (never raises into the caller — the audit trail must not break the primary
  flow) but increments the process-lived failure counter exactly once and is
  logged, so the drop is observable instead of silently vanishing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import applicant.adapters.storage.repositories as repositories_module
from applicant.application.services.audit_log_service import AuditLogService
from applicant.core.entities.action_event import ActionEvent
from applicant.core.ids import ActionEventId, new_id


def _make_event() -> ActionEvent:
    return ActionEvent(
        id=ActionEventId(new_id()),
        occurred_at=datetime(2026, 7, 5, tzinfo=UTC),
        action="state_changed",
        reason="test transition",
    )


class _FakeSession:
    """Stand-in for a SQLAlchemy ``Session`` — just tracks close()."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_session_factory():
    """Return (factory, sessions) where ``sessions`` records every session opened."""
    sessions: list[_FakeSession] = []

    def factory():
        s = _FakeSession()
        sessions.append(s)
        return s

    return factory, sessions


class _NullActionEvents:
    """No-op ``action_events`` repo stand-in (``.add`` never actually queries)."""

    @staticmethod
    def add(ae):
        pass


def test_transient_write_failure_is_retried_and_succeeds(monkeypatch):
    """A write that fails on its first attempt (transient blip) is retried and
    lands on the second attempt — no permanent drop, nothing counted."""
    attempts = {"n": 0}

    class _FlakyStore:
        def __init__(self, session):
            self._session = session
            self.action_events = _NullActionEvents()

        def commit(self):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("transient storage blip")
            # second attempt succeeds

    monkeypatch.setattr(repositories_module, "SqlAlchemyStorage", _FlakyStore)

    factory, sessions = _make_session_factory()
    svc = AuditLogService(storage=None, session_factory=factory)

    svc._persist_isolated(_make_event())

    assert attempts["n"] == 2, "should retry once after the first transient failure"
    assert svc.write_failure_count == 0, (
        "a write that eventually succeeds must not be counted as permanently dropped"
    )
    assert len(sessions) == 2, "each retry attempt should open its own fresh session"
    assert all(s.closed for s in sessions), "every opened session must be closed"


def test_permanently_failing_write_is_counted_and_swallowed(monkeypatch, caplog):
    """A write that fails on EVERY bounded attempt is still swallowed (never
    raises into the caller) but increments the failure counter exactly once
    and is logged at error level, so the drop is observable."""
    attempts = {"n": 0}

    class _AlwaysFailStore:
        def __init__(self, session):
            self._session = session
            self.action_events = _NullActionEvents()

        def commit(self):
            attempts["n"] += 1
            raise RuntimeError("storage is permanently down")

    monkeypatch.setattr(repositories_module, "SqlAlchemyStorage", _AlwaysFailStore)

    factory, sessions = _make_session_factory()
    svc = AuditLogService(storage=None, session_factory=factory, max_write_attempts=3)

    with caplog.at_level("WARNING"):
        # Must not raise — an audit-trail failure must never break the caller.
        svc._persist_isolated(_make_event())

    assert attempts["n"] == 3, "should attempt exactly max_write_attempts times, then stop"
    assert svc.write_failure_count == 1, (
        "a permanently-failing write must increment the drop counter exactly once"
    )
    assert len(sessions) == 3
    assert all(s.closed for s in sessions), "every opened session must be closed"

    # The drop must be clearly logged (not silent) at error severity.
    error_records = [r for r in caplog.records if r.levelno >= 40]
    assert any("dropped" in r.getMessage().lower() for r in error_records), (
        "a permanently-dropped audit event must be logged at error level"
    )


def test_failure_counter_accumulates_across_multiple_dropped_events(monkeypatch):
    """The failure counter is process-lived across the service instance's
    lifetime — a second permanently-failing event bumps it to 2, not reset."""

    class _AlwaysFailStore:
        def __init__(self, session):
            self._session = session
            self.action_events = _NullActionEvents()

        def commit(self):
            raise RuntimeError("still down")

    monkeypatch.setattr(repositories_module, "SqlAlchemyStorage", _AlwaysFailStore)

    factory, _sessions = _make_session_factory()
    svc = AuditLogService(storage=None, session_factory=factory, max_write_attempts=2)

    svc._persist_isolated(_make_event())
    assert svc.write_failure_count == 1

    svc._persist_isolated(_make_event())
    assert svc.write_failure_count == 2
