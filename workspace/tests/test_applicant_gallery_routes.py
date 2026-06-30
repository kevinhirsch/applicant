"""Hermetic tests for the Gallery proxy (#296, surfacing-only).

Mounts only ``routes/applicant_gallery_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives in
``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  campaign resolution, owner-scoping, the proxied collection shapes, and the
  soft-degrade paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine path (``/api/gallery/{cid}``) is hit.

Zero network either way. Mirrors test_applicant_activity_routes.py /
test_applicant_email_routes.py.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_gallery_routes as mod
from routes.applicant_gallery_routes import setup_applicant_gallery_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_gallery_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    galleries: dict = {}   # campaign_id -> engine gallery payload
    raises: dict = {}      # key -> EngineError

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

    async def gallery(self, cid):
        FakeEngine.calls.append(("gallery", cid))
        if ("gallery", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("gallery", cid)]
        return FakeEngine.galleries.get(cid, {})


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.galleries = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


_SEEDED = {
    "screenshots": {
        "count": 1,
        "items": [{"id": "s1", "application_id": "a1", "page_ref": "p1.png", "page_url": "https://x/apply"}],
    },
    "materials": {
        "count": 1,
        "items": [{"id": "d1", "application_id": "a1", "type": "cover_letter",
                   "storage_path": "artifacts/d1.pdf", "approved": True, "content": "Dear team"}],
    },
}


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    for path in ("", "/campaigns", "/c1"):
        r = c.get(f"/api/applicant/gallery{path}")
        assert r.status_code == 401, path


# --- campaign chooser -------------------------------------------------------


def test_campaigns_lists_owner_campaigns(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}, {"id": "c2", "name": "Platform"}]
    r = client.get("/api/applicant/gallery/campaigns")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert [c["id"] for c in body["campaigns"]] == ["c1", "c2"]


def test_campaigns_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/gallery/campaigns")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "campaigns": []}


# --- default (first campaign) gallery ---------------------------------------


def test_default_proxies_first_campaign_real_fields(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}, {"id": "c2", "name": "Platform"}]
    FakeEngine.galleries = {"c1": _SEEDED}
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_gallery"] is True
    assert body["campaign_id"] == "c1"
    assert body["campaign_name"] == "Backend"
    # REAL screenshot fields pass straight through.
    shot = body["screenshots"]["items"][0]
    assert shot["page_ref"] == "p1.png"
    assert shot["page_url"] == "https://x/apply"
    # REAL material fields pass straight through.
    mat = body["materials"]["items"][0]
    assert mat["type"] == "cover_letter"
    assert mat["storage_path"] == "artifacts/d1.pdf"
    assert mat["approved"] is True
    assert mat["content"] == "Dear team"
    # Only the first campaign's gallery is fetched.
    assert ("gallery", "c1") in FakeEngine.calls
    assert ("gallery", "c2") not in FakeEngine.calls


def test_default_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["has_gallery"] is False
    assert body["screenshots"] == {"count": 0, "items": []}
    assert body["materials"] == {"count": 0, "items": []}


def test_default_no_gallery_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["has_gallery"] is False


def test_default_no_gallery_when_fetch_errors(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("gallery", "c1")] = EngineError("boom", status=500)
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    assert r.json()["has_gallery"] is False


# --- specific campaign (owner-scoped) ---------------------------------------


def test_specific_campaign_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}, {"id": "c2", "name": "Platform"}]
    FakeEngine.galleries = {"c2": _SEEDED}
    r = client.get("/api/applicant/gallery/c2")
    assert r.status_code == 200
    body = r.json()
    assert body["campaign_id"] == "c2"
    assert body["has_gallery"] is True
    assert ("gallery", "c2") in FakeEngine.calls


def test_specific_campaign_not_owned_returns_empty_not_proxied(client):
    """A campaign id the owner does not have is NOT proxied (owner-scoping)."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.get("/api/applicant/gallery/c-evil")
    assert r.status_code == 200
    body = r.json()
    assert body["has_gallery"] is False
    assert body["screenshots"] == {"count": 0, "items": []}
    # The engine gallery read was never made for the non-owned campaign.
    assert ("gallery", "c-evil") not in FakeEngine.calls


# --- real client over MockTransport: exact engine path ----------------------


def test_engine_path_is_hit_over_real_client(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append(request.url.path)
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Backend"}])
        if request.url.path == "/api/gallery/c1":
            return httpx.Response(200, json=_SEEDED)
        return httpx.Response(404, json={"detail": "nope"})

    def _factory(*a, **k):
        return ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "ApplicantEngineClient", _factory)
    c = TestClient(_make_app())
    r = c.get("/api/applicant/gallery")
    assert r.status_code == 200
    assert r.json()["has_gallery"] is True
    assert "/api/campaigns" in captured["paths"]
    assert "/api/gallery/c1" in captured["paths"]


# --- HONESTY: a 409 setup gate is NOT offline (mirrors #544) -----------------
#
# The gallery's own _owner_campaigns previously mapped ANY EngineError → None →
# engine_available:false, so a 409 setup gate dishonestly read as "engine
# offline" here too. It now routes failures through the shared soft_degrade()
# classifier, so a GATE surfaces gated:true + the engine's message
# (engine_available:true) while a transport failure (status None) stays offline.

_GAL_GATE_MSG = (
    "Automated work is blocked until onboarding is complete and the LLM + "
    "notification channels are configured."
)


def test_default_409_gate_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("gated", status=409, detail=_GAL_GATE_MSG)
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GAL_GATE_MSG
    assert body["has_gallery"] is False
    # still a well-formed, renderable empty body
    assert body["screenshots"] == {"count": 0, "items": []}
    assert body["materials"] == {"count": 0, "items": []}


def test_default_transport_error_is_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", status=None)
    r = client.get("/api/applicant/gallery")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body.get("gated") is not True
    assert body["has_gallery"] is False


def test_campaigns_409_gate_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("gated", status=409, detail=_GAL_GATE_MSG)
    r = client.get("/api/applicant/gallery/campaigns")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["message"] == _GAL_GATE_MSG
    assert body["campaigns"] == []


def test_specific_campaign_409_gate_is_not_offline(client):
    FakeEngine.raises["list_campaigns"] = EngineError("gated", status=409, detail=_GAL_GATE_MSG)
    r = client.get("/api/applicant/gallery/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is True
    assert body["engine_available"] is True
    assert body["has_gallery"] is False
