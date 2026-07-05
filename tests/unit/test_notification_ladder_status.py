"""Regression coverage for dark-engine audit item #77 (B7): the notification
escalation-ladder state (held -> email) is invisible.

Every tick advances the hold->email escalation cadence (Discord held briefly for
a quick web approval, then email after the configurable timeout, both further
held during quiet hours) but nothing before now exposed WHICH rung a decision
was currently sitting on. ``AppriseNotifier.ladder_status`` / the
``NotificationService.ladder_status`` passthrough add read-only introspection;
the ``pending_actions`` router's ``notification_ladder`` field wires it onto
the SAME pending-action items the Portal already renders (keyed off the item's
own ``payload["dedup_key"]``, which ``material_service`` already sets to match
the exact ref its ``notify_decision`` call used).

Verified, by hand, to go RED when ``ladder_status``/the router field are
reverted out of ``apprise_notifier.py``/``notification_service.py``/
``pending_actions.py`` (restoring from a pre-change backup), then GREEN again
after restoring the change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.app.deps import get_notification_service
from applicant.app.main import create_app
from applicant.application.services.notification_service import NotificationService
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.notification import Notification


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _notifier(clock, **kw):
    return AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pw@smtp.test",
        clock=clock,
        **kw,
    )


# --- AppriseNotifier.ladder_status -------------------------------------------


def test_ladder_status_none_when_never_sent():
    n = _notifier(_Clock())
    assert n.ladder_status("decision:material_review:doc-1") is None


def test_ladder_status_none_once_acted_on():
    clock = _Clock()
    n = _notifier(clock)
    n.notify(Notification(title="Approve?", body="x", dedup_key="k1", web_preemptable=True))
    n.expire("k1")
    assert n.ladder_status("k1") is None


def test_ladder_status_reports_the_held_rung_and_when_it_escalates():
    clock = _Clock()
    n = _notifier(clock)
    n.notify(Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True))

    status = n.ladder_status("k1")
    assert status is not None
    assert status["held"] is True
    assert status["next_channel"] == "discord"
    # Discord is held _DISCORD_HOLD_SECONDS (30s by default in these tests).
    expected_due = clock.now + timedelta(seconds=30)
    assert status["next_due_at"] == expected_due.isoformat()
    assert status["quiet_hours_held"] is False
    channels_by_name = {c["channel"]: c for c in status["channels"]}
    assert channels_by_name["in_app"]["fired"] is True
    assert channels_by_name["in_app"]["due_at"] is None
    assert channels_by_name["discord"]["fired"] is False
    assert channels_by_name["email"]["fired"] is False


def test_ladder_status_advances_to_email_once_discord_fires():
    clock = _Clock()
    n = _notifier(clock)
    n.notify(Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True))
    clock.tick(30)
    n.advance()

    status = n.ladder_status("k1")
    assert status is not None
    assert status["next_channel"] == "email"


def test_ladder_status_flags_quiet_hours_hold():
    clock = _Clock()  # 2026-01-01 12:00 UTC
    n = _notifier(clock, quiet_hours=(22, 7))  # 22:00-07:00 quiet window
    clock.now = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)  # inside the window
    n.notify(Notification(title="Approve?", body="Acme role", dedup_key="k1", web_preemptable=True))

    status = n.ladder_status("k1")
    assert status is not None
    assert status["next_channel"] == "discord"
    assert status["quiet_hours_held"] is True


# --- NotificationService.ladder_status passthrough --------------------------


def test_notification_service_ladder_status_uses_the_decision_prefix():
    clock = _Clock()
    notifier = _notifier(clock)
    svc = NotificationService(notifier)
    svc.notify_decision("material_review:doc-1", title="Review ready", body="x")

    # The RAW ref (no "decision:" prefix) is what a caller (e.g. a pending
    # action's own payload) holds — the service must derive the same key
    # ``notify_decision`` used internally.
    status = svc.ladder_status("material_review:doc-1")
    assert status is not None
    assert status["held"] is True


def test_notification_service_ladder_status_none_when_notifier_lacks_it():
    class _NoLadderNotifier:
        def notify(self, *a, **kw):
            return "h1"

    svc = NotificationService(_NoLadderNotifier())
    assert svc.ladder_status("anything") is None


# --- pending_actions router wiring -------------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


class _FakeLadderNotificationService:
    """A minimal stand-in exposing only what ``pending_actions.py`` calls, so the
    router-wiring test is isolated from AppriseNotifier's own escalation-timing
    logic (covered directly above)."""

    def __init__(self, ladder_by_ref: dict) -> None:
        self._ladder_by_ref = ladder_by_ref

    def ladder_status(self, decision_ref: str):
        return self._ladder_by_ref.get(decision_ref)


def test_list_pending_carries_the_notification_ladder_field(client):
    svc = client.app.state.container.pending_actions_service
    cid = CampaignId(new_id())
    held_status = {
        "held": True,
        "next_channel": "email",
        "next_due_at": "2026-01-01T12:15:00+00:00",
        "quiet_hours_held": False,
        "channels": [],
    }
    action = svc.materialize(
        cid,
        "material_review",
        "Review your cover letter",
        payload={"document_id": "doc-1"},
        dedup_key="material_review:doc-1",
    )

    fake = _FakeLadderNotificationService({"material_review:doc-1": held_status})
    client.app.dependency_overrides[get_notification_service] = lambda: fake
    try:
        r = client.get(f"/api/pending-actions/{cid}")
    finally:
        client.app.dependency_overrides.pop(get_notification_service, None)

    assert r.status_code == 200
    items = r.json()["items"]
    row = next(i for i in items if i["id"] == action.id)
    assert row["notification_ladder"] == held_status


def test_list_pending_notification_ladder_is_none_without_a_dedup_key(client):
    svc = client.app.state.container.pending_actions_service
    cid = CampaignId(new_id())
    action = svc.materialize(cid, "agent_question", "Which city?")

    fake = _FakeLadderNotificationService({})
    client.app.dependency_overrides[get_notification_service] = lambda: fake
    try:
        r = client.get(f"/api/pending-actions/{cid}")
    finally:
        client.app.dependency_overrides.pop(get_notification_service, None)

    row = next(i for i in r.json()["items"] if i["id"] == action.id)
    assert row["notification_ladder"] is None


def test_list_pending_ladder_lookup_failure_degrades_to_none(client):
    svc = client.app.state.container.pending_actions_service
    cid = CampaignId(new_id())
    action = svc.materialize(
        cid,
        "material_review",
        "Review your cover letter",
        payload={"document_id": "doc-1"},
        dedup_key="material_review:doc-1",
    )

    class _BrokenNotificationService:
        def ladder_status(self, decision_ref: str):
            raise RuntimeError("boom")

    client.app.dependency_overrides[get_notification_service] = lambda: _BrokenNotificationService()
    try:
        r = client.get(f"/api/pending-actions/{cid}")
    finally:
        client.app.dependency_overrides.pop(get_notification_service, None)

    assert r.status_code == 200
    row = next(i for i in r.json()["items"] if i["id"] == action.id)
    assert row["notification_ladder"] is None
