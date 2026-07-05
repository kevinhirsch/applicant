"""Hermetic tests for the campaign/discovery-source settings proxy (#301).

Mounts only ``routes/applicant_campaigns_routes.py`` on a bare FastAPI app with a
tiny auth middleware (the real global auth gate lives in ``app.py`` and is out of
scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  config read, owner-scoped update/toggle, and the soft-degrade paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving the
  exact engine paths (``/api/campaigns``, ``PATCH /api/campaigns/{id}``,
  ``/api/discovery-sources/{id}``) are hit.

Zero network either way. Mirrors test_applicant_gallery_routes.py.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_campaigns_routes as mod
from routes.applicant_campaigns_routes import setup_applicant_campaigns_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_campaigns_routes())
    return app


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    sources: dict = {}     # campaign_id -> {"items": [...]}
    updated: dict = {}     # campaign_id -> dict returned by update
    audit_exports: dict = {}  # campaign_id -> httpx.Response
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

    async def update_campaign(self, cid, body):
        FakeEngine.calls.append(("update", cid, body))
        if ("update", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("update", cid)]
        return FakeEngine.updated.get(cid, {"id": cid, **body})

    async def list_discovery_sources(self, cid):
        FakeEngine.calls.append(("sources", cid))
        if ("sources", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("sources", cid)]
        return FakeEngine.sources.get(cid, {"items": []})

    async def toggle_discovery_source(self, cid, key, enabled):
        FakeEngine.calls.append(("toggle", cid, key, enabled))
        if ("toggle", cid, key) in FakeEngine.raises:
            raise FakeEngine.raises[("toggle", cid, key)]
        return {"campaign_id": cid, "source_key": key, "enabled": enabled}

    async def audit_log_campaign_export(self, cid):
        FakeEngine.calls.append(("audit_export", cid))
        if ("audit_export", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("audit_export", cid)]
        return FakeEngine.audit_exports.get(cid) or httpx.Response(
            200, json={"exported_at": "x", "count": 0, "events": []}
        )


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.sources = {}
    FakeEngine.updated = {}
    FakeEngine.audit_exports = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    assert c.get("/api/applicant/campaigns").status_code == 401
    assert c.patch("/api/applicant/campaigns/c1", json={"name": "x"}).status_code == 401
    assert c.get("/api/applicant/campaigns/c1/sources").status_code == 401


# --- list config ------------------------------------------------------------


def test_list_returns_config(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend", "run_mode": "continuous", "throughput_target": 15,
         "exploration_budget": 0.1, "active": True}
    ]
    body = client.get("/api/applicant/campaigns").json()
    assert body["engine_available"] is True
    assert body["campaigns"][0]["throughput_target"] == 15


def test_list_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    assert client.get("/api/applicant/campaigns").json() == {
        "engine_available": False, "campaigns": []
    }


# --- update (owner-scoped) --------------------------------------------------


def test_patch_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.patch("/api/applicant/campaigns/c1", json={"name": "Platform"})
    assert r.status_code == 200
    assert r.json()["name"] == "Platform"
    assert ("update", "c1", {"name": "Platform"}) in FakeEngine.calls


def test_patch_not_owned_is_404_not_proxied(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.patch("/api/applicant/campaigns/c-evil", json={"name": "hijack"})
    assert r.status_code == 404
    assert all(not (isinstance(c, tuple) and c[0] == "update") for c in FakeEngine.calls)


def test_patch_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    assert client.patch("/api/applicant/campaigns/c1", json={"name": "x"}).status_code == 503


# --- discovery sources (owner-scoped) ---------------------------------------


def test_sources_proxied_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.sources = {"c1": {"items": [
        {"source_key": "jobspy:indeed", "enabled": True, "yield_stats": {"postings": 45, "conversions": 3}}
    ]}}
    body = client.get("/api/applicant/campaigns/c1/sources").json()
    assert body["engine_available"] is True
    assert body["items"][0]["source_key"] == "jobspy:indeed"
    assert body["items"][0]["yield_stats"]["conversions"] == 3


def test_sources_not_owned_returns_empty_not_proxied(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    body = client.get("/api/applicant/campaigns/c-evil/sources").json()
    assert body["items"] == []
    assert ("sources", "c-evil") not in FakeEngine.calls


def test_toggle_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.put("/api/applicant/campaigns/c1/sources/jobspy:indeed", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert ("toggle", "c1", "jobspy:indeed", False) in FakeEngine.calls


def test_toggle_not_owned_is_404(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.put("/api/applicant/campaigns/c-evil/sources/x", json={"enabled": True})
    assert r.status_code == 404


# --- campaign audit-log export (owner-scoped, dark-engine audit item 31) ---
#
# ``GET /api/admin/audit-log/{campaign_id}/export.json`` already exists on the
# engine and was already proxied -- but only behind an admin account
# (``applicant_admin_routes.py``). These pin the NEW owner-scoped lane in
# THIS file: any authenticated owner can download the ordered action trail
# for one of their OWN campaigns, id-validated the same way ``update_campaign``
# / ``delete_campaign`` are above.


def test_export_proxies_when_owned(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.audit_exports["c1"] = httpx.Response(
        200,
        json={"exported_at": "2026-07-05T00:00:00Z", "count": 3, "events": []},
        headers={"Content-Disposition": "attachment; filename=audit-log.json"},
    )
    r = client.get("/api/applicant/campaigns/c1/audit-log/export.json")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "audit-log-c1.json" in cd
    assert r.json()["count"] == 3
    assert ("audit_export", "c1") in FakeEngine.calls


def test_export_not_owned_is_404_not_proxied(client):
    """MANDATORY owner-isolation test: a caller must never download the
    action trail for a campaign that isn't in their own campaign list --
    mirrors test_patch_not_owned_is_404_not_proxied / test_delete_not_owned_
    is_404_not_proxied for this exact proxy file."""
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    r = client.get("/api/applicant/campaigns/c-evil/audit-log/export.json")
    assert r.status_code == 404
    assert all(not (isinstance(c, tuple) and c[0] == "audit_export") for c in FakeEngine.calls)


def test_export_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.get("/api/applicant/campaigns/c1/audit-log/export.json")
    assert r.status_code == 503


def test_export_engine_error_is_forwarded(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "Backend"}]
    FakeEngine.raises[("audit_export", "c1")] = EngineError(
        "nope", status=404, detail="No such campaign."
    )
    r = client.get("/api/applicant/campaigns/c1/audit-log/export.json")
    assert r.status_code == 404


def test_export_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    r = c.get("/api/applicant/campaigns/c1/audit-log/export.json")
    assert r.status_code == 401


def test_engine_export_path_hit_over_real_client(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Backend"}])
        if request.url.path == "/api/admin/audit-log/c1/export.json":
            return httpx.Response(
                200, json={"exported_at": "x", "count": 1, "events": []}
            )
        return httpx.Response(404, json={"detail": "nope"})

    def _factory(*a, **k):
        return ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "ApplicantEngineClient", _factory)
    c = TestClient(_make_app())
    r = c.get("/api/applicant/campaigns/c1/audit-log/export.json")
    assert r.status_code == 200
    assert ("GET", "/api/admin/audit-log/c1/export.json") in captured["paths"]


# --- real client over MockTransport: exact engine paths ---------------------


def test_engine_paths_hit_over_real_client(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("paths", []).append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Backend"}])
        if request.url.path == "/api/campaigns/c1" and request.method == "PATCH":
            return httpx.Response(200, json={"id": "c1", "name": "Platform"})
        return httpx.Response(404, json={"detail": "nope"})

    def _factory(*a, **k):
        return ApplicantEngineClient(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "ApplicantEngineClient", _factory)
    c = TestClient(_make_app())
    r = c.patch("/api/applicant/campaigns/c1", json={"name": "Platform"})
    assert r.status_code == 200
    assert r.json()["name"] == "Platform"
    assert ("GET", "/api/campaigns") in captured["paths"]
    assert ("PATCH", "/api/campaigns/c1") in captured["paths"]
