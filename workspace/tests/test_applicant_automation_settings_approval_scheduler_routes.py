"""Hermetic tests for the Settings > Automation proxy routes' approval-timeout
and scheduler-interval fields (dark-engine audit items 86/90:
APPROVAL_TIMEOUT_DAYS/APPROVAL_WAIT_SECONDS, SCHEDULER_INTERVAL_SECONDS).

Extends the coverage in ``test_applicant_automation_settings_routes.py`` (the
82/84/85 foundation) to the two new knobs added to the same ``AutomationPrefsIn``
proxy body. The engine client is replaced with a fake async-context-manager so
every route is exercised with zero network.

Each assertion here was hand-verified to go RED when the corresponding field
is reverted from the proxy's ``AutomationPrefsIn``, then GREEN again after
restoring (revert-verification per the task's definition of done, via
file-copy backups -- not ``git stash``, which is shared across worktrees in
this session).
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


def test_get_automation_prefs_passes_the_new_fields_through(monkeypatch):
    payload = {
        "egress_timezone": "America/Phoenix",
        "egress_locale": "en-US",
        "allow_automated_accounts": False,
        "presubmit_max_apps_per_company_per_day": 3,
        "approval_timeout_days": 30,
        "approval_wait_seconds": None,
        "scheduler_interval_seconds": 60.0,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/automation")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_put_automation_prefs_forwards_the_new_fields(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {
        "approval_timeout_days": 45,
        "approval_wait_seconds": 600.0,
        "scheduler_interval_seconds": 20.0,
    }
    resp = _make_client().put("/api/applicant/setup/automation", json=body)
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_set_automation_prefs"
    assert args[0] == body


def test_put_automation_prefs_only_forwards_the_new_fields_actually_sent(monkeypatch):
    """A field omitted from the request body must not be forwarded as an
    explicit null -- that would clobber the persisted value for that key."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"scheduler_interval_seconds": 30.0},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert args[0] == {"scheduler_interval_seconds": 30.0}
    assert "approval_timeout_days" not in args[0]
    assert "approval_wait_seconds" not in args[0]


def test_put_automation_prefs_rejects_engine_400_for_the_new_fields(monkeypatch):
    err = EngineError("bad", status=400, detail="The check interval must be greater than zero.")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"scheduler_interval_seconds": 0},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "The check interval must be greater than zero."


def test_put_automation_prefs_still_requires_can_configure(monkeypatch):
    class _PrivAuthManager:
        is_configured = True

        def get_privileges(self, _user):
            return {"can_configure": False}

    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _PrivAuthManager()

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = "restricted"
        return await call_next(request)

    app.include_router(setup_applicant_setup_routes())
    client = TestClient(app)

    resp = client.put(
        "/api/applicant/setup/automation", json={"approval_timeout_days": 5}
    )
    assert resp.status_code == 403
