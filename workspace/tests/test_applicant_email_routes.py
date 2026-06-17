"""Hermetic tests for the Applicant Email proxy (routes/applicant_email_routes.py).

Zero network: the engine is served entirely by an ``httpx.MockTransport`` injected
through the route module's construction seams (``_engine_client`` for the shared
client; ``_PRESENCE_TRANSPORT`` for the direct presence POST). Covers the happy
path of every endpoint (correct engine path/method/body relay), the typed-error
degradation (timeout -> 504, unreachable -> 503, engine 5xx -> 502, engine 4xx
forwarded incl. the mandatory-decline-feedback 422), and that auth is enforced.
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_email_routes as mod
from routes.applicant_email_routes import (
    ApplicantEngineClient,
    setup_applicant_email_routes,
)


def _mock_engine(handler):
    """A no-network ApplicantEngineClient backed by ``handler``."""
    return ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )


@pytest.fixture
def make_client(monkeypatch):
    """Build a TestClient whose engine calls hit ``handler`` and nothing else.

    ``authed`` (default True) installs a tiny middleware that sets
    ``request.state.current_user`` so ``require_user`` passes — mirroring the
    real auth middleware without standing it up.
    """

    def _factory(handler, *, authed=True):
        # Route the shared async client AND the direct presence POST at the mock.
        monkeypatch.setattr(mod, "_engine_client", lambda: _mock_engine(handler))
        monkeypatch.setattr(mod, "_PRESENCE_TRANSPORT", httpx.MockTransport(handler))

        app = FastAPI()

        @app.middleware("http")
        async def _auth(request: Request, call_next):
            if authed:
                request.state.current_user = "kevin"
            return await call_next(request)

        app.include_router(setup_applicant_email_routes())
        return TestClient(app)

    return _factory


# -- happy paths -----------------------------------------------------------


def test_list_campaigns_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json=[{"id": "camp-1", "name": "Backend roles"}])

    client = make_client(handler)
    resp = client.get("/api/applicant/email/campaigns")
    assert resp.status_code == 200
    assert resp.json() == {"campaigns": [{"id": "camp-1", "name": "Backend roles"}]}
    assert captured["path"] == "/api/campaigns"


def test_get_digest_relays_to_engine(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        return httpx.Response(200, json={"rows": [{"role": "SWE"}], "empty": False})

    client = make_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1")
    assert resp.status_code == 200
    assert resp.json() == {"rows": [{"role": "SWE"}], "empty": False}
    assert captured["path"] == "/api/digest/camp-1"
    assert captured["method"] == "GET"


def test_get_digest_email_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"subject": "Today's roles", "body": "..."})

    client = make_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1/email")
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Today's roles"
    assert captured["path"] == "/api/digest/camp-1/email"


def test_deliver_digest_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        return httpx.Response(200, json={"row_count": 3, "delivered_channels": ["email"]})

    client = make_client(handler)
    resp = client.post("/api/applicant/email/digest/camp-1/deliver")
    assert resp.status_code == 200
    assert resp.json()["row_count"] == 3
    assert captured["path"] == "/api/digest/camp-1/deliver"
    assert captured["method"] == "POST"


def test_presence_posts_and_acks(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(204)

    client = make_client(handler)
    resp = client.post("/api/applicant/email/presence", json={"present": True})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "present": True}
    assert captured["path"] == "/api/digest/presence"
    assert '"present"' in captured["body"] and "true" in captured["body"]


def test_approve_application_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(201, json={"decision_id": "d1", "type": "approve"})

    client = make_client(handler)
    resp = client.post("/api/applicant/email/applications/app-9/approve")
    assert resp.status_code == 200
    assert resp.json()["decision_id"] == "d1"
    assert captured["path"] == "/api/digest/applications/app-9/approve"


def test_decline_application_sends_feedback_body(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(201, json={"decision_id": "d2", "type": "decline"})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/email/applications/app-9/decline",
        json={"feedback_text": "too junior", "criteria_delta": {"seniority": "senior"}},
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "decline"
    assert captured["path"] == "/api/digest/applications/app-9/decline"
    assert "too junior" in captured["body"]
    assert "seniority" in captured["body"]


def test_feedback_freetext_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(201, json={"ok": True})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/email/feedback/freetext",
        json={"campaign_id": "camp-1", "text": "prefer remote"},
    )
    assert resp.status_code == 200
    assert captured["path"] == "/api/feedback/freetext"
    assert "prefer remote" in captured["body"]
    assert "camp-1" in captured["body"]


def test_feedback_survey_relays(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        return httpx.Response(201, json={"ok": True})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/email/feedback/survey",
        json={"campaign_id": "camp-1", "answers": {"q1": "a1"}},
    )
    assert resp.status_code == 200
    assert captured["path"] == "/api/feedback/survey"
    assert "q1" in captured["body"]


# -- error degradation -----------------------------------------------------


def test_timeout_becomes_504(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = make_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1")
    assert resp.status_code == 504


def test_connect_error_becomes_503(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    resp = client.get("/api/applicant/email/digest/camp-1")
    assert resp.status_code == 503


def test_engine_5xx_becomes_502(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler)
    resp = client.post("/api/applicant/email/digest/camp-1/deliver")
    assert resp.status_code == 502


def test_engine_422_is_forwarded_on_decline(make_client):
    """Mandatory decline feedback was blank -> engine 422 passes through (FR-FB-1)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "feedback is required"})

    client = make_client(handler)
    resp = client.post(
        "/api/applicant/email/applications/app-9/decline",
        json={"feedback_text": "   "},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "feedback is required"


def test_presence_engine_error_degrades(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    resp = client.post("/api/applicant/email/presence", json={"present": True})
    assert resp.status_code == 503


# -- auth ------------------------------------------------------------------


def test_unauthenticated_is_rejected(make_client):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never hit
        return httpx.Response(200, json={})

    client = make_client(handler, authed=False)
    resp = client.get("/api/applicant/email/digest/camp-1")
    assert resp.status_code == 401
