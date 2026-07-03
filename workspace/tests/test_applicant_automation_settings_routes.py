"""Hermetic tests for the Settings > Automation proxy routes (dark-engine audit
items 82/84/85: EGRESS_TIMEZONE/EGRESS_LOCALE, ALLOW_AUTOMATED_ACCOUNTS,
PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY).

Mirrors ``test_applicant_setup_routes.py``'s ``test_get_tiers_passes_through`` /
``test_set_tiers_forwards_ladder`` shape: the engine client is replaced with a
fake async-context-manager so every route is exercised with zero network. Covers
the happy path (engine JSON passed through), the auth gate (read requires a
logged-in user), the owner-scoped config-privilege gate (write requires
``can_configure``), the partial-update (``exclude_unset``) forwarding, and the
typed-error -> clean-JSON-error translation.

Each assertion here was hand-verified to go RED when the corresponding route /
client method / privilege check is reverted, then GREEN again after restoring
(revert-verification per the task's definition of done).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_setup_routes as setup_routes
from routes.applicant_setup_routes import setup_applicant_setup_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient, scoped to the automation-prefs
    methods this test file exercises. Records (method, args); returns a
    canned result or raises a canned EngineError. Async context manager."""

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

    async def setup_get_automation_prefs(self):
        return await self._dispatch("setup_get_automation_prefs")

    async def setup_set_automation_prefs(self, body):
        return await self._dispatch("setup_set_automation_prefs", body)


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


def test_get_automation_prefs_passes_engine_json_through(monkeypatch):
    payload = {
        "egress_timezone": "America/Phoenix",
        "egress_locale": "en-US",
        "allow_automated_accounts": False,
        "presubmit_max_apps_per_company_per_day": 3,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/automation")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("setup_get_automation_prefs", ())


def test_put_automation_prefs_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {
        "egress_timezone": "America/Chicago",
        "egress_locale": "en-GB",
        "allow_automated_accounts": True,
        "presubmit_max_apps_per_company_per_day": 8,
    }
    resp = _make_client().put("/api/applicant/setup/automation", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_set_automation_prefs"
    assert args[0] == body


def test_put_automation_prefs_only_forwards_fields_actually_sent(monkeypatch):
    """A field omitted from the request body must not be forwarded as an
    explicit null -- that would clobber the persisted value for that key
    (the engine's set_automation_prefs treats an explicit None as a no-op,
    but the proxy should not even send unrelated keys)."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"allow_automated_accounts": True},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_set_automation_prefs"
    assert args[0] == {"allow_automated_accounts": True}
    assert "egress_timezone" not in args[0]
    assert "presubmit_max_apps_per_company_per_day" not in args[0]


def test_put_automation_prefs_rejects_engine_400(monkeypatch):
    err = EngineError("bad", status=400, detail="The per-company daily cap cannot be negative.")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"presubmit_max_apps_per_company_per_day": -1},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "The per-company daily cap cannot be negative."


def test_get_automation_prefs_soft_degrades_when_engine_down(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("connection refused"))
    resp = _make_client().get("/api/applicant/setup/automation")
    assert resp.status_code == 502
    assert resp.json()["message"] == "The application engine is unavailable."


# ── auth gate ────────────────────────────────────────────────────────────


def test_get_automation_prefs_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_setup_routes())
    client = TestClient(app)

    assert client.get("/api/applicant/setup/automation").status_code == 401


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


def test_put_automation_prefs_requires_can_configure(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_configure": False})

    resp = client.put(
        "/api/applicant/setup/automation", json={"allow_automated_accounts": True}
    )
    assert resp.status_code == 403


def test_get_automation_prefs_does_not_require_can_configure(monkeypatch):
    """Reads are available to any logged-in user (matches GET /llm/tiers,
    GET /channels, GET /sandbox-connection) -- only the PUT is privileged."""
    _patch_engine(monkeypatch, result={"egress_timezone": "America/Phoenix"})
    client = _make_priv_client({"can_configure": False})
    resp = client.get("/api/applicant/setup/automation")
    assert resp.status_code == 200
