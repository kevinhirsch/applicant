"""Hermetic tests for the crit-ops Debug/Activity ↔ engine proxy.

Mounts only ``routes/applicant_admin_routes.py`` on a bare FastAPI app with a tiny
middleware that sets the authenticated user + an ``auth_manager`` stub on app
state (the real global auth gate lives in ``app.py`` and is out of scope here).
The engine is faked two ways:

* a scripted ``FakeEngine`` patched in for ``ApplicantEngineClient`` (happy paths,
  soft-degrade on unreachable, and write error forwarding), and
* a real :class:`ApplicantEngineClient` over an ``httpx.MockTransport`` to prove
  the exact engine paths are hit.

Zero network either way.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_admin_routes as mod
from routes.applicant_admin_routes import setup_applicant_admin_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_app(*, user="alice", configured=True, admins=("alice",)) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_admin_routes())
    return app


class FakeEngine:
    available = True
    calls: list = []
    responses: dict = {}
    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def _maybe(self, key, *args, default=None):
        FakeEngine.calls.append((key, *args))
        if key in FakeEngine.raises:
            raise FakeEngine.raises[key]
        return FakeEngine.responses.get(key, default)

    async def engine_available(self):
        FakeEngine.calls.append(("engine_available",))
        return FakeEngine.available

    async def admin_application_history(self, cid, limit=200):
        return await self._maybe("history", cid, default={"campaign_id": cid, "applications": []})

    async def admin_application_outcomes(self, aid):
        return await self._maybe("outcomes", aid, default={"application_id": aid, "outcomes": []})

    async def admin_detections(self, cid):
        return await self._maybe("detections", cid, default={"campaign_id": cid, "detections": []})

    async def admin_workflow_state(self, aid):
        return await self._maybe("workflow", aid, default={"application_id": aid, "steps": []})

    async def admin_screenshots(self, aid):
        return await self._maybe("screenshots", aid, default={"application_id": aid, "screenshots": []})

    async def admin_logs(self, limit=100):
        return await self._maybe("logs", default={"entries": []})

    async def admin_variants(self, cid):
        return await self._maybe("variants", cid, default={"campaign_id": cid, "variants": []})

    async def admin_learning(self, cid):
        return await self._maybe(
            "learning",
            cid,
            default={"campaign_id": cid, "summary": {}, "sources": [], "converting_roles": []},
        )

    async def admin_stealth(self):
        return await self._maybe("stealth", default={})

    async def admin_workspace_bridge(self):
        return await self._maybe(
            "workspace_bridge", default={"configured": False, "reachable": False}
        )

    async def outcome_log(self, aid):
        return await self._maybe("log", aid, default={"application_id": aid})

    async def outcome_mark_submitted(self, aid, body=None):
        return await self._maybe("mark", aid, default={"outcome_id": "o1", "type": "submitted"})

    async def outcome_detect(self, aid):
        return await self._maybe("detect", aid, default={"detected": True})

    async def list_campaigns(self):
        return await self._maybe("list_campaigns", default=[])

    async def audit_log_application_export(self, aid):
        return await self._maybe("audit_export", aid, default=None)


@pytest.fixture(autouse=True)
def _reset():
    FakeEngine.available = True
    FakeEngine.calls = []
    FakeEngine.responses = {}
    FakeEngine.raises = {}
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    return TestClient(_make_app())


# --- auth / scoping ---------------------------------------------------------


def test_non_admin_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/logs").status_code == 403


def test_single_user_mode_allows_lone_owner(monkeypatch):
    # Unconfigured auth manager -> no admin distinction; the lone owner is allowed
    # from the box itself. Single-user mode means the operator on localhost, so the
    # caller is loopback (the remote-refusal hardening for #228 is asserted by the
    # BDD acceptance spec / test_single_user_mode_refuses_remote below).
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("127.0.0.1", 51000))
    assert c.get("/api/applicant/admin/logs").status_code == 200


def test_single_user_mode_refuses_remote(monkeypatch):
    # #228: an unconfigured + unauthenticated caller from a remote address must NOT
    # pass the operator-grade admin gate during setup.
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("203.0.113.9", 40000))
    assert c.get("/api/applicant/admin/logs").status_code == 401


def test_configured_unauthenticated_is_rejected(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/logs").status_code == 401


# --- read surfaces ----------------------------------------------------------


def test_history_passthrough(client):
    FakeEngine.responses["history"] = {
        "campaign_id": "c1",
        "applications": [{"id": "a1", "role": "SWE", "status": "submitted", "screenshot_count": 3}],
    }
    r = client.get("/api/applicant/admin/history/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["applications"][0]["role"] == "SWE"


def test_history_soft_degrades_when_engine_down(client):
    FakeEngine.raises["history"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/admin/history/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["applications"] == []


def test_logs_soft_degrades(client):
    FakeEngine.raises["logs"] = EngineError("down")
    r = client.get("/api/applicant/admin/logs")
    assert r.status_code == 200
    assert r.json() == {"entries": [], "engine_available": False}


def test_variants_passthrough(client):
    FakeEngine.responses["variants"] = {"campaign_id": "c1", "variants": [{"id": "v1", "score": 0.9}]}
    r = client.get("/api/applicant/admin/variants/c1")
    assert r.status_code == 200
    assert r.json()["variants"][0]["id"] == "v1"


def test_learning_passthrough(client):
    FakeEngine.responses["learning"] = {
        "campaign_id": "c1",
        "summary": {"total_matched": 24, "total_approved": 4, "total_submitted": 2, "sources_seen": 2},
        "sources": [
            {"source": "high", "matched": 4, "approved": 2, "submitted": 2, "conversion_rate": 50.0},
            {"source": "low", "matched": 20, "approved": 0, "submitted": 0, "conversion_rate": None},
        ],
        "converting_roles": ["Senior Backend Engineer"],
        "exploration_budget": 0.25,
    }
    r = client.get("/api/applicant/admin/learning/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["summary"]["total_matched"] == 24
    assert body["sources"][0]["source"] == "high"
    assert body["converting_roles"] == ["Senior Backend Engineer"]


def test_learning_soft_degrades_when_engine_down(client):
    FakeEngine.raises["learning"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/admin/learning/c1")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["sources"] == []
    assert body["converting_roles"] == []


def test_learning_requires_admin(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/learning/c1").status_code == 403


# --- workspace bridge health (dark-engine audit #71) ------------------------


def test_workspace_bridge_passthrough_when_configured_and_reachable(client):
    FakeEngine.responses["workspace_bridge"] = {"configured": True, "reachable": True, "detail": None}
    r = client.get("/api/applicant/admin/workspace-bridge")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["configured"] is True
    assert body["reachable"] is True


def test_workspace_bridge_reports_not_configured(client):
    FakeEngine.responses["workspace_bridge"] = {
        "configured": False, "reachable": False, "detail": None,
    }
    body = client.get("/api/applicant/admin/workspace-bridge").json()
    assert body["configured"] is False
    assert body["reachable"] is False


def test_workspace_bridge_soft_degrades_when_engine_down(client):
    FakeEngine.raises["workspace_bridge"] = EngineError("down", is_timeout=True)
    r = client.get("/api/applicant/admin/workspace-bridge")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is False
    assert body["configured"] is False
    assert body["reachable"] is False


def test_workspace_bridge_requires_admin(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/workspace-bridge").status_code == 403


def test_workflow_and_screenshots_and_outcomes(client):
    assert client.get("/api/applicant/admin/workflow/a1").status_code == 200
    assert client.get("/api/applicant/admin/screenshots/a1").status_code == 200
    assert client.get("/api/applicant/admin/outcomes/a1").status_code == 200


def test_status_probe(client):
    FakeEngine.available = False
    r = client.get("/api/applicant/admin/status")
    assert r.status_code == 200
    assert r.json() == {"engine_available": False}


# --- writes: mark-submitted / detect ---------------------------------------


def test_mark_submitted_passthrough(client):
    FakeEngine.responses["mark"] = {"outcome_id": "o9", "type": "submitted", "source": "user"}
    r = client.post("/api/applicant/admin/applications/a1/mark-submitted", json={})
    assert r.status_code == 200
    assert r.json()["outcome_id"] == "o9"
    assert ("mark", "a1") in FakeEngine.calls


def test_mark_submitted_forwards_409_review_gate(client):
    FakeEngine.raises["mark"] = EngineError("nope", status=409, detail="review required")
    r = client.post("/api/applicant/admin/applications/a1/mark-submitted", json={})
    assert r.status_code == 409
    assert r.json()["detail"] == "review required"


def test_mark_submitted_maps_unreachable_to_503(client):
    FakeEngine.raises["mark"] = EngineError("conn refused")  # no status -> transport failure
    r = client.post("/api/applicant/admin/applications/a1/mark-submitted", json={})
    assert r.status_code == 503


def test_detect_passthrough(client):
    FakeEngine.responses["detect"] = {"detected": True, "outcome_id": "o2"}
    r = client.post("/api/applicant/admin/applications/a1/detect")
    assert r.status_code == 200
    assert r.json()["detected"] is True


# --- exact engine paths over a real client + MockTransport ------------------


def _mock_transport_app(handler):
    class TransportEngine(ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = _make_app()
    return app, TransportEngine


def test_history_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"campaign_id": "c1", "applications": []})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/admin/history/c1?limit=50")
    assert r.status_code == 200
    assert seen["path"] == "/api/admin/history/c1"
    assert seen["query"]["limit"] == "50"


def test_learning_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"campaign_id": "c1", "summary": {}, "sources": []})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/admin/learning/c1")
    assert r.status_code == 200
    assert seen["path"] == "/api/admin/learning/c1"


def test_mark_submitted_hits_exact_engine_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(201, json={"outcome_id": "o1", "type": "submitted", "source": "user"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/admin/applications/app1/mark-submitted", json={"attributes_used": {"a": 1}})
    assert r.status_code == 200
    assert seen["path"] == "/api/outcomes/applications/app1/mark-submitted"
    assert seen["method"] == "POST"


# --- tool registry (FR-UI-4): list + toggle --------------------------------


def test_list_tools_passthrough_and_exact_path(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"tools": [
            {"key": "web_search", "label": "Web search", "enabled": True},
            {"key": "bash", "label": "Shell", "enabled": False},
        ]})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/admin/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert seen["path"] == "/api/admin/tools"
    assert {t["key"] for t in body["tools"]} == {"web_search", "bash"}


def test_list_tools_soft_degrades_when_engine_down(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.get("/api/applicant/admin/tools")
    assert r.status_code == 200
    assert r.json() == {"tools": [], "engine_available": False}


def test_toggle_tool_hits_exact_path_with_enabled_param(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"key": "bash", "enabled": True})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/admin/tools/bash", json={"enabled": True})
    assert r.status_code == 200
    assert seen["path"] == "/api/admin/tools/bash"
    assert seen["method"] == "POST"
    assert seen["query"]["enabled"] == "true"
    assert r.json()["enabled"] is True


def test_toggle_unknown_tool_forwards_404(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Unknown tool 'nope'"})

    app, engine_cls = _mock_transport_app(handler)
    monkeypatch.setattr(mod, "ApplicantEngineClient", engine_cls)
    c = TestClient(app)
    r = c.post("/api/applicant/admin/tools/nope", json={"enabled": False})
    assert r.status_code == 404


def test_tools_require_admin(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    assert c.get("/api/applicant/admin/tools").status_code == 403


# --- owner-reachable lane (dark-engine audit B4 items 29/30/32) -------------
#
# Unlike everything above, these routes must be reachable by a NON-admin
# authenticated user -- that's the whole point (durable-workflow state, an
# application's own audit export, and recent logs are the owner's OWN data,
# not operator-grade detail). Each owner-scoped read/download is validated
# against a caller-supplied application_id: it must turn up in THIS
# request's own campaign -> application-history fan-out first.


def test_owner_workflow_status_passthrough_when_owned(client):
    FakeEngine.responses["list_campaigns"] = [{"id": "c1", "name": "Backend"}]
    FakeEngine.responses["history"] = {
        "campaign_id": "c1",
        "applications": [{"application_id": "a1", "status": "APPLIED"}],
    }
    FakeEngine.responses["workflow"] = {
        "application_id": "a1",
        "steps": ["fill", "review", "submit"],
        "pending_recovery": False,
    }
    r = client.get("/api/applicant/admin/applications/a1/workflow-status")
    assert r.status_code == 200
    body = r.json()
    assert body["engine_available"] is True
    assert body["steps"] == ["fill", "review", "submit"]


def test_owner_workflow_status_allows_non_admin_user(monkeypatch):
    """MANDATORY per item 29: a non-admin owner must reach this, unlike the
    admin-gated ``/workflow/{id}`` route above (see test_workflow_and_
    screenshots_and_outcomes / test_non_admin_is_rejected)."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    r = c.get("/api/applicant/admin/applications/a1/workflow-status")
    assert r.status_code == 200


def test_owner_workflow_status_not_owned_is_404_not_proxied(client):
    """MANDATORY owner-isolation test: a caller must never read workflow state
    for an application that never turned up in their own campaign fan-out."""
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    r = client.get("/api/applicant/admin/applications/a-evil/workflow-status")
    assert r.status_code == 404
    assert all(not (isinstance(call, tuple) and call[0] == "workflow") for call in FakeEngine.calls)


def test_owner_workflow_status_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.get("/api/applicant/admin/applications/a1/workflow-status")
    assert r.status_code == 503


def test_owner_workflow_status_requires_authentication(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("alice",)))
    r = c.get("/api/applicant/admin/applications/a1/workflow-status")
    assert r.status_code == 401


def test_owner_export_application_audit_log_passthrough(client):
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    FakeEngine.responses["audit_export"] = httpx.Response(
        200,
        json={"exported_at": "2026-07-05T00:00:00Z", "count": 1, "events": []},
        headers={"Content-Disposition": "attachment; filename=audit-log.json"},
    )
    r = client.get("/api/applicant/admin/applications/a1/audit-export.json")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "audit-log-a1.json" in cd
    assert r.json()["count"] == 1


def test_owner_export_application_audit_log_allows_non_admin_user(monkeypatch):
    """MANDATORY per item 30: reachable without an admin account, unlike
    ``/audit-log/application/{id}/export.json`` (see test_applicant_audit_
    routes.py's ``test_audit_export_requires_admin``)."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    FakeEngine.responses["audit_export"] = httpx.Response(
        200, json={"exported_at": "x", "count": 0, "events": []},
    )
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    r = c.get("/api/applicant/admin/applications/a1/audit-export.json")
    assert r.status_code == 200


def test_owner_export_application_audit_log_not_owned_is_404_not_proxied(client):
    """MANDATORY owner-isolation test: a caller must never download the audit
    trail for an application that never turned up in their own fan-out."""
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    r = client.get("/api/applicant/admin/applications/a-evil/audit-export.json")
    assert r.status_code == 404
    assert all(not (isinstance(call, tuple) and call[0] == "audit_export") for call in FakeEngine.calls)


def test_owner_export_application_audit_log_engine_down_is_503(client):
    FakeEngine.raises["list_campaigns"] = EngineError("down")
    r = client.get("/api/applicant/admin/applications/a1/audit-export.json")
    assert r.status_code == 503


def test_owner_export_application_audit_log_error_is_forwarded(client):
    FakeEngine.responses["list_campaigns"] = [{"id": "c1"}]
    FakeEngine.responses["history"] = {"applications": [{"application_id": "a1"}]}
    FakeEngine.raises["audit_export"] = EngineError("nope", status=404, detail="No such application.")
    r = client.get("/api/applicant/admin/applications/a1/audit-export.json")
    assert r.status_code == 404


def test_owner_logs_allows_non_admin_user(monkeypatch):
    """Item 32: recent redacted logs, reachable without an admin account
    (unlike ``/logs`` above, see test_non_admin_is_rejected)."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    FakeEngine.responses["logs"] = {"entries": [{"level": "info", "message": "tick"}]}
    c = TestClient(_make_app(user="bob", configured=True, admins=("alice",)))
    r = c.get("/api/applicant/admin/logs/mine")
    assert r.status_code == 200
    assert r.json()["entries"][0]["message"] == "tick"


def test_owner_logs_soft_degrades_when_engine_down(client):
    FakeEngine.raises["logs"] = EngineError("down")
    r = client.get("/api/applicant/admin/logs/mine")
    assert r.status_code == 200
    assert r.json() == {"entries": [], "engine_available": False}


def test_owner_logs_requires_authentication(monkeypatch):
    monkeypatch.setattr(mod, "ApplicantEngineClient", FakeEngine)
    c = TestClient(_make_app(user=None, configured=True, admins=("alice",)))
    r = c.get("/api/applicant/admin/logs/mine")
    assert r.status_code == 401
