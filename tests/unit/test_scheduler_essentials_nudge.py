"""Scheduler-driven proactive "I'm still blocked on essentials" nudge (FR-NOTIF / FR-ONBOARD).

These prove, hermetically (injected clock, no real sleeps), that:

* when apply-essentials are MISSING and the schedule is on, the scheduler pushes the
  nudge EXACTLY once per campaign per UTC day, naming the REAL missing items
  (FR-AGENT-5: from ``apply_readiness().missing``, never fabricated);
* re-ticking the same day does NOT re-push (per-day idempotency); a new UTC day pushes again;
* it is a fast no-op when disabled (schedule off), when the gate is OPEN (nothing missing),
  and when work is blocked for some OTHER reason (no missing essentials reported);
* the nudge flows through the EXISTING notification path (in-app inbox + opt-in fan-out),
  so its reach follows the user's opt-ins — not a forced channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.essentials_nudge import EssentialsNudgeService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.scheduler import Scheduler
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import CampaignId, new_id
from applicant.core.rules.apply_readiness import ApplyReadiness


class _Loop:
    def tick(self, campaign_id, now=None, **_):
        return None


class _Onboarding:
    """Stub apply-readiness reader (mirrors OnboardingService.apply_readiness)."""

    def __init__(self, readiness: ApplyReadiness):
        self._readiness = readiness

    def apply_readiness(self, campaign_id):
        return self._readiness


def _campaign(storage):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C", active=True))
    return cid


def _notifier():
    # The DEFAULT (offline) AppriseNotifier records deliveries + the in-app inbox in
    # memory — no network. NotificationService wraps it, exactly like production.
    return NotificationService(AppriseNotifier())


def _service(notifier, readiness):
    return EssentialsNudgeService(
        notification_service=notifier,
        onboarding_service=_Onboarding(readiness),
    )


_BLOCKED = ApplyReadiness(
    ready=False,
    missing=("target roles", "salary floor"),
    reason="I can't start applying until I know: target roles, salary floor.",
)
_READY = ApplyReadiness(ready=True, missing=(), reason="Ready.")


def _sched(storage, notifier, readiness, *, schedule="daily"):
    return Scheduler(
        storage=storage,
        agent_loop=_Loop(),
        notification_service=notifier,
        # No setup gate wired: the essentials nudge intentionally fires while the
        # automated-work gate is closed (that is the situation it nudges about); it is
        # scoped to the missing-essentials cause by the readiness reader, not the gate.
        essentials_nudge_service=_service(notifier, readiness),
        essentials_nudge_schedule=schedule,
    )


@pytest.mark.unit
def test_nudge_pushes_once_per_day_naming_real_missing_and_idempotent_on_retick():
    storage = InMemoryStorage()
    cid = _campaign(storage)
    notifier = _notifier()
    sched = _sched(storage, notifier, _BLOCKED)

    now = datetime(2026, 6, 16, 9, 0, tzinfo=UTC)
    out1 = sched.tick(now)
    assert out1["essentials_nudges"] == [str(cid)]
    inbox = notifier.list_inbox()
    assert len(inbox) == 1
    # Names the REAL missing essentials, first-person, white-label.
    body = inbox[0].body
    assert "target roles" in body
    assert "salary floor" in body
    assert body.startswith("I'm ready to start applying, but I still need ")
    assert "FR-" not in body
    assert "hermes" not in body.lower()

    # Re-tick the SAME day -> no second push (per-day idempotency).
    out2 = sched.tick(now + timedelta(minutes=5))
    assert out2["essentials_nudges"] == []
    assert len(notifier.list_inbox()) == 1

    # A NEW UTC day pushes again.
    out3 = sched.tick(now + timedelta(days=1))
    assert out3["essentials_nudges"] == [str(cid)]
    assert len(notifier.list_inbox()) == 2


@pytest.mark.unit
def test_nudge_noop_when_disabled():
    storage = InMemoryStorage()
    _campaign(storage)
    notifier = _notifier()
    sched = _sched(storage, notifier, _BLOCKED, schedule="off")  # default: dormant
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["essentials_nudges"] == []
    assert notifier.list_inbox() == []


@pytest.mark.unit
def test_nudge_noop_when_gate_open_nothing_missing():
    storage = InMemoryStorage()
    _campaign(storage)
    notifier = _notifier()
    sched = _sched(storage, notifier, _READY)  # essentials all present
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["essentials_nudges"] == []
    assert notifier.list_inbox() == []


@pytest.mark.unit
def test_nudge_noop_when_blocked_for_other_reason():
    """A campaign whose readiness reports NO missing essentials (e.g. work blocked for
    some other cause) is not nudged — the list comes from apply_readiness, not invented."""
    storage = InMemoryStorage()
    _campaign(storage)
    notifier = _notifier()
    # ``ready`` False but ``missing`` empty: not an essentials problem -> no nudge.
    odd = ApplyReadiness(ready=False, missing=(), reason="blocked elsewhere")
    sched = _sched(storage, notifier, odd)
    out = sched.tick(datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert out["essentials_nudges"] == []
    assert notifier.list_inbox() == []


@pytest.mark.unit
def test_single_missing_item_reads_naturally():
    svc = EssentialsNudgeService(
        notification_service=_notifier(),
        onboarding_service=_Onboarding(_BLOCKED),
    )
    one = svc.build_message(("a résumé",))
    assert one == "I'm ready to start applying, but I still need a résumé. Add it and I'll begin."
    two = svc.build_message(("target roles", "a salary floor"))
    assert two == (
        "I'm ready to start applying, but I still need target roles and a salary floor. "
        "Add them and I'll begin."
    )


@pytest.mark.unit
def test_fanout_respects_optin_inapp_always_present():
    """The nudge flows through the existing notifier: it always lands in the in-app inbox,
    and external fan-out only happens for opted-in channels (none here)."""
    storage = InMemoryStorage()
    cid = _campaign(storage)
    notifier = NotificationService(AppriseNotifier())
    svc = _service(notifier, _BLOCKED)
    handle = svc.emit(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC))
    assert handle is not None
    assert len(notifier.list_inbox()) == 1
    fired_channels = {c.channel for c in notifier._notification._captured}
    assert fired_channels == {"in_app"}
