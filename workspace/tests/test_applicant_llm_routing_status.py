"""Front-door pass-through of the engine's live smart-routing status
(dark-engine audit item 74).

The engine's ``GET /api/setup/llm/tiers`` now returns a ``routing`` block (which
endpoint the smart router actually picked and why) alongside ``tiers``. The
front-door proxy (``routes/applicant_setup_routes.py::get_llm_tiers``) forwards
the engine's JSON through unchanged, so these tests confirm the new key survives
that hop exactly as returned — hermetic, zero network (the engine client is a fake).
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_setup_routes as setup_routes
from routes.applicant_setup_routes import setup_applicant_setup_routes
from src.applicant_engine import EngineError


class _FakeTiersEngine:
    """Minimal fake engine client exercising only GET /llm/tiers."""

    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def setup_get_tiers(self):
        type(self).last_call = "setup_get_tiers"
        if self._error is not None:
            raise self._error
        return self._result


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeTiersEngine.last_call = None
    monkeypatch.setattr(
        setup_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeTiersEngine(result=result, error=error),
    )


def _make_client():
    app = FastAPI()

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_setup_routes())
    return TestClient(app, raise_server_exceptions=True)


def test_routing_block_passes_through_unchanged(monkeypatch):
    payload = {
        "tiers": [{"provider": "ollama", "model": "llama3.1", "base_url": "http://localhost:11434"}],
        "routing": {
            "enabled": True,
            "prefer_local": True,
            "active_endpoint": {"name": "local-ollama", "base_url": "http://localhost:11434"},
            "reordered": False,
            "health": {
                "endpoints_total": 2,
                "endpoints_online": 2,
                "local_available": 1,
                "cloud_available": 1,
                "has_local_fallback": True,
            },
        },
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/llm/tiers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["routing"] == payload["routing"]
    assert body["engine_available"] is True


def test_routing_block_absent_when_engine_omits_it(monkeypatch):
    """An older/degraded engine response with no ``routing`` key must not 500 —
    the proxy is a thin pass-through and adds nothing of its own."""
    payload = {"tiers": []}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/setup/llm/tiers")
    assert resp.status_code == 200
    assert "routing" not in resp.json()


def test_routing_block_missing_when_engine_unreachable(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down"))
    resp = _make_client().get("/api/applicant/setup/llm/tiers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine_available"] is False
    assert "routing" not in body
