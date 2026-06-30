"""Hermetic test for GET /api/applicant/features (routes/applicant_routes.py).

Mounts only the applicant router on a bare FastAPI app and monkeypatches the
feature computation so the endpoint is exercised without an engine. Also asserts
the endpoint never propagates an exception (always returns a payload).

Auth is satisfied by a tiny middleware that sets ``request.state.current_user``
(the real global auth gate lives in ``app.py`` and is out of scope here).
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_routes as applicant_routes
from routes.applicant_routes import setup_applicant_routes


def _make_client(*, user="tester"):
    """Mount the router with an auth middleware that injects ``user``."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        if user:
            request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_routes())
    return TestClient(app)


@pytest.fixture
def client():
    return _make_client(user="tester")


def test_features_endpoint_returns_computed_payload(client, monkeypatch):
    payload = {
        "engine_available": True,
        "engine_url": "http://api:8000",
        "sections": {"compare": {"key": "compare", "state": "disabled"}},
    }
    monkeypatch.setattr(applicant_routes, "compute_features", lambda: payload)

    resp = client.get("/api/applicant/features")
    assert resp.status_code == 200
    assert resp.json() == payload


def test_features_endpoint_degrades_on_internal_error(client, monkeypatch):
    def boom():
        raise RuntimeError("engine layer blew up")

    monkeypatch.setattr(applicant_routes, "compute_features", boom)

    resp = client.get("/api/applicant/features")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_available"] is False
    assert body["sections"] == {}


def test_features_requires_authentication(monkeypatch):
    """Unauthenticated callers must be rejected — features leaks engine config."""
    app = FastAPI()

    @app.middleware("http")
    async def _no_user(request: Request, call_next):
        # Simulate a configured auth manager that has no session for this caller.
        class _Mgr:
            is_configured = True
        request.app.state.auth_manager = _Mgr()
        return await call_next(request)

    app.include_router(setup_applicant_routes())
    c = TestClient(app, raise_server_exceptions=False)
    resp = c.get("/api/applicant/features")
    assert resp.status_code == 401
