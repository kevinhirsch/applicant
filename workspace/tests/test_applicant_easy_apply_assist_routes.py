"""Hermetic tests for the Easy Apply assisted-mode proxy (P2-14).

Mounts only ``routes/applicant_easy_apply_routes.py`` on a bare FastAPI app with
a tiny stand-in auth middleware (the real global auth gate lives in ``app.py``
and is out of scope here). The engine is faked with a scripted ``FakeEngine``
patched in for ``ApplicantEngineClient`` -- zero network. Mirrors
``test_applicant_followups_routes.py``'s harness exactly.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_easy_apply_routes as mod
from routes.applicant_easy_apply_routes import setup_applicant_easy_apply_routes
from src.applicant_engine import EngineError


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_easy_apply_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    consent: dict = {"given": False, "given_at": None}
    assist_result: dict = {}  # (campaign_id, posting_id) -> engine response dict
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_campaigns(self):
        FakeEngine.calls.append("list_campaigns")
        if "list_campaigns" in FakeEngine.raises:
            raise FakeEngine.raises["list_campaigns"]
        return FakeEngine.campaigns

    async def easy_apply_consent_status(self):
        FakeEngine.calls.append("consent_status")
        if "consent_status" in FakeEngine.raises:
            raise FakeEngine.raises["consent_status"]
        return dict(FakeEngine.consent)

    async def easy_apply_consent_give(self):
        FakeEngine.calls.append("consent_give")
        if "consent_give" in FakeEngine.raises:
            raise FakeEngine.raises["consent_give"]
        FakeEngine.consent = {"given": True, "given_at": "2026-07-08T00:00:00+00:00"}
        return dict(FakeEngine.consent)

    async def easy_apply_assist(self, campaign_id, posting_id):
        key = ("assist", campaign_id, posting_id)
        FakeEngine.calls.append(key)
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.assist_result.get((campaign_id, posting_id), {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.consent = {"given": False, "given_at": None}
    FakeEngine.assist_result = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth ---------------------------------------------------------------


def test_unauthenticated_consent_get_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/easy-apply/consent")
    assert r.status_code == 401


def test_unauthenticated_consent_post_is_rejected(monkeypatch):
    """The WRITE is gated too (DISC-15b: require_engine_owner on reads AND
    writes) -- an unauthenticated caller can never record consent."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.post("/api/applicant/easy-apply/consent")
    assert r.status_code == 401
    # The engine write is never even attempted.
    assert "consent_give" not in FakeEngine.calls


def test_unauthenticated_assist_get_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/easy-apply/c1/p1")
    assert r.status_code == 401


# --- consent --------------------------------------------------------------


def test_consent_not_given_reads_false(client):
    r = client.get("/api/applicant/easy-apply/consent")
    assert r.status_code == 200
    assert r.json() == {"given": False, "given_at": None}


def test_recording_consent_flips_it(client):
    r = client.post("/api/applicant/easy-apply/consent")
    assert r.status_code == 201
    assert r.json()["given"] is True

    r2 = client.get("/api/applicant/easy-apply/consent")
    assert r2.json()["given"] is True


def test_consent_read_degrades_soft_when_engine_unreachable(client):
    FakeEngine.raises["consent_status"] = EngineError("boom", status=None)
    r = client.get("/api/applicant/easy-apply/consent")
    assert r.status_code == 200
    assert r.json()["given"] is False


def test_consent_write_failure_is_a_real_error(client):
    FakeEngine.raises["consent_give"] = EngineError("boom", status=502)
    r = client.post("/api/applicant/easy-apply/consent")
    assert r.status_code == 502


# --- assist: owner-scoped campaign-id fan-out ------------------------------


def test_campaign_not_owned_is_404(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.get("/api/applicant/easy-apply/someone-elses-campaign/p1")
    assert r.status_code == 404
    # The assist read is never even attempted for an unowned campaign id.
    assert ("assist", "someone-elses-campaign", "p1") not in FakeEngine.calls


def test_owned_campaign_round_trips_the_brief(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.assist_result[("c1", "p1")] = {
        "campaign_id": "c1",
        "posting_id": "p1",
        "title": "Staff Engineer",
        "company": "Acme",
        "deep_link": "https://example.test/jobs/acme",
        "checklist": ["Open the posting using the link below."],
        "consent_given_at": "2026-07-08T00:00:00+00:00",
    }
    r = client.get("/api/applicant/easy-apply/c1/p1")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Staff Engineer"
    assert body["deep_link"] == "https://example.test/jobs/acme"
    assert ("assist", "c1", "p1") in FakeEngine.calls


def test_engine_consent_gate_409_passes_through(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("assist", "c1", "p1")] = EngineError(
        "Accept the Easy Apply assisted-mode consent screen first.", status=409
    )
    r = client.get("/api/applicant/easy-apply/c1/p1")
    assert r.status_code == 409


def test_engine_unreachable_on_campaign_list_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("boom", status=None)
    r = client.get("/api/applicant/easy-apply/c1/p1")
    assert r.status_code == 503
