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
