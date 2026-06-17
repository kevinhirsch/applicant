"""Hermetic tests for the Pending-Actions Portal proxy (CRIT-portal).

Mounts only ``routes/applicant_portal_routes.py`` on a bare FastAPI app with a
tiny middleware that authenticates the request (the real global auth gate lives
in ``app.py`` and is out of scope here). The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (covers the
  aggregation, soft-degrade, and resolve/acquire happy + error paths), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` proving
  the exact engine paths are hit and that a typed ``EngineError`` (e.g. a 409
  confirm gate) is forwarded with its status.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_portal_routes as mod
from routes.applicant_portal_routes import setup_applicant_portal_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


# --- test app with a stand-in auth middleware -------------------------------


def _make_app(authed: bool = True) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester" if authed else None
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app


# --- a scripted fake engine -------------------------------------------------


class FakeEngine:
    """Stands in for ApplicantEngineClient as an async context manager."""

    calls: list = []
    campaigns: list = []
    pending: dict = {}            # campaign_id -> engine pending payload
    raises: dict = {}             # key -> EngineError
    acquire_response: dict = {"saved": True}

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

    async def list_pending_actions(self, cid):
        FakeEngine.calls.append(("list_pending_actions", cid))
        if ("list_pending_actions", cid) in FakeEngine.raises:
            raise FakeEngine.raises[("list_pending_actions", cid)]
        return FakeEngine.pending.get(cid, {"campaign_id": cid, "count": 0, "items": []})

    async def resolve_pending_action(self, aid):
        FakeEngine.calls.append(("resolve_pending_action", aid))
        if ("resolve_pending_action", aid) in FakeEngine.raises:
            raise FakeEngine.raises[("resolve_pending_action", aid)]
        return None

    async def acquire_missing_attribute(self, payload):
        FakeEngine.calls.append(("acquire_missing_attribute", payload))
        if "acquire_missing_attribute" in FakeEngine.raises:
            raise FakeEngine.raises["acquire_missing_attribute"]
        return FakeEngine.acquire_response


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeEngine.calls = []
    FakeEngine.campaigns = []
    FakeEngine.pending = {}
    FakeEngine.raises = {}
    FakeEngine.acquire_response = {"saved": True}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth -------------------------------------------------------------------


def test_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(authed=False))
    # No current_user and the TestClient host ("testclient") is not loopback, so
    # require_user rejects — a middleware misconfig can't open the portal up.
    r = c.get("/api/applicant/portal/pending")
    assert r.status_code == 401


# --- aggregation ------------------------------------------------------------


def test_pending_aggregates_across_campaigns(client):
    FakeEngine.campaigns = [
        {"id": "c1", "name": "Backend"},
        {"id": "c2", "name": "Platform"},
    ]
    FakeEngine.pending = {
        "c1": {"items": [
            {"id": "a1", "kind": "material_review", "title": "Cover letter", "application_id": "app1"},
        ]},
        "c2": {"items": [
            {"id": "a2", "kind": "missing_attr", "title": "Need a detail", "payload": {"attribute_name": "phone"}},
            {"id": "a3", "kind": "agent_question", "title": "Which city?"},
        ]},
    }
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["count"] == 3
    ids = {it["id"] for it in body["items"]}
    assert ids == {"a1", "a2", "a3"}
    # Campaign context is attached per item.
    by_id = {it["id"]: it for it in body["items"]}
    assert by_id["a1"]["campaign_id"] == "c1"
    assert by_id["a1"]["campaign_name"] == "Backend"
    assert by_id["a2"]["campaign_name"] == "Platform"


def test_pending_soft_degrades_when_engine_down(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False, "count": 0, "items": []}


def test_pending_skips_a_single_failing_campaign(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]
    FakeEngine.pending = {"c1": {"items": [{"id": "a1", "kind": "error", "title": "snag"}]}}
    FakeEngine.raises[("list_pending_actions", "c2")] = EngineError("flaky")
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "a1"


def test_pending_empty_when_no_campaigns(client):
    FakeEngine.campaigns = []
    r = client.get("/api/applicant/portal/pending")
    assert r.status_code == 200
    assert r.json() == {"engine_available": True, "count": 0, "items": []}


# --- resolve ----------------------------------------------------------------


def test_resolve_action_ok(client):
    r = client.post("/api/applicant/portal/actions/a1/resolve")
    assert r.status_code == 200
    assert r.json() == {"resolved": True, "action_id": "a1"}
    assert ("resolve_pending_action", "a1") in FakeEngine.calls


def test_resolve_action_forwards_error(client):
    FakeEngine.raises[("resolve_pending_action", "missing")] = EngineError(
        "nope", status=404, detail="unknown"
    )
    r = client.post("/api/applicant/portal/actions/missing/resolve")
    assert r.status_code == 404
    assert r.json()["detail"] == "unknown"


def test_resolve_action_maps_unreachable_to_503(client):
    FakeEngine.raises[("resolve_pending_action", "a1")] = EngineError("conn refused")
    r = client.post("/api/applicant/portal/actions/a1/resolve")
    assert r.status_code == 503


# --- missing attribute ------------------------------------------------------


def test_missing_attribute_acquires_and_resolves(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "555-1212", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] is True
    assert body["campaign_id"] == "c1"
    # The acquire payload carried the resolved campaign + value.
    acquire = [c for c in FakeEngine.calls if isinstance(c, tuple) and c[0] == "acquire_missing_attribute"]
    assert acquire and acquire[0][1]["name"] == "phone"
    assert acquire[0][1]["value"] == "555-1212"
    assert ("resolve_pending_action", "a2") in FakeEngine.calls


def test_missing_attribute_resolves_campaign_when_omitted(client):
    FakeEngine.campaigns = [{"id": "auto1", "name": "First"}]
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x"},
    )
    assert r.status_code == 200
    assert r.json()["campaign_id"] == "auto1"


def test_missing_attribute_requires_name_and_value(client):
    assert client.post(
        "/api/applicant/portal/missing-attribute", json={"name": " ", "value": "x"}
    ).status_code == 400
    assert client.post(
        "/api/applicant/portal/missing-attribute", json={"name": "phone", "value": " "}
    ).status_code == 400


def test_missing_attribute_forwards_confirm_gate(client):
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    FakeEngine.raises["acquire_missing_attribute"] = EngineError(
        "confirm", status=409, detail="needs confirm"
    )
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "needs confirm"


def test_missing_attribute_409_when_no_campaign(client):
    FakeEngine.campaigns = []
    r = client.post(
        "/api/applicant/portal/missing-attribute", json={"name": "phone", "value": "x"}
    )
    assert r.status_code == 409


def test_missing_attribute_survives_resolve_failure(client):
    # The detail saved; only the row-clear failed → still 200, resolved=False.
    FakeEngine.campaigns = [{"id": "c1", "name": "A"}]
    FakeEngine.raises[("resolve_pending_action", "a2")] = EngineError("flaky", status=500)
    r = client.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    assert r.json()["resolved"] is False


# --- exact engine paths via a real client over MockTransport ----------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())
    return app, TransportEngine


def test_resolve_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(204)

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.post("/api/applicant/portal/actions/a9/resolve")
    assert r.status_code == 200
    assert seen["path"] == "/api/pending-actions/a9/resolve"
    assert seen["method"] == "POST"


def test_missing_attribute_hits_exact_engine_path(monkeypatch):
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.method, request.url.path))
        if request.url.path == "/api/attributes/acquire-missing":
            return httpx.Response(200, json={"saved": True})
        if request.url.path == "/api/pending-actions/a2/resolve":
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "unexpected"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)

    r = c.post(
        "/api/applicant/portal/missing-attribute",
        json={"name": "phone", "value": "x", "campaign_id": "c1", "action_id": "a2"},
    )
    assert r.status_code == 200
    assert ("POST", "/api/attributes/acquire-missing") in paths
    assert ("POST", "/api/pending-actions/a2/resolve") in paths
