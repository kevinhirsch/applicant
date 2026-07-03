"""Hermetic tests for the profile-gap-checklist proxy route (dark-engine audit
item 51): ``GET /api/applicant/setup/gaps/{campaign_id}``.

``ChatService.identify_gaps`` was previously read ONLY as hidden LLM context
inside a chat turn -- no route exposed it as a visible checklist. This proves
the workspace proxy forwards to the new engine client method
(``ApplicantEngineClient.setup_get_gaps``), passes the campaign id through,
translates engine errors the same way every other setup route does, and is
reachable only to an authenticated caller (owner-scoped read, mirrors the other
GET routes in ``applicant_setup_routes.py`` which use ``require_user``).

Zero network: the engine client is replaced with a fake async-context-manager,
matching the pattern in ``test_applicant_setup_routes.py``.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_setup_routes as setup_routes
from routes.applicant_setup_routes import setup_applicant_setup_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient. Records (method, args), returns a
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

    async def setup_get_gaps(self, campaign_id):
        return await self._dispatch("setup_get_gaps", campaign_id)


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


def test_gaps_route_passes_engine_json_through(monkeypatch):
    payload = {"campaign_id": "c1", "gaps": ["email address", "phone"], "complete": False}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/gaps/c1")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("setup_get_gaps", ("c1",))


def test_gaps_route_forwards_the_campaign_id(monkeypatch):
    _patch_engine(monkeypatch, result={"campaign_id": "abc-123", "gaps": [], "complete": True})
    resp = _make_client().get("/api/applicant/setup/gaps/abc-123")
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "setup_get_gaps"
    assert args == ("abc-123",)


def test_gaps_route_complete_profile_is_well_formed(monkeypatch):
    _patch_engine(monkeypatch, result={"campaign_id": "c1", "gaps": [], "complete": True})
    resp = _make_client().get("/api/applicant/setup/gaps/c1")
    assert resp.status_code == 200
    assert resp.json()["complete"] is True
    assert resp.json()["gaps"] == []


def test_gaps_route_engine_timeout_becomes_502(monkeypatch):
    err = EngineError("timed out", is_timeout=True)
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/setup/gaps/c1")
    assert resp.status_code == 502
    assert "timed out" in resp.json()["message"].lower()


def test_gaps_route_engine_connection_error_becomes_502(monkeypatch):
    err = EngineError("connection refused")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/setup/gaps/c1")
    assert resp.status_code == 502
    assert resp.json()["message"] == "The application engine is unavailable."


def test_gaps_route_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_setup_routes())
    client = TestClient(app)

    assert client.get("/api/applicant/setup/gaps/c1").status_code == 401
