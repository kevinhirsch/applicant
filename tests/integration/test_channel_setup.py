"""Channel setup wired into the OOBE wizard (FR-NOTIF-1, FR-OOBE-2/3).

Hermetic: the default lane never sends to Discord/SMTP — the notifier captures
offline. A live real-send test is gated behind NOTIF_LIVE_TEST=1.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _open_llm_gate(client):
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


@pytest.mark.integration
def test_configuring_channels_marks_gate_and_ungates_work(client):
    _open_llm_gate(client)
    # Channels not yet configured.
    chan = client.get("/api/setup/channels").json()
    assert chan["channels_configured"] is False

    r = client.post(
        "/api/setup/channels",
        json={
            "discord_webhook_url": "https://discord.test/api/webhooks/x/y",
            "apprise_urls": "mailto://user:pw@smtp.test",
        },
    )
    assert r.status_code == 204

    chan2 = client.get("/api/setup/channels").json()
    assert chan2["discord_configured"] is True
    assert chan2["email_configured"] is True
    assert chan2["channels_configured"] is True

    # The channels step now reads complete in the wizard status (FR-OOBE-2).
    status = client.get("/api/setup/status").json()
    assert "channels" in status["steps_complete"]


@pytest.mark.integration
def test_channels_endpoint_rejects_empty(client):
    _open_llm_gate(client)
    r = client.post("/api/setup/channels", json={})
    assert r.status_code == 400


@pytest.mark.integration
def test_test_notification_is_hermetic(client):
    _open_llm_gate(client)
    client.post(
        "/api/setup/channels",
        json={"discord_webhook_url": "https://discord.test/api/webhooks/x/y"},
    )
    r = client.post("/api/setup/channels/test")
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] is True
    # No network was touched (send_real defaults off); the channel is reported.
    assert "discord" in body["channels"]
    # K6 UX honesty: the default lane is a DRY RUN — say so instead of implying it
    # delivered. live=False + a note the UI surfaces (FR-NOTIF-1).
    assert body["live"] is False
    assert "NOTIFICATIONS_LIVE" in body["note"]


@pytest.mark.integration
def test_ntfy_channel_round_trips_and_completes_gate(client):
    # K5: ntfy push is configurable from the front-door, not just NTFY_URL boot env.
    # Saving an ntfy topic alone marks channels configured and ungates work (FR-NOTIF-1).
    _open_llm_gate(client)
    r = client.post(
        "/api/setup/channels",
        json={"ntfy_url": "ntfy://ntfy.sh/applicant-test-topic"},
    )
    assert r.status_code == 204

    chan = client.get("/api/setup/channels").json()
    assert chan["ntfy_configured"] is True
    assert chan["channels_configured"] is True

    status = client.get("/api/setup/status").json()
    assert "channels" in status["steps_complete"]

    # The live notifier picked up the ntfy channel without a restart.
    test = client.post("/api/setup/channels/test").json()
    assert "ntfy" in test["channels"]


@pytest.mark.integration
def test_quiet_hours_round_trip_and_24_7(client):
    # FR-NOTIF-5: quiet hours default to 24/7 (disabled) and round-trip through the
    # dedicated endpoint, reconfiguring the live notifier in place.
    _open_llm_gate(client)
    qh = client.get("/api/setup/channels/quiet-hours").json()
    assert qh["enabled"] is False  # 24/7 by default

    r = client.post(
        "/api/setup/channels/quiet-hours",
        json={"enabled": True, "start": "22:30", "end": "07:15", "tz": "America/Phoenix"},
    )
    assert r.status_code == 204
    saved = client.get("/api/setup/channels/quiet-hours").json()
    assert saved == {
        "enabled": True,
        "start": "22:30",
        "end": "07:15",
        "tz": "America/Phoenix",
    }
    # It also rides along on the channels GET so the UI renders it in one fetch.
    assert client.get("/api/setup/channels").json()["quiet_hours"]["enabled"] is True

    # Switching back to 24/7 disables the window.
    assert client.post("/api/setup/channels/quiet-hours", json={"enabled": False}).status_code == 204
    assert client.get("/api/setup/channels/quiet-hours").json()["enabled"] is False


@pytest.mark.integration
def test_quiet_hours_rejects_bad_time(client):
    _open_llm_gate(client)
    r = client.post(
        "/api/setup/channels/quiet-hours",
        json={"enabled": True, "start": "25:00", "end": "07:00"},
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("NOTIF_LIVE_TEST") != "1",
    reason="Set NOTIF_LIVE_TEST=1 + DISCORD_WEBHOOK_URL to send a real notification.",
)
def test_real_discord_send_smoke():
    """Live Discord send via Apprise — integration-gated, opt-in only (FR-NOTIF-1)."""
    from applicant.adapters.notification.apprise_notifier import AppriseNotifier
    from applicant.ports.driven.notification import Notification, NotificationUrgency

    webhook = os.environ["DISCORD_WEBHOOK_URL"]
    notifier = AppriseNotifier(discord_webhook_url=webhook, in_app=False, send_real=True)
    handle = notifier.notify(
        Notification(
            title="Applicant live test",
            body="Phase 1 escalation ladder smoke test.",
            urgency=NotificationUrgency.IMMEDIATE,
            dedup_key="live-smoke",
        )
    )
    assert handle
