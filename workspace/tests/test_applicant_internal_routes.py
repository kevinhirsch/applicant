"""Hermetic tests for the Stage 2.5 internal callback channel auth gate
(routes/applicant_internal_routes.py).

Mounts only the internal router on a bare FastAPI app and exercises the
token gate + owner scoping without booting the full workspace app:

- channel DISABLED when no secret is configured (403, no token would match)
- token REQUIRED: missing/wrong token -> 403, correct token -> 200
- constant-time comparison via secrets.compare_digest (correct token only)
- owner scoping: X-Applicant-Owner is reflected through internal_owner
- lane placeholders return 501 (only with a valid token)
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_channel_enabled,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


def _enable(monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)


def test_disabled_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    assert internal_channel_enabled() is False
    # Even presenting *some* token is rejected: the channel is off.
    resp = client.get("/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: "anything"})
    assert resp.status_code == 403


def test_ping_requires_token(client, monkeypatch):
    _enable(monkeypatch)
    assert internal_channel_enabled() is True
    # No token header.
    assert client.get("/api/applicant/internal/ping").status_code == 403
    # Wrong token.
    bad = client.get("/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: "wrong"})
    assert bad.status_code == 403


def test_ping_succeeds_with_correct_token(client, monkeypatch):
    _enable(monkeypatch)
    resp = client.get(
        "/api/applicant/internal/ping", headers={INTERNAL_TOKEN_HEADER: TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "owner": None}


def test_owner_scoping_reflected(client, monkeypatch):
    _enable(monkeypatch)
    resp = client.get(
        "/api/applicant/internal/ping",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
    )
    assert resp.status_code == 200
    assert resp.json()["owner"] == "kevin"


def test_lane_placeholders_return_501_with_token(client, monkeypatch):
    _enable(monkeypatch)
    h = {INTERNAL_TOKEN_HEADER: TOKEN}
    # Lane A (calendar/interviews) is now implemented (see
    # test_applicant_internal_calendar.py). Remaining lanes are still 501.
    assert client.post("/api/applicant/internal/research", headers=h, json={"query": "x"}).status_code == 501
    assert client.get("/api/applicant/internal/local-models", headers=h).status_code == 501


def test_lane_placeholders_still_token_gated(client, monkeypatch):
    _enable(monkeypatch)
    # No token -> 403 before reaching the 501 placeholder.
    assert client.get("/api/applicant/internal/calendar/interviews").status_code == 403
    assert client.post("/api/applicant/internal/research", json={"query": "x"}).status_code == 403
    assert client.get("/api/applicant/internal/local-models").status_code == 403
