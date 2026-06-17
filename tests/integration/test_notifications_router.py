"""Notification-center router integration: list + dismiss over the live inbox."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.ports.driven.notification import Notification, NotificationUrgency


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c, app


def _open_gate(client):
    assert (
        client.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
        ).status_code
        == 204
    )


def _push(app, **kw):
    app.state.container.notification_service._notification.notify(Notification(**kw))


@pytest.mark.integration
def test_gate_blocks_before_setup(client):
    c, _ = client
    assert c.get("/api/notifications").status_code == 409


@pytest.mark.integration
def test_list_and_dismiss(client):
    c, app = client
    _open_gate(c)
    _push(app, title="Digest ready", body="2 roles", dedup_key="digest:c1")
    _push(app, title="Heads up", body="something", urgency=NotificationUrgency.IMMEDIATE)

    data = c.get("/api/notifications").json()
    assert data["count"] == 2
    kinds = {i["title"]: i["kind"] for i in data["items"]}
    assert kinds["Digest ready"] == "digest"
    assert kinds["Heads up"] == "error"

    target = data["items"][0]["id"]
    assert c.post(f"/api/notifications/{target}/seen").status_code == 204
    after = c.get("/api/notifications").json()
    assert all(i["id"] != target for i in after["items"])
    # Dismissing an unknown id is a 404 so the caller can drop the row.
    assert c.post("/api/notifications/does-not-exist/seen").status_code == 404


@pytest.mark.integration
def test_action_items_carry_links_action(client):
    c, app = client
    _open_gate(c)
    _push(app, title="Approve", body="b", dedup_key="decision:abc123", web_preemptable=True)
    data = c.get("/api/notifications").json()
    item = data["items"][0]
    assert item["kind"] == "action"
    assert item["links_action"] is True
    assert item["action_ref"] == "abc123"
