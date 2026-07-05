"""Regression coverage for editing/removing the engine's own saved model
endpoints from the front door (dark-engine audit item 20).

The engine has exposed ``PATCH /api/model-endpoints/{id}`` (toggle
enabled/disabled) and ``DELETE /api/model-endpoints/{id}`` since the endpoint
registry was built (``src/applicant/app/routers/model_endpoints.py``), but
``applicant_setup_routes.py`` only ever proxied list/add/test/models -- so a
stale or mistyped endpoint accumulated forever with no way to clean it up.
This file covers the three pieces that close that gap:

  * ``workspace/src/applicant_engine.py`` -- new ``patch_model_endpoint`` /
    ``delete_model_endpoint`` client methods.
  * ``workspace/routes/applicant_model_connections_routes.py`` -- new
    ``PATCH``/``DELETE /api/applicant/setup/model-endpoints/{id}`` proxies,
    gated by the same ``can_configure`` privilege as add/test.
  * ``workspace/static/js/applicantModelLadder.js`` -- a "Saved model
    connections" list (enable/disable + remove per row) in the Settings model
    panel that already owns this data's front door.

Note on scope: the engine's own endpoint registry is a genuinely SEPARATE
config store from the ordered LLM tier ladder that panel already edits (two
independent config-store keys -- ``model.endpoints`` vs. ``llm.tier_ladder``,
confirmed by reading ``model_endpoint_service.py`` / ``setup_service.py``) --
this list surfaces THAT registry's records, not the ladder's tiers.

Every assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted, then GREEN again after restoring.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_model_connections_routes as setup_routes
from routes.applicant_model_connections_routes import setup_applicant_model_connections_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
MODEL_LADDER_JS = WORKSPACE_DIR / "static" / "js" / "applicantModelLadder.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: patch_model_endpoint / delete_model_endpoint ────────────


@pytest.mark.asyncio
async def test_client_patch_model_endpoint_hits_exact_engine_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"ok": True})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    result = await client.patch_model_endpoint("ep-1")
    assert seen["path"] == "/api/model-endpoints/ep-1"
    assert seen["method"] == "PATCH"
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_client_delete_model_endpoint_hits_exact_engine_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(200, json={"ok": True})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    result = await client.delete_model_endpoint("ep-1")
    assert seen["path"] == "/api/model-endpoints/ep-1"
    assert seen["method"] == "DELETE"
    assert result == {"ok": True}


# ── workspace proxy routes ──────────────────────────────────────────────────


class _FakeEngine:
    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def patch_model_endpoint(self, endpoint_id):
        type(self).last_call = ("patch_model_endpoint", (endpoint_id,))
        if self._error is not None:
            raise self._error
        return self._result

    async def delete_model_endpoint(self, endpoint_id):
        type(self).last_call = ("delete_model_endpoint", (endpoint_id,))
        if self._error is not None:
            raise self._error
        return self._result


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
    app.include_router(setup_applicant_model_connections_routes())
    return TestClient(app, raise_server_exceptions=True)


def test_patch_model_endpoint_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"ok": True})
    resp = _make_client().patch("/api/applicant/setup/model-endpoints/ep-1")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _FakeEngine.last_call == ("patch_model_endpoint", ("ep-1",))


def test_delete_model_endpoint_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"ok": True})
    resp = _make_client().delete("/api/applicant/setup/model-endpoints/ep-1")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _FakeEngine.last_call == ("delete_model_endpoint", ("ep-1",))


def test_patch_model_endpoint_timeout_becomes_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("timed out", is_timeout=True))
    resp = _make_client().patch("/api/applicant/setup/model-endpoints/ep-1")
    assert resp.status_code == 502


def test_delete_model_endpoint_404_passes_through(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("unknown endpoint", status=404, detail="unknown endpoint"))
    resp = _make_client().delete("/api/applicant/setup/model-endpoints/nope")
    assert resp.status_code == 404


# ── auth + privilege gate (mirrors add/test model-endpoint routes) ─────────


def test_patch_and_delete_require_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)

    class _Configured:
        is_configured = True

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_model_connections_routes())
    client = TestClient(app)
    assert client.patch("/api/applicant/setup/model-endpoints/ep-1").status_code == 401
    assert client.delete("/api/applicant/setup/model-endpoints/ep-1").status_code == 401


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

    app.include_router(setup_applicant_model_connections_routes())
    return TestClient(app)


def test_patch_and_delete_require_can_configure_privilege(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("engine must not be called when privilege denied")

    monkeypatch.setattr(setup_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_configure": False})
    assert client.patch("/api/applicant/setup/model-endpoints/ep-1").status_code == 403
    assert client.delete("/api/applicant/setup/model-endpoints/ep-1").status_code == 403


def test_patch_and_delete_allowed_with_can_configure_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"ok": True})
    client = _make_priv_client({"can_configure": True})
    assert client.patch("/api/applicant/setup/model-endpoints/ep-1").status_code == 200
    assert client.delete("/api/applicant/setup/model-endpoints/ep-1").status_code == 200


# ── front-end: "Saved model connections" list in the model-ladder panel ────


def test_model_ladder_js_fetches_saved_endpoints():
    src = _read(MODEL_LADDER_JS)
    assert "${SETUP}/model-endpoints`" in src


def test_model_ladder_js_renders_toggle_and_remove_controls():
    src = _read(MODEL_LADDER_JS)
    assert "ml-ep-toggle" in src
    assert "ml-ep-remove" in src
    assert "method: 'PATCH'" in src
    assert "method: 'DELETE'" in src


def test_model_ladder_js_confirms_before_removing():
    src = _read(MODEL_LADDER_JS)
    fn = re.search(r"function _wireSavedEndpoints\(\) \{.*?\n\}", src, re.S)
    assert fn, "expected a _wireSavedEndpoints() function"
    assert "styledConfirm" in fn.group(0)
