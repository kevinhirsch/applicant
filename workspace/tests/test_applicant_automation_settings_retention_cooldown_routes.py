"""Hermetic tests for the Settings > Automation proxy routes' two new fields
(dark-engine audit items 87/88): ``pii_retention_days`` (data-retention
window, default 0 = keep forever) and ``presubmit_duplicate_cooldown_days``
(re-apply cooldown, default 30).

Mirrors ``test_applicant_automation_settings_routes.py``'s shape: the engine
client is replaced with a fake async-context-manager so every route is
exercised with zero network. Covers the happy path (engine JSON passed
through, including the two new fields), the partial-update (``exclude_unset``)
forwarding for the new fields specifically, and the typed-error -> clean-JSON
translation for a rejection on either new field.

Each assertion here was hand-verified to go RED when the corresponding field
is reverted from ``AutomationPrefsIn`` in
``workspace/routes/applicant_setup_routes.py``, then GREEN again after
restoring (revert-verification per the task's definition of done, using
file-copy backups rather than ``git stash`` -- shared across sibling
worktrees in this session).
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


def test_get_automation_prefs_passes_retention_and_cooldown_through(monkeypatch):
    payload = {
        "egress_timezone": "America/Phoenix",
        "egress_locale": "en-US",
        "allow_automated_accounts": False,
        "presubmit_max_apps_per_company_per_day": 3,
        "pii_retention_days": 0,
        "presubmit_duplicate_cooldown_days": 30,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/automation")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_put_automation_prefs_forwards_retention_and_cooldown(monkeypatch):
    _patch_engine(monkeypatch, result=None)
    body = {"pii_retention_days": 180, "presubmit_duplicate_cooldown_days": 45}
    resp = _make_client().put("/api/applicant/setup/automation", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    name, args = _FakeEngine.last_call
    assert name == "setup_set_automation_prefs"
    assert args[0] == body


def test_put_automation_prefs_only_forwards_new_fields_actually_sent(monkeypatch):
    """A field omitted from the request body must not be forwarded as an
    explicit null -- that would clobber the persisted value for that key."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"pii_retention_days": 14},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_set_automation_prefs"
    assert args[0] == {"pii_retention_days": 14}
    assert "presubmit_duplicate_cooldown_days" not in args[0]
    assert "egress_timezone" not in args[0]


def test_put_automation_prefs_rejects_engine_400_for_negative_retention(monkeypatch):
    err = EngineError(
        "bad", status=400, detail="The data-retention window cannot be negative."
    )
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"pii_retention_days": -1},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "The data-retention window cannot be negative."


def test_put_automation_prefs_rejects_engine_400_for_negative_cooldown(monkeypatch):
    err = EngineError(
        "bad", status=400, detail="The re-apply cooldown cannot be negative."
    )
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().put(
        "/api/applicant/setup/automation",
        json={"presubmit_duplicate_cooldown_days": -3},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "The re-apply cooldown cannot be negative."


def test_zero_retention_days_round_trips_as_a_valid_value(monkeypatch):
    """0 is the documented default meaning "keep forever" -- must not be
    dropped/rejected as falsy anywhere along the proxy chain."""
    _patch_engine(monkeypatch, result=None)
    resp = _make_client().put(
        "/api/applicant/setup/automation", json={"pii_retention_days": 0}
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert args[0] == {"pii_retention_days": 0}
