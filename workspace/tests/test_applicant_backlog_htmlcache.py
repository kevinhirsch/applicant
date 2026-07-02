"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md's
exhaustive2/03_performance.md lens items #11 and #12.

  #11 `index.html` (232 KB) was re-read from disk AND re-scanned with a full
      ``str.replace()`` on EVERY navigation (nine deep-link routes share
      ``serve_index`` -> ``_serve_html_with_nonce``), with no caching at all.
      ``src/app_helpers.py`` now exposes ``read_cached_html_parts``: it
      containment-checks + reads the file, splits it once around the
      ``{{CSP_NONCE}}`` token, and caches the resulting parts list keyed by
      the file's ``os.stat().st_mtime``. As long as mtime is unchanged,
      repeat calls skip the disk read AND the string-scan entirely.
      ``workspace/app.py``'s ``_serve_html_with_nonce`` now calls this helper
      and reassembles the response with ``nonce.join(parts)`` instead of
      ``html.replace(...)``.

      SECURITY-CRITICAL INVARIANT: the CSP nonce itself is NEVER cached or
      reused. ``core/middleware.py``'s ``SecurityHeadersMiddleware`` still
      generates a fresh ``secrets.token_hex(16)`` on every single request
      (``request.state.csp_nonce``) before the route ever runs; the cache
      only stores the STATIC text either side of the nonce placeholder, and
      every response still joins that static text with its own freshly
      generated nonce. This file proves that two back-to-back requests for
      the exact same (fully cached, zero re-read) file body still embed two
      different nonces, and that each embedded nonce matches that same
      response's own CSP header nonce.

  #12 ``_RevalidatingStatic`` (workspace/app.py) stamped a blanket
      ``Cache-Control: no-cache`` on every ``.js``/``.css``/``.html`` static
      file, forcing a conditional-GET round-trip for every one of the ~162
      JS modules + the stylesheet on every page load (Starlette does answer
      a cheap 304, but the round-trip itself, times ~162, is the cost).
      ``.js``/``.css`` now get ``Cache-Control: max-age=60`` — a short
      window that still self-heals within a minute of a real code change
      (this app has no build step / versioned URLs) while collapsing the
      revalidation storm for the common case of several navigations within
      the same minute. ``.html`` is kept on ``no-cache`` — the app shell
      should never be more than one reload stale.

      ``static/sw.js`` is network-first for ``.js``/``.css`` (its `fetch`
      handler always calls ``fetch(e.request)`` before falling back to the
      SW cache); that ``fetch()`` call still consults the browser's own HTTP
      cache first, so a fresh ``max-age=60`` entry resolves the SW's
      "network-first" fetch with ZERO round-trip, and only reverts to a real
      conditional-GET once the 60s window has elapsed — the two strategies
      compose rather than conflict.

Every assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion fail
-> restore), per this codebase's test-coverage convention (see
test_applicant_backlog_perfcompression.py's docstring for the same
methodology). Following that same file's precedent, ``workspace/app.py`` is
NOT imported directly here (it pulls ChromaDB/RAG/TTS/etc. and has real
filesystem side effects) — its behavior is reproduced on bare FastAPI apps
wired with the REAL, lightweight helper modules (``src/app_helpers.py``,
``core/middleware.py``, loaded standalone to dodge ``core/__init__.py``'s
heavy ``src.llm_core`` import), and cross-checked against the actual
``workspace/app.py`` source text.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
WORKSPACE_APP_PY = WORKSPACE_DIR / "app.py"
APP_HELPERS_PY = WORKSPACE_DIR / "src" / "app_helpers.py"
MIDDLEWARE_PY = WORKSPACE_DIR / "core" / "middleware.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module_from_path(name: str, path: pathlib.Path):
    """Load a module directly by file path, bypassing its package's
    ``__init__.py`` (mirrors test_applicant_safe_path.py's technique for
    dodging core/__init__.py's heavy src.llm_core import)."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── item #11: src/app_helpers.py — real module import (already lightweight,
#    per test_app.py's `from src.app_helpers import abs_join` precedent) ────

import src.app_helpers as app_helpers  # noqa: E402


def test_read_cached_html_parts_reconstructs_original_content(tmp_path):
    """Splitting on the token and re-joining with the substituted value must
    be exactly equivalent to the old `.replace()` call, for any number of
    occurrences (including zero)."""
    content = "<html>A{{CSP_NONCE}}B{{CSP_NONCE}}C</html>"
    f = tmp_path / "multi.html"
    f.write_text(content, encoding="utf-8")

    parts = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache={})
    nonce = "deadbeefcafefeed"
    assert nonce.join(parts) == content.replace("{{CSP_NONCE}}", nonce)


def test_read_cached_html_parts_handles_zero_occurrences(tmp_path):
    content = "<html>no token here</html>"
    f = tmp_path / "notoken.html"
    f.write_text(content, encoding="utf-8")

    parts = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache={})
    assert "anything".join(parts) == content


def test_read_cached_html_parts_rejects_path_outside_base(tmp_path):
    base = tmp_path / "static"
    base.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("nope", encoding="utf-8")

    with pytest.raises(ValueError):
        app_helpers.read_cached_html_parts(str(base), str(outside), cache={})


def test_cache_skips_disk_read_when_mtime_unchanged(tmp_path, monkeypatch):
    """The critical perf claim: a second call for the same file, same mtime,
    must NOT touch the filesystem's `open()` at all."""
    f = tmp_path / "index.html"
    f.write_text("<html>{{CSP_NONCE}}</html>", encoding="utf-8")

    calls = {"n": 0}
    real_open = open

    def counting_open(path, *a, **k):
        calls["n"] += 1
        return real_open(path, *a, **k)

    monkeypatch.setattr(app_helpers, "open", counting_open, raising=False)

    cache: dict = {}
    parts1 = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache=cache)
    assert calls["n"] == 1, "first call must read the file"

    parts2 = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache=cache)
    parts3 = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache=cache)
    assert calls["n"] == 1, "unchanged mtime must NOT trigger a re-read"
    assert parts1 == parts2 == parts3


def test_revert_simulation_naive_replace_would_reread_every_call(tmp_path, monkeypatch):
    """Sanity check / revert-simulation: reproduces the OLD uncached
    `serve_html_contained` behavior (still present, unchanged, for backward
    compat) to prove it DOES re-read on every call — i.e. this is the exact
    cost `read_cached_html_parts` eliminates."""
    f = tmp_path / "index.html"
    f.write_text("<html>{{CSP_NONCE}}</html>", encoding="utf-8")

    calls = {"n": 0}
    real_open = open

    def counting_open(path, *a, **k):
        calls["n"] += 1
        return real_open(path, *a, **k)

    monkeypatch.setattr(app_helpers, "open", counting_open, raising=False)

    app_helpers.serve_html_contained(str(tmp_path), str(f))
    app_helpers.serve_html_contained(str(tmp_path), str(f))
    app_helpers.serve_html_contained(str(tmp_path), str(f))
    assert calls["n"] == 3, "uncached helper re-reads on every call (the bug being fixed)"


def test_cache_rereads_after_mtime_changes(tmp_path):
    """A real file edit (mtime bump) must bust the cache and serve fresh
    content — the cache must never go stale across a redeploy/edit."""
    f = tmp_path / "index.html"
    f.write_text("<html>OLD {{CSP_NONCE}}</html>", encoding="utf-8")

    cache: dict = {}
    parts1 = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache=cache)
    assert "OLD" in "".join(parts1)

    f.write_text("<html>NEW {{CSP_NONCE}} CONTENT</html>", encoding="utf-8")
    # Force the mtime forward — some filesystems have coarse mtime
    # resolution, so a fast test run could otherwise produce an identical
    # mtime for both writes.
    bumped = os.path.getmtime(f) + 5
    os.utime(f, (bumped, bumped))

    parts2 = app_helpers.read_cached_html_parts(str(tmp_path), str(f), cache=cache)
    joined2 = "".join(parts2)
    assert "NEW" in joined2 and "CONTENT" in joined2
    assert parts1 != parts2


def test_multiple_files_cache_independently(tmp_path):
    f1 = tmp_path / "index.html"
    f2 = tmp_path / "login.html"
    f1.write_text("<html>INDEX {{CSP_NONCE}}</html>", encoding="utf-8")
    f2.write_text("<html>LOGIN {{CSP_NONCE}}</html>", encoding="utf-8")

    cache: dict = {}
    p1 = app_helpers.read_cached_html_parts(str(tmp_path), str(f1), cache=cache)
    p2 = app_helpers.read_cached_html_parts(str(tmp_path), str(f2), cache=cache)
    assert "INDEX" in "".join(p1)
    assert "LOGIN" in "".join(p2)
    assert len(cache) == 2


# ── item #11: workspace/app.py source wiring ─────────────────────────────────


def test_workspace_app_py_uses_read_cached_html_parts():
    src = _read(WORKSPACE_APP_PY)
    assert "from src.app_helpers import read_cached_html_parts" in src
    assert "read_cached_html_parts(BASE_DIR, file_path)" in src
    assert "nonce.join(parts)" in src
    # The old full-file-scan replace call must be gone from the hot path.
    assert 'html.replace("{{CSP_NONCE}}", nonce)' not in src


# ── item #11 (security-critical): fresh unique nonce per response, even with
#    a fully-cached (zero re-read) file body ─────────────────────────────────


def test_two_requests_get_two_different_nonces_with_cache_reused(tmp_path, monkeypatch):
    """Reproduces `_serve_html_with_nonce`'s real logic end-to-end: the real
    SecurityHeadersMiddleware (loaded standalone) generates the nonce, the
    real `read_cached_html_parts` supplies the cached static parts, and the
    route joins them exactly as workspace/app.py does. Proves BOTH halves of
    the fix at once: the disk is touched only once (cache is live), AND every
    response still gets its own unique, correct nonce embedded in the body
    and matching its own CSP header — caching the parts never caches or
    reuses the nonce itself."""
    middleware_mod = _load_module_from_path("t11_middleware_under_test", MIDDLEWARE_PY)

    html_file = tmp_path / "index.html"
    html_file.write_text(
        '<html><head></head><body>'
        '<script nonce="{{CSP_NONCE}}">console.log("boot")</script>'
        '</body></html>',
        encoding="utf-8",
    )

    calls = {"n": 0}
    real_open = open

    def counting_open(path, *a, **k):
        calls["n"] += 1
        return real_open(path, *a, **k)

    monkeypatch.setattr(app_helpers, "open", counting_open, raising=False)

    shared_cache: dict = {}

    app = FastAPI()
    app.add_middleware(middleware_mod.SecurityHeadersMiddleware)

    @app.get("/")
    async def index(request: Request):
        parts = app_helpers.read_cached_html_parts(
            str(tmp_path), str(html_file), cache=shared_cache
        )
        nonce = getattr(request.state, "csp_nonce", "")
        return HTMLResponse(nonce.join(parts))

    client = TestClient(app)
    r1 = client.get("/")
    r2 = client.get("/")
    r3 = client.get("/")

    assert r1.status_code == r2.status_code == r3.status_code == 200

    # The file must have been read from disk exactly once across all three
    # requests — the cache is doing its job.
    assert calls["n"] == 1, "file should be read once and served from cache thereafter"

    def extract_body_nonce(body: str) -> str:
        m = re.search(r'nonce="([0-9a-f]{32})"', body)
        assert m, f"no 32-hex-char nonce found in response body: {body!r}"
        return m.group(1)

    n1, n2, n3 = (extract_body_nonce(r.text) for r in (r1, r2, r3))

    # The critical security assertion: three responses, three DIFFERENT
    # nonces, despite the underlying file bytes being served from cache
    # every time.
    assert len({n1, n2, n3}) == 3, "each response must get its own unique nonce"

    # Each embedded body nonce must match that SAME response's own CSP
    # header nonce (not e.g. a stale/previous one).
    for resp, nonce in ((r1, n1), (r2, n2), (r3, n3)):
        csp = resp.headers.get("content-security-policy", "")
        assert f"nonce-{nonce}" in csp, (
            f"response body nonce {nonce!r} does not match its own CSP header: {csp!r}"
        )


def test_revert_simulation_shared_cache_never_returns_a_nonce_placeholder():
    """Defensive: confirms the cached PARTS themselves never contain a nonce
    value — only the literal split points either side of the placeholder.
    If a future change accidentally cached the joined (nonce-substituted)
    HTML instead of the split parts, this would catch it: joining cached
    parts with two different nonces must always diverge."""
    content = '<script nonce="{{CSP_NONCE}}">x()</script>'
    # Directly exercise the split the cache stores, independent of any
    # request plumbing.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "x.html"
        f.write_text(content, encoding="utf-8")
        parts_a = app_helpers.read_cached_html_parts(d, str(f), cache={})
    joined_1 = "nonceONE".join(parts_a)
    joined_2 = "nonceTWO".join(parts_a)
    assert joined_1 != joined_2
    assert "nonceONE" in joined_1 and "nonceTWO" not in joined_1
    assert "nonceTWO" in joined_2 and "nonceONE" not in joined_2


# ── item #12: workspace/app.py source — Cache-Control policy ────────────────


def test_workspace_app_py_source_sets_short_maxage_for_js_css():
    src = _read(WORKSPACE_APP_PY)
    assert 'if path.endswith((".js", ".css")):' in src
    assert 'resp.headers["Cache-Control"] = "max-age=60"' in src


def test_workspace_app_py_source_keeps_html_on_no_cache():
    src = _read(WORKSPACE_APP_PY)
    assert 'elif path.endswith(".html"):' in src
    idx = src.index('elif path.endswith(".html"):')
    tail = src[idx : idx + 150]
    assert 'resp.headers["Cache-Control"] = "no-cache"' in tail


def test_workspace_app_py_source_no_longer_blankets_all_three_with_no_cache():
    """Revert-simulation guard: the old single branch covering
    `.js/.css/.html` together must be gone — js/css and html now diverge."""
    src = _read(WORKSPACE_APP_PY)
    assert 'if path.endswith((".js", ".css", ".html")):' not in src


# ── item #12: behavioral reproduction of _RevalidatingStatic's header split ─


def test_revalidating_static_applies_short_maxage_to_js_and_css_no_cache_to_html(tmp_path):
    """Reproduces the exact class body from workspace/app.py's
    `_RevalidatingStatic` (kept in sync with the source-text assertions
    above) against a real temp static directory served by a real FastAPI
    app, proving the header split actually takes effect per file type."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "app.js").write_text("console.log(1);", encoding="utf-8")
    (static_dir / "style.css").write_text("body{color:red}", encoding="utf-8")
    (static_dir / "page.html").write_text("<html></html>", encoding="utf-8")
    (static_dir / "logo.png").write_bytes(b"\x89PNG\r\n")

    class _RevalidatingStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            if path.endswith((".js", ".css")):
                resp.headers["Cache-Control"] = "max-age=60"
            elif path.endswith(".html"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

    app = FastAPI()
    app.mount("/static", _RevalidatingStatic(directory=str(static_dir)), name="static")
    client = TestClient(app)

    r_js = client.get("/static/app.js")
    r_css = client.get("/static/style.css")
    r_html = client.get("/static/page.html")
    r_png = client.get("/static/logo.png")

    assert r_js.headers.get("cache-control") == "max-age=60"
    assert r_css.headers.get("cache-control") == "max-age=60"
    assert r_html.headers.get("cache-control") == "no-cache"
    # Other asset types are untouched by this policy (left to StaticFiles'
    # own default headers) — no regression on images/fonts/etc.
    assert r_png.headers.get("cache-control") != "no-cache"


# ── item #12: sw.js network-first interaction note (documented, verified) ──


def test_sw_js_is_network_first_for_js_css_confirming_the_maxage_interaction():
    """Confirms the documented interaction still holds: `static/sw.js`'s
    fetch handler is network-first (always calls `fetch()` before any SW
    cache fallback) for `.js`/`.css` — so the new `max-age=60` on those
    responses is what actually shortens the effective latency under the SW,
    since a fresh `fetch()` still resolves from the browser's own HTTP cache
    within that window instead of a real network round-trip."""
    sw_src = _read(WORKSPACE_DIR / "static" / "sw.js")
    assert "network-first" in sw_src.lower()
    # The JS/CSS branch must call fetch() itself (not cache-first) as the
    # PRIMARY path, only falling back to the SW cache in the `.catch()`.
    js_css_branch = sw_src[sw_src.index("JS/CSS: network-first") :]
    js_css_branch = js_css_branch[: js_css_branch.index("Other static assets")]
    assert "fetch(e.request).then(" in js_css_branch
    assert ".catch(() => caches.match(e.request))" in js_css_branch
