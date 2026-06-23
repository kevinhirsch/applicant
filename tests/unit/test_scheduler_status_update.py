"""Scheduler-driven proactive periodic agent status update (FR-AGENT-7 / FR-OBS-2).

These prove, hermetically (injected clock, no real sleeps), that:

* the scheduler pushes the status update EXACTLY once per campaign per UTC day,
  gated on the automated-work gate, and is a fast no-op when disabled / gated;
* re-ticking the same day does NOT re-push (per-day idempotency), and a new UTC day
  pushes again;
* the pushed message reflects REAL recent-activity / next-action state and omits
  unknown fields (no fabrication, FR-AGENT-5);
* the update flows through the EXISTING notification path (in-app inbox + opt-in
  fan-out), so its channel reach follows the user's opt-ins — not a forced channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.application.services.status_update import StatusUpdateService
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _Gate:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def is_automated_work_allowed(self) -> bool:
        return self.allowed


class _Runs:
    """Read-only agent-run status stub (mirrors AgentRunService.status keys)."""

    def __init__(self, status: dict):
        self._status = status

    def status(self, campaign_id, **_):
        return dict(self._status)


class _Pending:
    def __init__(self, n: int):
        self._items = [object() for _ in range(n)]

    def list_pending(self, campaign_id):
        return list(self._items)


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


def _service(notifier, *, runs=None, pending=None, admin=None):
    return StatusUpdateService(
        notification_service=notifier,
        agent_run_service=runs,
        admin_query=admin,
        pending_actions=pending,
    )


def _notifier():
    # The DEFAULT (offline) AppriseNotifier records deliveries + the in-app inbox in
    # memory — no network. NotificationService wraps it, exactly like production.
    return NotificationService(AppriseNotifier())


_RUN_STATUS = {
    "campaign_id": "c1",
    "paused": False,
    "applied_today": 3,
    "daily_budget": 15,
    "latest_intent": "Pre-fill the Acme Workday application and stop at the final review.",
}


@pytest.mark.unit
def test_status_update_pushes_once_per_day_and_is_idempotent_on_retick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    notifier = _notifier()
    svc = _service(notifier, runs=_Runs(_RUN_STATUS), pending=_Pending(2))
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        notification_service=notifier,
        setup_service=_Gate(allowed=True),
        status_update_service=svc,
        status_update_schedule="daily",
    )
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    assert out1["status_updates"] == [str(cid)]
    inbox = notifier.list_inbox()
    assert len(inbox) == 1

    # Re-tick the SAME day -> no second push (per-day idempotency).
    out2 = sched.tick(now + timedelta(minutes=5))
    assert out2["status_updates"] == []
    assert len(notifier.list_inbox()) == 1

    # A NEW UTC day pushes again.
    out3 = sched.tick(now + timedelta(days=1))
    assert out3["status_updates"] == [str(cid)]
    assert len(notifier.list_inbox()) == 2


@pytest.mark.unit
def test_status_update_noop_when_disabled():
    storage = InMemoryStorage()
    _campaign(storage)
    notifier = _notifier()
    svc = _service(notifier, runs=_Runs(_RUN_STATUS), pending=_Pending(1))
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        notification_service=notifier,
        setup_service=_Gate(allowed=True),
        status_update_service=svc,
        status_update_schedule="off",  # default: dormant
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["status_updates"] == []
    assert notifier.list_inbox() == []


@pytest.mark.unit
def test_status_update_noop_when_gate_closed():
    storage = InMemoryStorage()
    _campaign(storage)
    notifier = _notifier()
    svc = _service(notifier, runs=_Runs(_RUN_STATUS), pending=_Pending(1))
    sched = Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        notification_service=notifier,
        setup_service=_Gate(allowed=False),  # onboarding/LLM not satisfied
        status_update_service=svc,
        status_update_schedule="daily",
    )
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["status_updates"] == []
    assert notifier.list_inbox() == []


@pytest.mark.unit
def test_message_reflects_real_state_and_omits_unknown_fields():
    """Truthful (FR-AGENT-5): present fields appear; absent sources contribute nothing."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    svc = _service(
        _notifier(),
        runs=_Runs(_RUN_STATUS),
        pending=_Pending(2),
    )
    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    msg = svc.build_message(cid, now)
    assert msg is not None
    # Real applied count + budget (the truthful numbers).
    assert "started 3 applications" in msg
    assert "budget of 15" in msg
    # The FR-AGENT-7 next-action intent, decapitalized after "Next I'll".
    assert "pre-fill the Acme Workday application" in msg
    # Pending count from the real pending source.
    assert "2 items waiting" in msg
    # No admin_query wired -> no invented role history.
    assert "worked on" not in msg
    # First-person beats, white-label (no codenames / FR jargon).
    assert msg.startswith("Since yesterday I ")
    assert "FR-" not in msg
    assert "hermes" not in msg.lower()


@pytest.mark.unit
def test_message_is_none_when_nothing_to_report():
    """No meaningful state -> emit nothing (the scheduler pushes nothing)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    empty_status = {"paused": False, "applied_today": 0, "latest_intent": ""}
    svc = _service(_notifier(), runs=_Runs(empty_status), pending=_Pending(0))
    assert svc.build_message(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC)) is None
    # And emit() returns None (nothing pushed).
    assert svc.emit(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC)) is None


@pytest.mark.unit
def test_fanout_respects_optin_inapp_always_present():
    """The update flows through the existing notifier: it always lands in the in-app
    inbox, and external fan-out only happens for opted-in channels (none here)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    # A notifier with NO Discord/email channels configured (no opt-in).
    notifier = NotificationService(AppriseNotifier())
    svc = _service(notifier, runs=_Runs(_RUN_STATUS), pending=_Pending(1))
    handle = svc.emit(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert handle is not None
    # In-app inbox got it (the always-present home-base channel).
    inbox = notifier.list_inbox()
    assert len(inbox) == 1
    # With no Discord/email channels opted in, the ONLY dispatch is the in-app one —
    # fan-out reaches exactly the opted-in channels (here: none beyond in-app), never a
    # forced external send.
    fired_channels = {c.channel for c in notifier._notification._captured}
    assert fired_channels == {"in_app"}
