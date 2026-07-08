"""P1-4 — Notifications out of the box.

Three pins on the story's engine half:

1. **Per-channel Send test** — ``POST /api/setup/channels/test`` with a
   ``channel`` body tests exactly one channel (and 400s on an unknown or
   unconfigured one), while the historical no-body shape keeps fanning out to
   every configured channel unchanged.
2. **A watched test button tells the truth** — ``AppriseNotifier.send_test``
   dispatches directly (no ladder), so a live delivery failure PROPAGATES to
   the caller instead of being logged-and-retried like a real alert.
3. **Nothing silently drops** — a live push channel that fails delivery leaves
   an error entry in the zero-config in-app inbox (deduped while undismissed),
   so a broken webhook/SMTP/topic is discoverable in the product, not only in
   server logs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.notification.apprise_notifier import (
    AppriseNotifier,
    NotificationDeliveryError,
)
from applicant.app.main import create_app
from applicant.ports.driven.notification import Notification, NotificationUrgency


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.1",
            },
        )
        assert r.status_code == 204
        yield c


def _configure_discord_and_ntfy(client) -> None:
    r = client.post(
        "/api/setup/channels",
        json={
            "discord_webhook_url": "https://discord.test/api/webhooks/x/y",
            "ntfy_url": "ntfy://ntfy.sh/applicant-test-topic",
        },
    )
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# 1. The router lane
# ---------------------------------------------------------------------------


def test_no_body_test_still_fans_out_to_every_configured_channel(client):
    _configure_discord_and_ntfy(client)
    res = client.post("/api/setup/channels/test")
    assert res.status_code == 200
    body = res.json()
    assert body["sent"] is True
    assert "discord" in body["channels"] and "ntfy" in body["channels"]
    # Hermetic default lane stays honest about the dry run.
    assert body["live"] is False
    assert "NOTIFICATIONS_LIVE" in body["note"]


def test_single_channel_test_targets_only_that_channel(client):
    _configure_discord_and_ntfy(client)
    res = client.post("/api/setup/channels/test", json={"channel": "discord"})
    assert res.status_code == 200
    body = res.json()
    assert body["sent"] is True
    assert body["channels"] == ["discord"]
    assert body["live"] is False  # dry-run honesty rides along on this lane too
    assert "NOTIFICATIONS_LIVE" in body["note"]


def test_in_app_channel_is_testable_with_zero_config(client):
    # The in-app inbox works out of the box — no channel setup required.
    res = client.post("/api/setup/channels/test", json={"channel": "in_app"})
    assert res.status_code == 200
    assert res.json()["channels"] == ["in_app"]
    # And the test ping is actually listed in the in-app inbox, as info not error.
    inbox = client.get("/api/notifications").json()
    tests = [i for i in inbox["items"] if "test" in i["title"].lower()]
    assert tests, "the in-app test ping must land in the notification center"
    assert all(i["kind"] == "info" for i in tests)


def test_unconfigured_channel_is_a_400_not_a_fake_success(client):
    # Nothing configured: testing discord must refuse, not claim success.
    res = client.post("/api/setup/channels/test", json={"channel": "discord"})
    assert res.status_code == 400
    assert "discord" in res.json()["detail"]


def test_unknown_channel_name_is_a_400(client):
    res = client.post("/api/setup/channels/test", json={"channel": "pigeon"})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# 2. send_test: direct dispatch, honest failures
# ---------------------------------------------------------------------------


def test_send_test_dispatches_exactly_one_channel():
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        ntfy_url="ntfy://ntfy.sh/topic",
    )
    notifier.send_test("discord")
    sends = notifier.captured()
    assert [s.channel for s in sends] == ["discord"]
    assert sends[0].dedup_key == "channels-test:discord"


def test_send_test_rejects_unknown_and_unconfigured_channels():
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    with pytest.raises(ValueError):
        notifier.send_test("pigeon")
    with pytest.raises(ValueError):
        notifier.send_test("ntfy")  # not configured


def test_send_test_propagates_a_live_delivery_failure():
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh", send_real=True
    )

    def _boom(channel, notification):
        raise NotificationDeliveryError("Apprise delivery failed on discord.")

    notifier._send_real_dispatch = _boom
    with pytest.raises(NotificationDeliveryError):
        notifier.send_test("discord")


def test_per_channel_test_ping_classifies_as_info_in_the_inbox():
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    notifier.send_test("in_app")
    entries = notifier.list_inbox()
    assert entries and entries[0].kind == "info"


# ---------------------------------------------------------------------------
# 3. Nothing silently drops: failed live pushes surface in the in-app inbox
# ---------------------------------------------------------------------------


def _failing_notifier() -> AppriseNotifier:
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh", send_real=True
    )
    real = notifier._send_real_dispatch

    def _fail_discord(channel, notification):
        if channel == "discord":
            raise NotificationDeliveryError("webhook gone")
        return real(channel, notification)

    notifier._send_real_dispatch = _fail_discord
    return notifier


def test_failed_live_push_leaves_an_error_entry_in_the_inbox():
    notifier = _failing_notifier()
    notifier.notify(
        Notification(
            title="Agent needs you",
            body="x",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="alert-1",
        )
    )
    failures = [
        e for e in notifier.list_inbox() if e.dedup_key == "channel_failure:discord"
    ]
    assert len(failures) == 1
    entry = failures[0]
    assert entry.kind == "error"
    assert "Discord" in entry.title
    # The body says where to fix it — plain language, no jargon.
    assert "Settings" in entry.body and "Notifications" in entry.body


def test_failure_entry_is_deduped_across_retries_until_dismissed():
    notifier = _failing_notifier()
    for i in range(3):
        notifier.notify(
            Notification(
                title=f"Alert {i}",
                body="x",
                urgency=NotificationUrgency.IMMEDIATE,
                dedup_key=f"alert-{i}",
            )
        )
    failures = [
        e for e in notifier.list_inbox() if e.dedup_key == "channel_failure:discord"
    ]
    assert len(failures) == 1, "retries must not stack duplicate failure notes"
    # Once dismissed, a NEW failure may surface again (the user asked to be told).
    assert notifier.mark_seen(failures[0].id)
    notifier.notify(
        Notification(
            title="Another alert",
            body="x",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="alert-later",
        )
    )
    fresh = [
        e for e in notifier.list_inbox() if e.dedup_key == "channel_failure:discord"
    ]
    assert len(fresh) == 1


def test_failed_test_ping_does_not_add_an_inbox_failure_note():
    # The Send-test button reports its failure inline, right where the user is
    # looking — no duplicate error entry in the center.
    notifier = _failing_notifier()
    with pytest.raises(NotificationDeliveryError):
        notifier.send_test("discord")
    assert not [
        e for e in notifier.list_inbox() if e.dedup_key == "channel_failure:discord"
    ]
