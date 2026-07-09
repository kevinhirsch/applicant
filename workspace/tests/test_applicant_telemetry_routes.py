"""Hermetic tests for the Settings > System > Error telemetry proxy routes (P5-3).

Mirrors ``test_applicant_automation_settings_routes.py``'s shape exactly: the
engine client is replaced with a fake async-context-manager so every route is
exercised with zero network. Covers the happy path (engine JSON passed
through), the auth gate (read requires a logged-in user), the owner-scoped
config-privilege gate (write requires ``can_configure``), the partial-update
(``exclude_unset``) forwarding, and the typed-error -> clean-JSON-error
translation.

The privacy-critical assertions live on the ENGINE side
(``tests/unit/test_telemetry_reporting.py``) — this file only proves the
proxy forwards the engine's own ``effective``/``local_only`` computation
byte-for-byte rather than re-deriving or overriding it, and that a caller
cannot smuggle an extra field (e.g. ``effective``) into the write body.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_setup_routes as setup_routes
from routes.applicant_setup_routes import setup_applicant_setup_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient, scoped to the telemetry methods
    this test file exercises. Records (method, args); returns a canned result
    or raises a canned EngineError. Async context manager."""

    last_call = None

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

    async def setup_get_telemetry(self):
        return await self._dispatch("setup_get_telemetry")

    async def setup_configure_telemetry(self, body):
        return await self._dispatch("setup_configure_telemetry", body)


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        setup_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(result=result, error=error),
    )


def _make_client(*, authed: bool = True):
    app = FastAPI()
    if authed:

        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)

    app.include_router(setup_applicant_setup_routes())
    return TestClient(app, raise_server_exceptions=True)


# ── happy path ────────────────────────────────────────────────────────────


def test_get_telemetry_passes_engine_json_through(monkeypatch):
    payload = {
        "enabled": False,
        "endpoint": "",
        "endpoint_configured": False,
        "local_only": False,
        "effective": False,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/telemetry")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("setup_get_telemetry", ())


def test_get_telemetry_forwards_effective_false_despite_stored_enabled(monkeypatch):
    payload = {
        "enabled": True,
        "endpoint": "https://telemetry.example.com/ingest",
        "endpoint_configured": True,
        "local_only": True,
        "effective": False,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/telemetry")
    assert resp.status_code == 200
    assert resp.json()["effective"] is False
    assert resp.json()["local_only"] is True


def test_put_telemetry_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {"enabled": True, "endpoint": "https://telemetry.example.com/ingest"}
    resp = _make_client().post("/api/applicant/setup/telemetry", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_telemetry"
    assert args[0] == body


def test_put_telemetry_only_forwards_fields_actually_sent(monkeypatch):
    """A field omitted from the request body must not be forwarded as an
    explicit null -- that would clobber the persisted value for that key."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/telemetry", json={"enabled": True}
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_telemetry"
    assert args[0] == {"enabled": True}
    assert "endpoint" not in args[0]


def test_put_telemetry_ignores_an_unknown_effective_field(monkeypatch):
    """A caller cannot smuggle a fabricated ``effective``/``local_only`` value
    into the write body -- the proxy's Pydantic model only knows about
    ``enabled``/``endpoint``, so anything else is dropped before it ever
    reaches the engine (defense in depth: the engine itself computes
    ``effective`` server-side and would ignore it too, but the proxy should
    not even forward the attempt)."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().post(
        "/api/applicant/setup/telemetry",
        json={"enabled": True, "effective": True, "local_only": False},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_configure_telemetry"
    assert args[0] == {"enabled": True}
    assert "effective" not in args[0]
    assert "local_only" not in args[0]


def test_put_telemetry_rejects_engine_422_for_bad_endpoint(monkeypatch):
    err = EngineError(
        "bad", status=422, detail="telemetry endpoint must be an http(s) URL (got scheme 'file')."
    )
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/setup/telemetry", json={"endpoint": "file:///etc/passwd"}
    )
    assert resp.status_code == 422
    assert "must be an http(s) URL" in resp.json()["detail"]


def test_get_telemetry_soft_degrades_when_engine_down(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("connection refused"))
    resp = _make_client().get("/api/applicant/setup/telemetry")
    assert resp.status_code == 502
    assert resp.json()["message"] == "The application engine is unavailable."


# ── auth gate ────────────────────────────────────────────────────────────


def test_get_telemetry_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_setup_routes())
    client = TestClient(app)

    assert client.get("/api/applicant/setup/telemetry").status_code == 401


# ── owner-scoped config privilege gate (write requires can_configure) ──────


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

    app.include_router(setup_applicant_setup_routes())
    return TestClient(app)


def test_put_telemetry_requires_can_configure(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_configure": False})

    resp = client.post("/api/applicant/setup/telemetry", json={"enabled": True})
    assert resp.status_code == 403


def test_get_telemetry_does_not_require_can_configure(monkeypatch):
    """Reads are available to any logged-in user (matches GET /automation,
    GET /channels) -- only the write is privileged."""
    _patch_engine(monkeypatch, result={"enabled": False, "effective": False})
    client = _make_priv_client({"can_configure": False})
    resp = client.get("/api/applicant/setup/telemetry")
    assert resp.status_code == 200
