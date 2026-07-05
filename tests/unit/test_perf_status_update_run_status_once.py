"""Regression coverage for performance lens 03 (round 2): ``StatusUpdateService.
build_message`` (``application/services/status_update.py``, FR-AGENT-7/FR-OBS-2)
called ``self._safe_run_status(campaign_id)`` -> ``agent_run_service.status(...)``
independently from ``_past_lines``, ``_present_lines``, and ``_future_lines`` — 3
identical calls to the same underlying status read within a single ``emit()``.

The fix reads ``run_status`` once in ``build_message`` and threads it through the
three beat-builders.

FAIL-BEFORE: on the pre-fix tree (verified by hand — file-copy the pre-fix
``status_update.py`` back in, rerun, see the call-count assertion fail with 3
instead of 1, then restore) this pins the single read AND that the assembled
message text is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.application.services.status_update import StatusUpdateService


class _CountingRunStatus:
    def __init__(self, status: dict):
        self._status = dict(status)
        self.calls = 0

    def status(self, campaign_id, **_):
        self.calls += 1
        return dict(self._status)


class _Pending:
    def __init__(self, n: int):
        self._items = [object() for _ in range(n)]

    def list_pending(self, campaign_id):
        return list(self._items)


@pytest.mark.unit
def test_build_message_reads_run_status_exactly_once():
    runs = _CountingRunStatus(
        {
            "applied_today": 3,
            "daily_budget": 10,
            "paused": False,
            "latest_intent": "Apply to senior backend roles at Series B startups.",
        }
    )
    pending = _Pending(2)
    svc = StatusUpdateService(
        notification_service=object(),  # unused by build_message directly
        agent_run_service=runs,
        pending_actions=pending,
    )

    message = svc.build_message("c-1", datetime(2026, 6, 17, 9, 0, tzinfo=UTC))

    assert runs.calls == 1, "run status must be read exactly once per build_message call"
    assert message is not None
    assert "started 3 applications toward today's budget of 10" in message
    assert "apply to senior backend roles" in message.lower()
    assert "2 items waiting for your review" in message


@pytest.mark.unit
def test_build_message_paused_and_empty_states_unchanged():
    """Behavior parity across the (past, present, future) beats with a single read."""
    runs = _CountingRunStatus({"paused": True})
    svc = StatusUpdateService(agent_run_service=runs)

    message = svc.build_message("c-1", datetime(2026, 6, 17, 9, 0, tzinfo=UTC))

    assert runs.calls == 1
    assert message == "Right now my automated work is paused."


@pytest.mark.unit
def test_build_message_returns_none_when_nothing_to_report():
    svc = StatusUpdateService()
    assert svc.build_message("c-1", datetime(2026, 6, 17, 9, 0, tzinfo=UTC)) is None
