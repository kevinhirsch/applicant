"""Notifications router — lens 10 audit findings #26 and #55.

#26 — ``NotificationService.list_inbox(include_seen=True)`` already exists but the
router hard-coded the default, so no caller could ever request dismissed/seen
notifications (e.g. an "undo my last dismiss" affordance). The router now accepts
an optional ``include_seen`` query param and threads it straight through.

#55 — ``GET /api/notifications`` shipped the entire (up to ~1000-row) inbox on
every poll. The router now accepts optional ``since`` (an ISO-8601 timestamp,
matching the shape of each row's own ``created_at``) and ``limit`` query params
so a caller that already tracks a newest-seen cursor can fetch only what's new.

Both params are optional and default to the historical behavior — the Portal's
existing no-params poll must keep working unchanged, which
``test_default_call_is_unchanged`` pins down against the pre-existing
integration-level behavior in ``tests/integration/test_notifications_router.py``.

Hermetic: in-memory storage, real container services, LLM gate opened like the
peer router tests (``test_post_submission_router.py``).
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.ports.driven.notification import Notification, NotificationUrgency


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/setup/llm",
                json={"provider": "ollama", "base_url": "http://x/v1", "model": "llama3.1"},
            ).status_code
            == 204
        )
        yield c, app


def _push(app, **kw):
    app.state.container.notification_service._notification.notify(Notification(**kw))


# --- (a) default call is unchanged ------------------------------------------


def test_default_call_is_unchanged(client):
    """No query params -> same shape/behavior as before the fix: newest first,
    dismissed entries omitted, full (unbounded-by-us) inbox."""
    c, app = client
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
    assert after["count"] == 1
    assert all(i["id"] != target for i in after["items"])


def test_default_call_omits_seen_entries(client):
    c, app = client
    _push(app, title="A", body="a", dedup_key="digest:a")
    data = c.get("/api/notifications").json()
    target = data["items"][0]["id"]
    c.post(f"/api/notifications/{target}/seen")

    default = c.get("/api/notifications").json()
    assert default["count"] == 0
    assert default["items"] == []


# --- (b) include_seen=true surfaces dismissed entries -----------------------


def test_include_seen_returns_dismissed_entries(client):
    c, app = client
    _push(app, title="A", body="a", dedup_key="digest:a")
    _push(app, title="B", body="b", dedup_key="digest:b")

    data = c.get("/api/notifications").json()
    ids = {i["title"]: i["id"] for i in data["items"]}
    assert c.post(f"/api/notifications/{ids['A']}/seen").status_code == 204

    # Default omits the dismissed one.
    default = c.get("/api/notifications").json()
    assert default["count"] == 1
    assert {i["title"] for i in default["items"]} == {"B"}

    # include_seen=true surfaces it again, flagged as seen.
    full = c.get("/api/notifications", params={"include_seen": "true"}).json()
    assert full["count"] == 2
    by_title = {i["title"]: i for i in full["items"]}
    assert by_title["A"]["seen"] is True
    assert by_title["B"]["seen"] is False


def test_include_seen_false_is_explicitly_identical_to_default(client):
    c, app = client
    _push(app, title="A", body="a", dedup_key="digest:a")
    data = c.get("/api/notifications").json()
    target = data["items"][0]["id"]
    c.post(f"/api/notifications/{target}/seen")

    default = c.get("/api/notifications").json()
    explicit = c.get("/api/notifications", params={"include_seen": "false"}).json()
    assert default == explicit == {"count": 0, "items": []}


# --- (c) limit bounds the page ----------------------------------------------


def test_limit_bounds_returned_rows(client):
    c, app = client
    _push(app, title="First", body="1", dedup_key="digest:1")
    _push(app, title="Second", body="2", dedup_key="digest:2")
    _push(app, title="Third", body="3", dedup_key="digest:3")

    unbounded = c.get("/api/notifications").json()
    assert unbounded["count"] == 3

    bounded = c.get("/api/notifications", params={"limit": 1}).json()
    assert bounded["count"] == 1
    # Newest-first: the last one pushed comes back.
    assert bounded["items"][0]["title"] == "Third"


def test_limit_zero_is_rejected(client):
    c, _app = client
    r = c.get("/api/notifications", params={"limit": 0})
    assert r.status_code == 422


# --- (c) since filters to only newer rows -----------------------------------


def test_since_filters_out_entries_at_or_before_the_cursor(client):
    c, app = client
    _push(app, title="Older", body="o", dedup_key="digest:older")
    cursor = c.get("/api/notifications").json()["items"][0]["created_at"]

    time.sleep(0.01)  # guarantee a distinct, later created_at
    _push(app, title="Newer", body="n", dedup_key="digest:newer")

    data = c.get("/api/notifications", params={"since": cursor}).json()
    titles = {i["title"] for i in data["items"]}
    assert titles == {"Newer"}
    assert "Older" not in titles


def test_since_in_the_future_returns_nothing(client):
    c, app = client
    _push(app, title="Anything", body="x", dedup_key="digest:x")
    data = c.get("/api/notifications", params={"since": "2999-01-01T00:00:00+00:00"}).json()
    assert data == {"count": 0, "items": []}


def test_since_malformed_is_a_400(client):
    c, app = client
    _push(app, title="Anything", body="x", dedup_key="digest:x")
    r = c.get("/api/notifications", params={"since": "not-a-timestamp"})
    assert r.status_code == 400


def test_since_and_limit_compose(client):
    c, app = client
    _push(app, title="One", body="1", dedup_key="digest:one")
    cursor = c.get("/api/notifications").json()["items"][0]["created_at"]
    time.sleep(0.01)
    _push(app, title="Two", body="2", dedup_key="digest:two")
    time.sleep(0.01)
    _push(app, title="Three", body="3", dedup_key="digest:three")

    data = c.get("/api/notifications", params={"since": cursor, "limit": 1}).json()
    assert data["count"] == 1
    assert data["items"][0]["title"] == "Three"


# --- gate still applies with the new params in play -------------------------


def test_llm_gate_still_blocks_new_params_when_not_configured():
    with TestClient(create_app()) as c:
        r = c.get("/api/notifications", params={"include_seen": "true", "limit": 5})
        assert r.status_code == 409
