"""Hermetic tests for the Applicant LIVE-SESSION proxy (applicant_remote_routes.py).

Zero network: the engine client is replaced with a fake async-context-manager so
every route is exercised without an engine. Covers happy-path JSON pass-through,
that the terminal controls map to the engine's EXPLICIT authorize endpoints (the
stop-boundary path), typed-error translation, and the auth + privilege gates.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_remote_routes as remote_routes
from routes.applicant_remote_routes import setup_applicant_remote_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    last_call = None  # class-level so the test can read it after the request

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _dispatch(self, name, *args):
        type(self).last_call = (name, args)
        if self._error is not None:
            raise self._error
        return self._result

    async def list_remote_sessions(self):
        return await self._dispatch("list_remote_sessions")

    async def open_remote_session(self, application_id):
        return await self._dispatch("open_remote_session", application_id)

    async def remote_session_view_url(self, session_id):
        return await self._dispatch("remote_session_view_url", session_id)

    async def takeover_remote_session(self, session_id):
        return await self._dispatch("takeover_remote_session", session_id)

    async def request_final_approval(self, application_id):
        return await self._dispatch("request_final_approval", application_id)

    async def submit_self(self, application_id):
        return await self._dispatch("submit_self", application_id)

    async def authorize_engine_finish(self, application_id):
        return await self._dispatch("authorize_engine_finish", application_id)

    async def resume_account_step(self, application_id):
        return await self._dispatch("resume_account_step", application_id)

    async def resume_detection_step(self, application_id):
        return await self._dispatch("resume_detection_step", application_id)

    async def continue_two_factor(self, application_id):
        return await self._dispatch("continue_two_factor", application_id)

    async def stealth_caveat(self):
        return await self._dispatch("stealth_caveat")

    async def desktop_assist_health(self):
        return await self._dispatch("desktop_assist_health")

    async def desktop_assist_state(self, session_id):
        return await self._dispatch("desktop_assist_state", session_id)

    async def desktop_assist_enable(self, session_id):
        return await self._dispatch("desktop_assist_enable", session_id)

    async def desktop_assist_disable(self, session_id):
        return await self._dispatch("desktop_assist_disable", session_id)

    async def desktop_assist_action(self, session_id, body):
        return await self._dispatch("desktop_assist_action", session_id, body)


def _make_client(*, authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_remote_routes())
    return TestClient(app, raise_server_exceptions=True)


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        remote_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(result=result, error=error),
    )


# ── happy path ────────────────────────────────────────────────────────────


def test_list_sessions_passes_through(monkeypatch):
    payload = {"sessions": [{"session_id": "sbx-1", "application_id": "app-1"}], "count": 1}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/remote/sessions")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("list_remote_sessions", ())


def test_open_session_forwards_application_id(monkeypatch):
    _patch_engine(monkeypatch, result={"session_id": "sbx-2", "view_url": "https://x/y"})
    resp = _make_client().post(
        "/api/applicant/remote/sessions", json={"application_id": "app-9"}
    )
    assert resp.status_code == 201
    assert _FakeEngine.last_call == ("open_remote_session", ("app-9",))


def test_view_url_forwards_session_id(monkeypatch):
    _patch_engine(monkeypatch, result={"session_id": "sbx-3", "view_url": "https://v"})
    resp = _make_client().get("/api/applicant/remote/sessions/sbx-3/view-url")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("remote_session_view_url", ("sbx-3",))


def test_takeover(monkeypatch):
    _patch_engine(monkeypatch, result=None)  # engine returns 204 -> None
    resp = _make_client().post("/api/applicant/remote/sessions/sbx-4/takeover")
    assert resp.status_code == 200
    assert resp.json()["takeover"] == "granted"
    assert _FakeEngine.last_call == ("takeover_remote_session", ("sbx-4",))


def test_resume_account_and_detection(monkeypatch):
    _patch_engine(monkeypatch, result={"state": "prefilling"})
    client = _make_client()
    assert client.post(
        "/api/applicant/remote/applications/app-1/resume-account-step"
    ).status_code == 200
    assert _FakeEngine.last_call == ("resume_account_step", ("app-1",))
    assert client.post(
        "/api/applicant/remote/applications/app-1/resume-detection-step"
    ).status_code == 200
    assert _FakeEngine.last_call == ("resume_detection_step", ("app-1",))


def test_continue_two_factor_forwards_application_id(monkeypatch):
    _patch_engine(monkeypatch, result={"state": "prefilling"})
    resp = _make_client().post(
        "/api/applicant/remote/applications/app-1/continue-two-factor"
    )
    assert resp.status_code == 200
    assert resp.json() == {"state": "prefilling"}
    assert _FakeEngine.last_call == ("continue_two_factor", ("app-1",))


def test_caveat_passes_through(monkeypatch):
    _patch_engine(monkeypatch, result={"caveat": "best-effort", "egress_caveat": "e"})
    resp = _make_client().get("/api/applicant/remote/caveat")
    assert resp.status_code == 200
    assert resp.json()["caveat"] == "best-effort"
    assert _FakeEngine.last_call == ("stealth_caveat", ())


# ── the stop-boundary controls map to the EXPLICIT authorize endpoints ──────


def test_submit_self_maps_to_submit_self_endpoint(monkeypatch):
    _patch_engine(monkeypatch, result={"result": "submitted_by_user"})
    resp = _make_client().post("/api/applicant/remote/applications/app-5/submit-self")
    assert resp.status_code == 201
    # SECURITY: the user's own-submit decision routes to the engine's submit-self.
    assert _FakeEngine.last_call == ("submit_self", ("app-5",))


def test_authorize_engine_finish_maps_to_authorize_endpoint(monkeypatch):
    _patch_engine(monkeypatch, result={"result": "finished_by_engine"})
    resp = _make_client().post(
        "/api/applicant/remote/applications/app-6/authorize-engine-finish"
    )
    assert resp.status_code == 201
    # SECURITY: authorizing the engine to finish must hit the EXPLICIT authorize
    # endpoint (which routes the click through the core stop-boundary). No other
    # method may be substituted, or the engine could "finish" un-authorized.
    assert _FakeEngine.last_call == ("authorize_engine_finish", ("app-6",))


def test_authorize_boundary_403_passes_through(monkeypatch):
    """If the engine boundary refuses (403), the UI sees a 403 — never bypassed."""
    err = EngineError("boundary", status=403, detail="engine_submit not authorized")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/remote/applications/app-6/authorize-engine-finish"
    )
    assert resp.status_code == 403
    assert resp.json()["engine_status"] == 403


def test_request_final_approval(monkeypatch):
    _patch_engine(monkeypatch, result={"gate": "awaiting"})
    resp = _make_client().post(
        "/api/applicant/remote/applications/app-7/request-final-approval"
    )
    assert resp.status_code == 202
    assert _FakeEngine.last_call == ("request_final_approval", ("app-7",))


# ── error translation ───────────────────────────────────────────────────────


def test_timeout_becomes_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("timed out", is_timeout=True))
    resp = _make_client().get("/api/applicant/remote/sessions")
    assert resp.status_code == 502
    assert resp.json()["engine_status"] is None


def test_review_required_409_passes_through(monkeypatch):
    err = EngineError("review required", status=409, detail="approve docs first")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post("/api/applicant/remote/applications/app-8/submit-self")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "approve docs first"


# ── auth + privilege gates ───────────────────────────────────────────────────


def test_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(remote_routes, "ApplicantEngineClient", _boom)
    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_remote_routes())
    client = TestClient(app)
    assert client.get("/api/applicant/remote/sessions").status_code == 401


class _PrivAuthManager:
    is_configured = True

    def __init__(self, privileges):
        self._privs = privileges

    def get_privileges(self, _user):
        return dict(self._privs)


def _make_priv_client(privileges, *, user="restricted"):
    app = FastAPI()
    app.state.auth_manager = _PrivAuthManager(privileges)

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_remote_routes())
    return TestClient(app)


def test_mutations_require_privilege(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege denied")

    monkeypatch.setattr(remote_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})
    writes = [
        ("POST", "/api/applicant/remote/sessions", {"application_id": "a"}),
        ("POST", "/api/applicant/remote/sessions/s1/takeover", None),
        ("POST", "/api/applicant/remote/applications/a/submit-self", None),
        ("POST", "/api/applicant/remote/applications/a/authorize-engine-finish", None),
        ("POST", "/api/applicant/remote/applications/a/resume-account-step", None),
        ("POST", "/api/applicant/remote/applications/a/resume-detection-step", None),
        ("POST", "/api/applicant/remote/applications/a/continue-two-factor", None),
    ]
    for method, path, body in writes:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


def test_reads_allowed_without_write_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"sessions": [], "count": 0})
    client = _make_priv_client({"can_use_documents": False})
    assert client.get("/api/applicant/remote/sessions").status_code == 200
    assert client.get("/api/applicant/remote/sessions/s1/view-url").status_code == 200


# ── desktop assist (FR-CUA): opt-in, per-session, ships DORMANT ──────────────


def test_desktop_health_passes_through(monkeypatch):
    _patch_engine(monkeypatch, result={"available": False, "dormant": True, "ok": True})
    resp = _make_client().get("/api/applicant/remote/desktop/health")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
    assert resp.json()["dormant"] is True
    assert _FakeEngine.last_call == ("desktop_assist_health", ())


def test_desktop_health_degrades_to_disabled_when_engine_down(monkeypatch):
    # Engine unreachable -> the surface must degrade to an HONEST disabled state
    # (200 with available=False), not a 502 that would break the live-session UI.
    _patch_engine(monkeypatch, error=EngineError("down", is_timeout=True))
    resp = _make_client().get("/api/applicant/remote/desktop/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["dormant"] is True


def test_desktop_state_passes_through(monkeypatch):
    _patch_engine(
        monkeypatch,
        result={"session_id": "sbx-1", "enabled": False, "available": False, "dormant": True},
    )
    resp = _make_client().get("/api/applicant/remote/sessions/sbx-1/desktop")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert _FakeEngine.last_call == ("desktop_assist_state", ("sbx-1",))


def test_desktop_state_degrades_when_engine_down(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down", is_timeout=True))
    resp = _make_client().get("/api/applicant/remote/sessions/sbx-1/desktop")
    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "sbx-1",
        "enabled": False,
        "available": False,
        "dormant": True,
    }


def test_desktop_enable_maps_to_engine_enable(monkeypatch):
    _patch_engine(monkeypatch, result={"session_id": "sbx-1", "enabled": True})
    resp = _make_client().post("/api/applicant/remote/sessions/sbx-1/desktop/enable")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("desktop_assist_enable", ("sbx-1",))


def test_desktop_enable_dormant_409_passes_through(monkeypatch):
    # While dormant the engine refuses to enable (409); the UI must see the 409.
    err = EngineError("dormant", status=409, detail="not available yet")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post("/api/applicant/remote/sessions/sbx-1/desktop/enable")
    assert resp.status_code == 409
    assert resp.json()["engine_status"] == 409


def test_desktop_disable_maps_to_engine_disable(monkeypatch):
    _patch_engine(monkeypatch, result={"session_id": "sbx-1", "enabled": False})
    resp = _make_client().post("/api/applicant/remote/sessions/sbx-1/desktop/disable")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("desktop_assist_disable", ("sbx-1",))


def test_desktop_action_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result={"action": "capture", "mode": "som"})
    resp = _make_client().post(
        "/api/applicant/remote/sessions/sbx-1/desktop/action",
        json={"action": "capture", "mode": "som"},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "desktop_assist_action"
    assert args[0] == "sbx-1"
    assert args[1]["action"] == "capture"


def test_desktop_action_boundary_403_passes_through(monkeypatch):
    # A desktop action mapped to the stop-boundary (e.g. a final-submit click) is
    # refused by the engine core (403); the proxy must NEVER bypass it.
    err = EngineError("boundary", status=403, detail="final submit not authorized")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/remote/sessions/sbx-1/desktop/action",
        json={"action": "click", "element_token": "e1", "intent": "final_submit"},
    )
    assert resp.status_code == 403


def test_desktop_mutations_require_privilege(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege denied")

    monkeypatch.setattr(remote_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})
    writes = [
        ("POST", "/api/applicant/remote/sessions/s1/desktop/enable", None),
        ("POST", "/api/applicant/remote/sessions/s1/desktop/disable", None),
        ("POST", "/api/applicant/remote/sessions/s1/desktop/action", {"action": "capture"}),
    ]
    for method, path, body in writes:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


def test_desktop_reads_allowed_without_write_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"available": False, "dormant": True})
    client = _make_priv_client({"can_use_documents": False})
    assert client.get("/api/applicant/remote/desktop/health").status_code == 200
    assert client.get("/api/applicant/remote/sessions/s1/desktop").status_code == 200
