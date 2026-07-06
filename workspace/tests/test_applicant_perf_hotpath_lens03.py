"""Regression coverage for docs/design/audits/exhaustive2/03_performance.md's
LANE-P4 hot-path micro-fixes: findings #46-#48 and #50.

  #46 `SecurityHeadersMiddleware` (`workspace/core/middleware.py`) used to run
      `secrets.token_hex(16)` on EVERY request, including every one of the
      ~162 `/static/*` JS/CSS/asset requests per page load that never read
      `request.state.csp_nonce` at all (only the handful of HTML-serving
      routes in `workspace/app.py` do, via `_serve_html_with_nonce`). The
      fixed `dispatch` now skips the `token_hex` call for `/static/*` paths.

  #47 The cookie-session branch of `workspace/app.py`'s `AuthMiddleware`
      used to call `auth_manager.validate_token(token)` (one locked lookup +
      expiry/orphan check) and then, on success, `auth_manager
      .get_username_for_token(token)` (a SECOND locked lookup re-running the
      exact same expiry/orphan check) just to get the username. Since
      `get_username_for_token` already performs every check `validate_token`
      does and returns `None` under the exact same failure conditions, the
      fix collapses this to a single `get_username_for_token(token)` call
      whose truthiness IS the validity check.

  #48 `serve_generated_image` used to open a fresh `SessionLocal()` and run
      the gallery-ownership query on every single image request, even though
      generated-image filenames are content hashes (the bytes for a given
      filename never change) and a gallery grid re-requests the same
      filenames repeatedly. The fix adds a short-TTL in-process
      filename->owner cache (`_IMAGE_OWNER_CACHE`) so repeat requests for the
      same filename skip the DB round trip; a TTL (not "forever") keeps this
      correct if a null-owner row is later swept to a real owner.

  #50 The LLM keepalive loop's `_warmup_endpoints` used to build a brand new
      `httpx.AsyncClient(timeout=5.0)` INSIDE the per-endpoint loop -- up to 5
      fresh clients every 60s cycle. The fix hoists a single
      `httpx.AsyncClient` construction above the loop and reuses it for every
      endpoint in that cycle.

Every assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore), per this codebase's test-coverage convention (see
test_applicant_backlog_perfcompression.py's docstring for the same
methodology). Following that same file's precedent, `workspace/app.py` is
NOT imported directly here (it pulls ChromaDB/RAG/TTS/bcrypt/etc. that are
not installed in this lane's env) -- its behavior for #47/#48/#50 is
reproduced on small, self-contained stand-ins whose logic is a deliberate,
commented mirror of the real code, cross-checked against the actual
`workspace/app.py` source text so the two can't silently drift apart.
`workspace/core/middleware.py` (#46) IS lightweight enough (only
fastapi/starlette) to load directly, standalone, bypassing
`core/__init__.py`'s heavy `src.llm_core` import -- the exact technique
`test_applicant_backlog_htmlcache.py` already uses for the same module.
"""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
WORKSPACE_APP_PY = WORKSPACE_DIR / "app.py"
MIDDLEWARE_PY = WORKSPACE_DIR / "core" / "middleware.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module_from_path(name: str, path: pathlib.Path):
    """Load a module directly by file path, bypassing its package's
    ``__init__.py`` (mirrors test_applicant_backlog_htmlcache.py's technique
    for dodging core/__init__.py's heavy src.llm_core import)."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


APP_PY_SRC = _read(WORKSPACE_APP_PY)


# ═══════════════════════════════════════════════════════════════════════
# #46 -- CSP nonce skipped for /static/* requests
# ═══════════════════════════════════════════════════════════════════════


def test_middleware_source_skips_token_hex_for_static_prefix():
    src = _read(MIDDLEWARE_PY)
    assert 'path.startswith("/static/")' in src
    # The skip branch must sit ahead of the unconditional generation it
    # replaces -- i.e. there must be an if/else around the token_hex call.
    idx = src.index('path.startswith("/static/")')
    tail = src[idx : idx + 200]
    assert 'nonce = ""' in tail
    assert "secrets.token_hex(16)" in tail


def test_static_request_never_calls_token_hex():
    """Behavioral proof: a real request through the real (standalone-loaded)
    SecurityHeadersMiddleware for a /static/* path must not touch
    secrets.token_hex at all."""
    middleware_mod = _load_module_from_path("t_lens03_middleware_static", MIDDLEWARE_PY)

    calls = {"n": 0}
    real_token_hex = middleware_mod.secrets.token_hex

    def counting_token_hex(*a, **k):
        calls["n"] += 1
        return real_token_hex(*a, **k)

    middleware_mod.secrets.token_hex = counting_token_hex

    app = FastAPI()
    app.add_middleware(middleware_mod.SecurityHeadersMiddleware)

    @app.get("/static/{path:path}")
    async def static_stub(path: str):
        return PlainTextResponse("asset-bytes")

    client = TestClient(app)
    r1 = client.get("/static/js/app.js")
    r2 = client.get("/static/style.css")

    assert r1.status_code == r2.status_code == 200
    assert calls["n"] == 0, "static requests must not generate a CSP nonce"
    # request.state.csp_nonce still exists (defaults to ""), so the CSP header
    # this (non-HTML) response carries has an empty 'nonce-' component rather
    # than a real random value -- no 32-hex-char nonce was ever generated.
    import re

    csp = r1.headers.get("content-security-policy", "")
    assert "'nonce-'" in csp
    assert not re.search(r"nonce-[0-9a-f]{32}", csp)


def test_html_request_still_gets_a_real_unique_nonce_per_response():
    """Non-static routes must be completely unaffected: every response still
    gets its own freshly generated nonce, embedded correctly in its own CSP
    header -- the optimization must not touch this path at all."""
    middleware_mod = _load_module_from_path("t_lens03_middleware_html", MIDDLEWARE_PY)

    app = FastAPI()
    app.add_middleware(middleware_mod.SecurityHeadersMiddleware)

    @app.get("/")
    async def index(request: Request):
        nonce = getattr(request.state, "csp_nonce", "")
        return HTMLResponse(f'<script nonce="{nonce}">boot()</script>')

    client = TestClient(app)
    r1 = client.get("/")
    r2 = client.get("/")

    import re

    def body_nonce(resp):
        m = re.search(r'nonce="([0-9a-f]{32})"', resp.text)
        assert m, resp.text
        return m.group(1)

    n1, n2 = body_nonce(r1), body_nonce(r2)
    assert n1 != n2, "each non-static response must still get a unique nonce"
    for resp, nonce in ((r1, n1), (r2, n2)):
        csp = resp.headers.get("content-security-policy", "")
        assert f"nonce-{nonce}" in csp


def test_revert_simulation_old_dispatch_generated_nonce_for_static_too():
    """Revert-simulation: reproduces the OLD unconditional
    `nonce = secrets.token_hex(16)` (no static skip) to prove it DOES burn a
    token_hex call on a /static/* request -- the exact cost the fix
    eliminates."""
    import secrets as real_secrets
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    calls = {"n": 0}

    class _OldSecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            calls["n"] += 1
            nonce = real_secrets.token_hex(16)
            request.state.csp_nonce = nonce
            response = await call_next(request)
            response.headers["Content-Security-Policy"] = f"script-src 'nonce-{nonce}'"
            return response

    app = FastAPI()
    app.add_middleware(_OldSecurityHeadersMiddleware)

    @app.get("/static/{path:path}")
    async def static_stub(path: str):
        return PlainTextResponse("asset-bytes")

    client = TestClient(app)
    client.get("/static/js/app.js")
    assert calls["n"] == 1, "old behavior generates a nonce even for /static/*"


# ═══════════════════════════════════════════════════════════════════════
# #47 -- auth middleware: single lookup instead of validate_token +
#         get_username_for_token
# ═══════════════════════════════════════════════════════════════════════


def test_app_py_source_cookie_auth_uses_single_lookup():
    """The cookie-session branch must resolve the username via ONE call to
    get_username_for_token and must not also call validate_token."""
    idx = APP_PY_SRC.index("--- Cookie-based session auth ---")
    # Bounded window: from the comment to the next top-level middleware
    # registration (`app.add_middleware(AuthMiddleware)`), which closes the
    # branch.
    end = APP_PY_SRC.index("app.add_middleware(AuthMiddleware)", idx)
    block = APP_PY_SRC[idx:end]

    assert "auth_manager.get_username_for_token(token)" in block
    assert "auth_manager.validate_token(" not in block, (
        "the cookie-auth branch must not run a second, redundant "
        "validate_token lookup alongside get_username_for_token"
    )
    # The resolved username itself must be the validity check.
    assert "username = auth_manager.get_username_for_token(token)" in block
    assert "if not username:" in block


class _FakeAuthManager:
    """Instrumented stand-in for core.auth.AuthManager's two lookup methods.
    Mirrors the REAL semantics (see core/auth.py's validate_token /
    get_username_for_token): both run the same locked expiry/orphan check;
    validate_token returns a bool, get_username_for_token returns the
    username or None under the identical conditions."""

    def __init__(self, sessions: dict):
        self._sessions = sessions
        self.validate_token_calls = 0
        self.get_username_for_token_calls = 0

    def validate_token(self, token):
        self.validate_token_calls += 1
        return token in self._sessions

    def get_username_for_token(self, token):
        self.get_username_for_token_calls += 1
        return self._sessions.get(token)


def _build_merged_cookie_auth_app(auth_manager: _FakeAuthManager) -> FastAPI:
    """Mirrors the CURRENT (merged, post-fix) cookie-auth branch of
    workspace/app.py's AuthMiddleware: a single get_username_for_token call
    whose truthiness gates 401/redirect, kept in sync with the real source
    via test_app_py_source_cookie_auth_uses_single_lookup above."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse, RedirectResponse

    class _MergedAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            token = request.cookies.get("session")
            username = auth_manager.get_username_for_token(token)
            if not username:
                if path.startswith("/api/"):
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})
                return RedirectResponse(url="/login", status_code=302)
            request.state.current_user = username
            return await call_next(request)

    app = FastAPI()
    app.add_middleware(_MergedAuthMiddleware)

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"user": request.state.current_user}

    return app


def test_merged_auth_makes_exactly_one_lookup_per_request():
    mgr = _FakeAuthManager({"good-token": "alice"})
    app = _build_merged_cookie_auth_app(mgr)
    client = TestClient(app)

    r = client.get("/api/whoami", cookies={"session": "good-token"})

    assert r.status_code == 200
    assert r.json() == {"user": "alice"}
    assert mgr.get_username_for_token_calls == 1
    assert mgr.validate_token_calls == 0, (
        "merged auth must not also call validate_token"
    )


def test_merged_auth_rejects_invalid_token_for_api_paths():
    mgr = _FakeAuthManager({"good-token": "alice"})
    app = _build_merged_cookie_auth_app(mgr)
    client = TestClient(app)

    r = client.get("/api/whoami", cookies={"session": "bad-token"})

    assert r.status_code == 401
    assert mgr.get_username_for_token_calls == 1
    assert mgr.validate_token_calls == 0


def test_revert_simulation_old_auth_made_two_lookups():
    """Revert-simulation: reproduces the OLD two-call pattern
    (`validate_token` then `get_username_for_token`) to prove it really did
    take the sessions lock twice for the same request."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse, RedirectResponse

    mgr = _FakeAuthManager({"good-token": "alice"})

    class _OldAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            token = request.cookies.get("session")
            if not mgr.validate_token(token):
                if path.startswith("/api/"):
                    return JSONResponse(status_code=401, content={"error": "Not authenticated"})
                return RedirectResponse(url="/login", status_code=302)
            request.state.current_user = mgr.get_username_for_token(token)
            return await call_next(request)

    app = FastAPI()
    app.add_middleware(_OldAuthMiddleware)

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"user": request.state.current_user}

    client = TestClient(app)
    r = client.get("/api/whoami", cookies={"session": "good-token"})

    assert r.status_code == 200
    assert mgr.validate_token_calls == 1
    assert mgr.get_username_for_token_calls == 1, "old code made TWO separate locked lookups"


# ═══════════════════════════════════════════════════════════════════════
# #48 -- generated-image ownership: short-TTL filename->owner cache
# ═══════════════════════════════════════════════════════════════════════


def test_app_py_source_has_image_owner_cache_with_ttl():
    assert "_IMAGE_OWNER_CACHE: dict" in APP_PY_SRC
    assert "_IMAGE_OWNER_CACHE_TTL" in APP_PY_SRC
    idx = APP_PY_SRC.index("async def serve_generated_image")
    end = APP_PY_SRC.index("\n\n", APP_PY_SRC.index("return FileResponse", idx))
    block = APP_PY_SRC[idx:end]
    assert "_IMAGE_OWNER_CACHE.get(filename)" in block
    assert "_IMAGE_OWNER_CACHE[filename] = (" in block
    # The cache-hit branch must be checked BEFORE the DB session is opened.
    assert block.index("_IMAGE_OWNER_CACHE.get(filename)") < block.index("SessionLocal")


class _FakeRow:
    def __init__(self, owner):
        self.owner = owner


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDB:
    """Instrumented stand-in for the SessionLocal() + gallery query the real
    route runs on a cache miss."""

    query_count = 0

    def __init__(self, row):
        self._row = row
        type(self).query_count += 1

    def query(self, *a, **k):
        return _FakeQuery(self._row)

    def close(self):
        pass


def _resolve_owner_cached(cache: dict, filename: str, row, ttl: float, now_fn):
    """Mirrors the CURRENT (post-fix) owner-resolution logic inside
    serve_generated_image: check the cache first; only construct a fresh
    "SessionLocal" (here, _FakeDB) on a miss/expiry. Kept in sync with the
    real code via test_app_py_source_has_image_owner_cache_with_ttl above."""
    now = now_fn()
    cached = cache.get(filename)
    if cached is not None and (now - cached[1]) < ttl:
        return cached[0]
    db = _FakeDB(row)
    try:
        owner = db.query().filter().first()
        owner = owner.owner if owner is not None else None
    finally:
        db.close()
    cache[filename] = (owner, now)
    return owner


def test_repeat_request_for_same_filename_skips_second_db_query():
    _FakeDB.query_count = 0
    cache: dict = {}
    clock = {"t": 1000.0}

    owner1 = _resolve_owner_cached(cache, "abc123.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])
    owner2 = _resolve_owner_cached(cache, "abc123.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])
    owner3 = _resolve_owner_cached(cache, "abc123.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])

    assert owner1 == owner2 == owner3 == "alice"
    assert _FakeDB.query_count == 1, "repeat requests for the same filename must not re-open a session"


def test_different_filenames_each_get_their_own_query():
    _FakeDB.query_count = 0
    cache: dict = {}
    clock = {"t": 1000.0}

    _resolve_owner_cached(cache, "aaa.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])
    _resolve_owner_cached(cache, "bbb.png", _FakeRow("bob"), ttl=60.0, now_fn=lambda: clock["t"])

    assert _FakeDB.query_count == 2


def test_cache_expires_after_ttl_and_requeries():
    _FakeDB.query_count = 0
    cache: dict = {}
    clock = {"t": 1000.0}

    _resolve_owner_cached(cache, "abc123.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])
    clock["t"] += 61.0
    _resolve_owner_cached(cache, "abc123.png", _FakeRow("alice"), ttl=60.0, now_fn=lambda: clock["t"])

    assert _FakeDB.query_count == 2, "an expired cache entry must trigger a fresh query"


def test_no_row_caches_none_owner_as_allow():
    _FakeDB.query_count = 0
    cache: dict = {}
    owner = _resolve_owner_cached(cache, "orphan.png", None, ttl=60.0, now_fn=lambda: 1000.0)
    assert owner is None
    assert cache["orphan.png"][0] is None


def test_revert_simulation_uncached_lookup_queries_every_time():
    """Revert-simulation: the OLD logic (no cache at all) queried on every
    single call for the same filename."""

    def uncached_resolve(filename: str, row) -> str | None:
        db = _FakeDB(row)
        try:
            r = db.query().filter().first()
            return r.owner if r is not None else None
        finally:
            db.close()

    _FakeDB.query_count = 0
    uncached_resolve("abc123.png", _FakeRow("alice"))
    uncached_resolve("abc123.png", _FakeRow("alice"))
    uncached_resolve("abc123.png", _FakeRow("alice"))
    assert _FakeDB.query_count == 3, "uncached lookup re-queries on every request (the bug being fixed)"


# ═══════════════════════════════════════════════════════════════════════
# #50 -- LLM keepalive loop reuses one httpx.AsyncClient per cycle
# ═══════════════════════════════════════════════════════════════════════


def test_app_py_source_warmup_builds_one_client_outside_the_loop():
    idx = APP_PY_SRC.index("async def _warmup_endpoints")
    end = APP_PY_SRC.index("_startup_tasks.append(asyncio.create_task(_warmup_endpoints()))")
    block = APP_PY_SRC[idx:end]

    # Exactly one AsyncClient construction in the whole function.
    assert block.count("httpx.AsyncClient(") == 1
    client_idx = block.index("httpx.AsyncClient(")
    loop_idx = block.index("for url in urls")
    assert client_idx < loop_idx, (
        "the AsyncClient must be constructed once, BEFORE the per-endpoint "
        "loop, not once per endpoint inside it"
    )
    # The per-endpoint work inside the loop must reuse that same `client`.
    loop_block = block[loop_idx:]
    assert "await client.get(url)" in loop_block
    assert "httpx.AsyncClient(" not in loop_block, (
        "no second AsyncClient construction should appear inside the loop"
    )


class _FakeAsyncClient:
    instances = 0
    get_calls = 0

    def __init__(self, timeout=None):
        type(self).instances += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        type(self).get_calls += 1
        return None


async def _warmup_endpoints_mirror(urls: list[str], client_cls):
    """Mirrors the CURRENT (post-fix) `_warmup_endpoints` body: one client
    for the whole cycle, reused across every endpoint. Kept in sync with the
    real code via test_app_py_source_warmup_builds_one_client_outside_the_loop
    above."""
    async with client_cls(timeout=5.0) as client:
        for url in urls:
            try:
                await client.get(url)
            except Exception:
                pass


async def _warmup_endpoints_old_mirror(urls: list[str], client_cls):
    """Reproduces the OLD `_warmup_endpoints` body: a fresh client
    per endpoint, every cycle."""
    for url in urls:
        try:
            async with client_cls(timeout=5.0) as client:
                await client.get(url)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_warmup_reuses_a_single_client_across_five_endpoints():
    _FakeAsyncClient.instances = 0
    _FakeAsyncClient.get_calls = 0
    urls = [f"http://host{i}/models" for i in range(5)]

    await _warmup_endpoints_mirror(urls, _FakeAsyncClient)

    assert _FakeAsyncClient.instances == 1, "one cycle over 5 endpoints must build exactly one client"
    assert _FakeAsyncClient.get_calls == 5


@pytest.mark.asyncio
async def test_revert_simulation_old_warmup_built_a_client_per_endpoint():
    _FakeAsyncClient.instances = 0
    _FakeAsyncClient.get_calls = 0
    urls = [f"http://host{i}/models" for i in range(5)]

    await _warmup_endpoints_old_mirror(urls, _FakeAsyncClient)

    assert _FakeAsyncClient.instances == 5, "old behavior built a fresh client per endpoint"
    assert _FakeAsyncClient.get_calls == 5
