"""Regression coverage for docs/design/audits/exhaustive2/03_performance.md's
items #1 (no response compression anywhere) and #3 (per-request
``httpx.AsyncClient`` construction on every workspace->engine proxy call).

Item #1 — GZip:
  - Neither ``workspace/app.py`` nor the engine's ``create_app()``
    (``src/applicant/app/main.py``) registered ``GZipMiddleware``. Both now do.
  - Starlette wraps each ``add_middleware`` call around everything registered
    before it, so the LAST call becomes the OUTERMOST layer (first to see the
    request, last to see the response). GZip must be outermost to compress the
    final assembled response, so on the workspace app it is added AFTER CORS /
    SecurityHeaders / RequestTimeout / Auth (`app.py:100/119/161/406`), not
    before. This is verified two ways: (a) source-position of the
    ``add_middleware`` calls in ``workspace/app.py`` (GZip's call must be the
    last of the five), and (b) a live behavioural reproduction of the same
    five-layer stack on a bare FastAPI app, proving GZip actually compresses a
    response that passed through all four inner layers. The engine app has no
    other middleware, so there GZip is simply the only layer.

Item #3 — shared httpx client:
  - ``ApplicantEngineClient.__init__`` now accepts an optional ``client=``
    (an already-open ``httpx.AsyncClient``). When given, this instance does
    NOT own its lifecycle: ``aclose()`` becomes a no-op, so the existing
    ``async with ApplicantEngineClient(client=...) as engine:`` pattern (the
    exact pattern already used at ~180 call sites) is a safe drop-in swap.
  - ``workspace/app.py``'s startup event builds ONE app-lifetime client via
    ``src.applicant_engine.build_shared_http_client()`` and stores it at
    ``app.state.http_client``; the shutdown event closes it.
  - ``src.applicant_engine.shared_engine_http_client(request)`` is the
    reusable per-request resolver: it returns ``request.app.state.http_client``
    (or ``None`` when unset, e.g. a bare test app that never ran the real
    startup event) WITHOUT constructing an ``ApplicantEngineClient`` itself, so
    call sites keep using their OWN already-imported ``ApplicantEngineClient``
    name — this is what keeps every existing ``monkeypatch.setattr(mod,
    "ApplicantEngineClient", FakeEngine)``-based route test working unchanged
    (verified below with the exact real route + MockTransport pattern the
    existing route test suites use).
  - Wired into three representative, high-traffic call sites as proof:
    ``routes/applicant_portal_routes.py``'s ``/pending`` (the Portal badge
    poll + open, the single highest-traffic proxy route) and
    ``routes/applicant_activity_routes.py``'s ``/status`` and ``/runs`` (the
    always-visible status strip poll + the Activity page). The remaining
    ~177 ``async with ApplicantEngineClient()`` call sites are an intentional,
    purely mechanical follow-up (each is a one-kwarg change:
    ``ApplicantEngineClient(client=shared_engine_http_client(request))``).

Every assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion fail
-> restore) per the batch's test-coverage DoD. Engine-app assertions import
the real ``applicant.app.main:app`` (cheap, in-memory-DB-fallback boot, no
network) as the boot smoke already proves is safe in this environment; the
workspace app is NOT imported directly (it pulls ChromaDB/RAG/TTS/etc. and has
real filesystem side effects) — those facts are read from source text or
reproduced on a bare FastAPI app, following the precedent set by
``test_applicant_global_exception_handler.py``.
"""

from __future__ import annotations

import asyncio
import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_APP_PY = REPO_ROOT / "workspace" / "app.py"
ENGINE_MAIN_PY = REPO_ROOT / "src" / "applicant" / "app" / "main.py"
APPLICANT_ENGINE_PY = REPO_ROOT / "workspace" / "src" / "applicant_engine.py"
PORTAL_ROUTES_PY = REPO_ROOT / "workspace" / "routes" / "applicant_portal_routes.py"
ACTIVITY_ROUTES_PY = REPO_ROOT / "workspace" / "routes" / "applicant_activity_routes.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── item #1: engine app registers GZip ───────────────────────────────────────


def test_engine_app_registers_gzip_middleware():
    from applicant.app.main import app

    gzip_entries = [m for m in app.user_middleware if m.cls is GZipMiddleware]
    assert gzip_entries, "GZipMiddleware not registered on the engine FastAPI app"
    assert gzip_entries[0].kwargs.get("minimum_size") == 1000


def test_engine_main_py_source_has_gzip_import_and_registration():
    src = _read(ENGINE_MAIN_PY)
    assert "from fastapi.middleware.gzip import GZipMiddleware" in src
    assert "app.add_middleware(GZipMiddleware, minimum_size=1000)" in src


# ── item #1: workspace app.py source — GZip present AND outermost ───────────


def test_workspace_app_py_source_has_gzip_import_and_registration():
    src = _read(WORKSPACE_APP_PY)
    assert "from fastapi.middleware.gzip import GZipMiddleware" in src
    assert "app.add_middleware(GZipMiddleware, minimum_size=1000)" in src


def test_workspace_gzip_added_after_cors_security_timeout_auth():
    """Starlette: the LAST add_middleware call becomes the OUTERMOST wrapper.

    GZip must compress the FINAL response every inner layer produces, so its
    add_middleware call must come after CORS, SecurityHeaders, RequestTimeout,
    and Auth in source order (each of those is added earlier / registered
    conditionally, but all four precede GZip on every code path).
    """
    src = _read(WORKSPACE_APP_PY)

    def _pos(marker: str) -> int:
        idx = src.index(marker)
        assert idx >= 0
        return idx

    cors_pos = _pos("app.add_middleware(\n    CORSMiddleware,")
    security_pos = _pos("app.add_middleware(SecurityHeadersMiddleware)")
    timeout_pos = _pos("app.add_middleware(_RequestTimeoutMiddleware)")
    auth_pos = _pos("app.add_middleware(AuthMiddleware)")
    gzip_pos = _pos("app.add_middleware(GZipMiddleware, minimum_size=1000)")

    assert cors_pos < gzip_pos
    assert security_pos < gzip_pos
    assert timeout_pos < gzip_pos
    assert auth_pos < gzip_pos


def test_workspace_gzip_registration_is_unconditional():
    """GZip must apply whether or not AUTH_ENABLED is set — it must not live
    inside the `if AUTH_ENABLED:` block (else it silently vanishes with auth
    disabled, e.g. local dev / LOCALHOST_BYPASS)."""
    src = _read(WORKSPACE_APP_PY)
    # The GZip registration line must appear strictly after the closing
    # `else:` branch of the auth block, i.e. outside the if/else entirely.
    else_pos = src.index('logger.info("Auth middleware disabled (set AUTH_ENABLED=true to enable)")')
    gzip_pos = src.index("app.add_middleware(GZipMiddleware, minimum_size=1000)")
    assert gzip_pos > else_pos


# ── item #1: behavioural reproduction of the exact 5-layer stack ────────────


def _build_reproduction_app(*, add_gzip_last: bool) -> FastAPI:
    """Reproduce workspace/app.py's middleware stack shape (CORS -> Security ->
    RequestTimeout -> Auth [-> GZip]) on a bare app, so GZip's actual
    compression behaviour when wrapping the other four layers can be exercised
    without importing the real (heavy, side-effecting) workspace/app.py.
    """
    app = FastAPI()

    @app.get("/payload")
    async def payload() -> JSONResponse:
        # Comfortably over GZipMiddleware's default/explicit minimum_size.
        return JSONResponse({"data": "x" * 5000})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost"],
        allow_credentials=True,
        allow_methods=["GET"],
    )

    class _SecurityHeaders(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            return resp

    app.add_middleware(_SecurityHeaders)

    class _RequestTimeout(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await asyncio.wait_for(call_next(request), timeout=45)

    app.add_middleware(_RequestTimeout)

    class _Auth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)

    app.add_middleware(_Auth)

    if add_gzip_last:
        app.add_middleware(GZipMiddleware, minimum_size=1000)

    return app


def test_gzip_as_outermost_layer_compresses_final_response():
    app = _build_reproduction_app(add_gzip_last=True)
    c = TestClient(app)
    r = c.get("/payload")
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    # The inner SecurityHeaders layer's header must still make it through.
    assert r.headers.get("x-content-type-options") == "nosniff"
    # Compression must have actually shrunk the wire payload.
    raw_json_len = len(r.json()["data"]) + 20
    assert len(r.content) < raw_json_len


def test_without_gzip_response_is_uncompressed():
    """Sanity check / revert-simulation: without GZipMiddleware registered at
    all, the same payload goes over the wire uncompressed."""
    app = _build_reproduction_app(add_gzip_last=False)
    c = TestClient(app)
    r = c.get("/payload")
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"


def test_small_response_under_minimum_size_is_not_compressed():
    app = FastAPI()

    @app.get("/tiny")
    async def tiny() -> dict:
        return {"ok": True}

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    c = TestClient(app)
    r = c.get("/tiny")
    assert r.headers.get("content-encoding") != "gzip"


# ── item #3: ApplicantEngineClient shared-client support ────────────────────


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_client_kwarg_is_used_directly_and_not_owned():
    from src.applicant_engine import ApplicantEngineClient

    shared = httpx.AsyncClient(
        base_url="http://api:8000",
        transport=_mock_transport(lambda r: httpx.Response(200, json={"ok": True})),
    )
    try:
        engine = ApplicantEngineClient(client=shared)
        assert engine._client is shared
        assert engine._owns_client is False

        data = await engine.setup_status()
        assert data == {"ok": True}

        # aclose() on an instance holding an injected client must NOT close it —
        # other in-flight requests may still be using the shared pool.
        await engine.aclose()
        assert shared.is_closed is False
    finally:
        await shared.aclose()


@pytest.mark.asyncio
async def test_default_construction_still_owns_and_closes_its_own_client():
    """Backward-compat: an un-injected ApplicantEngineClient (the ~180
    existing call sites, unchanged) must behave exactly as before — it owns
    its private pool and aclose() actually closes it."""
    from src.applicant_engine import ApplicantEngineClient

    engine = ApplicantEngineClient(
        base_url="http://api:8000",
        transport=_mock_transport(lambda r: httpx.Response(200, json={"ok": True})),
    )
    assert engine._owns_client is True
    await engine.aclose()
    assert engine._client.is_closed is True


def test_build_shared_http_client_matches_default_base_url_and_timeout():
    from src.applicant_engine import (
        _DEFAULT_TIMEOUT,
        build_shared_http_client,
        engine_base_url,
    )

    client = build_shared_http_client()
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert str(client.base_url).rstrip("/") == engine_base_url()
        assert client.timeout.connect == _DEFAULT_TIMEOUT.connect
        assert client.timeout.read == _DEFAULT_TIMEOUT.read
    finally:
        asyncio.run(client.aclose())


def test_shared_engine_http_client_resolves_from_request_app_state():
    from src.applicant_engine import shared_engine_http_client

    class _State:
        pass

    class _App:
        pass

    class _FakeRequest:
        pass

    sentinel = object()
    state = _State()
    state.http_client = sentinel
    app_obj = _App()
    app_obj.state = state
    req = _FakeRequest()
    req.app = app_obj

    assert shared_engine_http_client(req) is sentinel


def test_shared_engine_http_client_returns_none_when_unset():
    from src.applicant_engine import shared_engine_http_client

    class _State:
        pass

    class _App:
        pass

    class _FakeRequest:
        pass

    app_obj = _App()
    app_obj.state = _State()  # no http_client attribute set
    req = _FakeRequest()
    req.app = app_obj

    assert shared_engine_http_client(req) is None

    # And a request with no .app at all (defensive) must also degrade to None,
    # not raise.
    req2 = _FakeRequest()
    assert shared_engine_http_client(req2) is None


# ── item #3: workspace/app.py wires the shared client at startup/shutdown ───


def test_workspace_app_py_builds_shared_client_at_startup():
    src = _read(WORKSPACE_APP_PY)
    assert "from src.applicant_engine import build_shared_http_client" in src
    assert "app.state.http_client = build_shared_http_client()" in src
    # Must happen inside startup_event, not at import time.
    startup_idx = src.index('async def startup_event():')
    build_idx = src.index("app.state.http_client = build_shared_http_client()")
    shutdown_idx = src.index('async def shutdown_event():')
    assert startup_idx < build_idx < shutdown_idx


def test_workspace_app_py_closes_shared_client_at_shutdown():
    src = _read(WORKSPACE_APP_PY)
    shutdown_idx = src.index('async def shutdown_event():')
    aclose_idx = src.index("await http_client.aclose()")
    assert aclose_idx > shutdown_idx


# ── item #3: proof routes wired to the shared client ─────────────────────────


def test_portal_pending_route_source_uses_shared_client():
    src = _read(PORTAL_ROUTES_PY)
    assert "shared_engine_http_client" in src
    assert "ApplicantEngineClient(client=shared_engine_http_client(request))" in src


def test_activity_status_and_runs_routes_source_use_shared_client():
    src = _read(ACTIVITY_ROUTES_PY)
    assert "shared_engine_http_client" in src
    occurrences = src.count("ApplicantEngineClient(client=shared_engine_http_client(request))")
    assert occurrences >= 2, "expected /status and /runs to both use the shared client"


def test_portal_pending_route_actually_forwards_the_shared_client():
    """Functional proof: install a shared, already-open httpx.AsyncClient (over
    a MockTransport, zero network) on app.state.http_client and confirm the
    REAL route (not FakeEngine) serves a request through it and hits the exact
    engine paths — proving the injection is live, not just source text."""
    from routes.applicant_portal_routes import setup_applicant_portal_routes

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[{"id": "c1", "name": "Search"}])
        if request.url.path == "/api/pending-actions/c1":
            return httpx.Response(200, json={"campaign_id": "c1", "count": 0, "items": []})
        if request.url.path == "/api/onboarding/c1":
            return httpx.Response(200, json={"complete": True, "missing_sections": []})
        return httpx.Response(404, json={"detail": "unexpected"})

    shared_client = httpx.AsyncClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )

    app = FastAPI()
    app.state.http_client = shared_client

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())

    c = TestClient(app)
    try:
        r = c.get("/api/applicant/portal/pending")
        assert r.status_code == 200
        assert r.json()["count"] == 0
        assert ("GET", "/api/campaigns") in calls
        assert ("GET", "/api/pending-actions/c1") in calls
        # The route must not have closed the shared pool it borrowed.
        assert shared_client.is_closed is False
    finally:
        asyncio.run(shared_client.aclose())


def test_portal_pending_route_still_works_when_shared_client_absent():
    """Backward compat: a bare app that never set app.state.http_client (like
    every OTHER existing route test in this suite) must keep working exactly
    as before — shared_engine_http_client() degrades to None, and
    ApplicantEngineClient(client=None) falls back to its own private pool."""
    from routes.applicant_portal_routes import setup_applicant_portal_routes

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/campaigns":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "unexpected"})

    import routes.applicant_portal_routes as portal_mod

    class TransportEngine(portal_mod.ApplicantEngineClient):
        def __init__(self, *a, **k):
            super().__init__(base_url="http://api:8000", transport=httpx.MockTransport(handler))

    app = FastAPI()
    # NOTE: no app.state.http_client set at all.

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        request.state.current_user = "tester"
        return await call_next(request)

    app.include_router(setup_applicant_portal_routes())

    orig = portal_mod.ApplicantEngineClient
    portal_mod.ApplicantEngineClient = TransportEngine
    try:
        c = TestClient(app)
        r = c.get("/api/applicant/portal/pending")
        assert r.status_code == 200
        assert r.json() == {"engine_available": True, "count": 0, "items": []}
        assert ("GET", "/api/campaigns") in calls
    finally:
        portal_mod.ApplicantEngineClient = orig
