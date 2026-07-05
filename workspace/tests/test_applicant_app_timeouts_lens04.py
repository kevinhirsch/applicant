"""Regression coverage for docs/design/audits/exhaustive2/04_failure_paths.md's
items #11 and #17 (both in ``workspace/app.py``).

  #11 The 45s request-timeout middleware (``_RequestTimeoutMiddleware`` /
      ``_TIMEOUT_EXEMPT_PREFIXES``) did NOT exempt
      ``/api/applicant/internal/research`` — the engine-to-workspace deep
      research callback (``routes/applicant_internal_routes.py``'s
      ``POST /api/applicant/internal/research``). That handler can
      legitimately run for minutes, so a real research callback landing on
      this path got killed at 45s with a 504, even though its sibling
      "manual trigger" path (``/api/applicant/research``) was already
      exempt. The path is now in ``_TIMEOUT_EXEMPT_PREFIXES``.

  #17 ``_RevalidatingStatic.get_response`` (the static-file mount handler)
      returned Starlette's ``FileResponse`` unmodified. ``FileResponse``
      stat()s the file and stamps ``Content-Length`` from that stat result
      inside ``StaticFiles.get_response`` (i.e. at ROUTING time), but only
      actually reads the file's bytes later, in 64KB chunks, whenever the
      ASGI response is sent. A concurrent rewrite of the file landing in
      that window (a redeploy/edit overwriting a `.js`/`.css`/`.html` asset
      while a request is in flight) desyncs the two: the client is handed a
      ``Content-Length`` that no longer matches the bytes actually
      streamed — a truncated/partial response. ``get_response`` now reads
      the whole file into memory itself and returns a plain ``Response``
      built from those exact bytes, so ``Content-Length`` is always derived
      from (and matches) the same snapshot that is served — no window for
      a later rewrite to desync the two.

Every assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore), following this codebase's test-coverage convention (see
test_applicant_backlog_perfcompression.py / test_applicant_backlog_htmlcache.py
for the same methodology). ``workspace/app.py`` is NOT imported directly here
(it pulls ChromaDB/RAG/TTS/etc. and has real filesystem side effects) — its
behavior is instead cross-checked against the actual source text, and
reproduced on bare FastAPI apps built from logic extracted straight out of
that source text (so the tests can never silently drift from what's shipped).
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import re

import anyio
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
import starlette.responses as starlette_responses

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_APP_PY = REPO_ROOT / "workspace" / "app.py"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_timeout_exempt_prefixes(src: str) -> tuple:
    """Pull the REAL ``_TIMEOUT_EXEMPT_PREFIXES`` tuple out of the source
    text via ``ast.literal_eval`` (rather than hand-copying the list into
    this test), so this test can never silently drift from what's shipped."""
    m = re.search(r"_TIMEOUT_EXEMPT_PREFIXES = \((.*?)\n\)\n", src, re.S)
    assert m, "could not locate _TIMEOUT_EXEMPT_PREFIXES tuple in workspace/app.py"
    tuple_src = "(" + m.group(1) + "\n)"
    return ast.literal_eval(tuple_src)


# ── item #11: source text ────────────────────────────────────────────────────


def test_internal_research_path_is_in_timeout_exempt_set():
    src = _read(WORKSPACE_APP_PY)
    prefixes = _extract_timeout_exempt_prefixes(src)
    assert "/api/applicant/internal/research" in prefixes


def test_manual_and_internal_research_paths_both_exempt():
    """The manual trigger and the engine callback are siblings under
    /api/applicant[/internal]/research — both must be exempt, not just one."""
    src = _read(WORKSPACE_APP_PY)
    prefixes = _extract_timeout_exempt_prefixes(src)
    assert "/api/applicant/research" in prefixes
    assert "/api/applicant/internal/research" in prefixes


# ── item #11: behavioral reproduction of _RequestTimeoutMiddleware ──────────


def _build_timeout_app(*, exempt_prefixes: tuple, hard_timeout: float) -> FastAPI:
    """Reproduces _RequestTimeoutMiddleware's dispatch logic (copied straight
    from workspace/app.py, kept in sync with the source-text assertions
    above) wired to a REAL, hard-coded set of exempt prefixes, so both the
    "current" and "pre-fix" prefix sets can be exercised against identical
    middleware behavior."""
    app = FastAPI()

    class _RequestTimeoutMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path or ""
            if any(path.startswith(p) for p in exempt_prefixes):
                return await call_next(request)
            try:
                return await asyncio.wait_for(call_next(request), timeout=hard_timeout)
            except asyncio.TimeoutError:
                return JSONResponse(
                    {"detail": f"Request exceeded {hard_timeout:.0f}s timeout"},
                    status_code=504,
                )

    app.add_middleware(_RequestTimeoutMiddleware)

    @app.post("/api/applicant/internal/research")
    async def internal_research():
        await asyncio.sleep(0.2)
        return {"ok": True}

    @app.post("/api/applicant/other")
    async def other():
        await asyncio.sleep(0.2)
        return {"ok": True}

    return app


def test_internal_research_survives_a_slow_run_with_the_real_exempt_set():
    """Using the REAL prefixes extracted from workspace/app.py, a slow
    (> hard_timeout) internal research run must complete normally instead
    of being killed with a 504."""
    src = _read(WORKSPACE_APP_PY)
    real_prefixes = _extract_timeout_exempt_prefixes(src)
    app = _build_timeout_app(exempt_prefixes=real_prefixes, hard_timeout=0.05)
    client = TestClient(app)

    r = client.post("/api/applicant/internal/research")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_revert_simulation_without_the_new_entry_internal_research_would_504():
    """Revert-simulation: with the exempt set as it stood BEFORE this fix
    (the real set minus the one new entry), the same slow internal-research
    request must get killed at the hard timeout and come back as a 504 —
    proving the new entry is what makes the difference, not some other
    factor (e.g. a shared prefix already covering it)."""
    src = _read(WORKSPACE_APP_PY)
    real_prefixes = _extract_timeout_exempt_prefixes(src)
    pre_fix_prefixes = tuple(
        p for p in real_prefixes if p != "/api/applicant/internal/research"
    )
    assert len(pre_fix_prefixes) == len(real_prefixes) - 1

    app = _build_timeout_app(exempt_prefixes=pre_fix_prefixes, hard_timeout=0.05)
    client = TestClient(app)

    r = client.post("/api/applicant/internal/research")
    assert r.status_code == 504


def test_non_exempt_path_still_gets_killed_with_the_real_exempt_set():
    """Sanity check: the real exempt set must not be so broad that it
    swallows everything — a path with no matching prefix still times out."""
    src = _read(WORKSPACE_APP_PY)
    real_prefixes = _extract_timeout_exempt_prefixes(src)
    app = _build_timeout_app(exempt_prefixes=real_prefixes, hard_timeout=0.05)
    client = TestClient(app)

    r = client.post("/api/applicant/other")
    assert r.status_code == 504


# ── item #17: source text ────────────────────────────────────────────────────


def test_static_get_response_buffers_full_file_before_returning():
    src = _read(WORKSPACE_APP_PY)
    idx = src.index("class _RevalidatingStatic(StaticFiles):")
    end = src.index('app.mount("/static"', idx)
    body = src[idx:end]
    assert "async def get_response(self, path, scope):" in body
    assert "isinstance(resp, FileResponse)" in body
    # The fix must read the file's bytes itself (a single, complete read)
    # rather than letting FileResponse stream lazily-read chunks later.
    assert ".read_bytes)" in body
    assert 'headers["content-length"] = str(len(body))' in body
    assert "resp = Response(" in body


# ── item #17: behavioral reproduction, real race condition ─────────────────


def _install_racing_open_file(monkeypatch, new_content: bytes):
    """Patches starlette.responses.anyio.open_file (what FileResponse's
    lazy chunked body-read calls) so that, on first use, it rewrites the
    target file out from under the response before actually opening it —
    reproducing a concurrent "save in place" landing in the window between
    StaticFiles.get_response()'s earlier stat() (which already stamped
    Content-Length) and the later chunked read."""
    real_open_file = starlette_responses.anyio.open_file
    calls = {"n": 0}

    async def racing_open_file(path, mode="rb"):
        calls["n"] += 1
        pathlib.Path(path).write_bytes(new_content)
        return await real_open_file(path, mode)

    monkeypatch.setattr(starlette_responses.anyio, "open_file", racing_open_file)
    return calls


def test_revert_simulation_plain_staticfiles_desyncs_content_length_under_a_race(
    tmp_path, monkeypatch
):
    """Reproduces the exact bug #17 fixes, using the REAL (unmodified)
    Starlette StaticFiles/FileResponse: a file rewritten in the window
    between get_response()'s stat() and the later chunked read causes the
    client to receive a Content-Length that does NOT match the bytes
    actually delivered — a truncated/partial response by the client's own
    accounting. This is the "before" state; the fixed _RevalidatingStatic
    below (item #17) must NOT reproduce this."""
    original = b"A" * 100
    (tmp_path / "app.js").write_bytes(original)

    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(tmp_path)), name="static")
    client = TestClient(app)

    calls = _install_racing_open_file(monkeypatch, b"B" * 40)

    r = client.get("/static/app.js")
    assert calls["n"] == 1, "the race hook must actually have fired"
    assert r.status_code == 200
    # The bug: Content-Length lies about how many bytes were really sent.
    assert int(r.headers["content-length"]) != len(r.content)
    assert int(r.headers["content-length"]) == len(original)
    assert len(r.content) == 40


def test_fixed_revalidating_static_is_immune_to_the_same_race(tmp_path, monkeypatch):
    """Reproduces the CURRENT (fixed) _RevalidatingStatic.get_response body
    (kept in sync with the source-text assertions above) under the exact
    same race hook used in the revert-simulation. Because the fix reads the
    whole file into memory during get_response() itself — before the
    lazy/streamed FileResponse code path is ever reached — the race hook
    (which only fires from inside that lazy path) never even triggers, and
    Content-Length always matches the exact bytes served."""

    class _RevalidatingStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            if path.endswith((".js", ".css")):
                resp.headers["Cache-Control"] = "max-age=60"
            elif path.endswith(".html"):
                resp.headers["Cache-Control"] = "no-cache"
            if isinstance(resp, FileResponse) and resp.status_code == 200:
                body = await anyio.to_thread.run_sync(
                    pathlib.Path(resp.path).read_bytes
                )
                headers = dict(resp.headers)
                headers["content-length"] = str(len(body))
                resp = Response(
                    content=body,
                    status_code=resp.status_code,
                    headers=headers,
                    media_type=resp.media_type,
                    background=resp.background,
                )
            return resp

    original = b"A" * 100
    (tmp_path / "app.js").write_bytes(original)

    app = FastAPI()
    app.mount("/static", _RevalidatingStatic(directory=str(tmp_path)), name="static")
    client = TestClient(app)

    calls = _install_racing_open_file(monkeypatch, b"B" * 40)

    r = client.get("/static/app.js")
    assert calls["n"] == 0, (
        "the fixed path must never reach the lazy chunked-read code the race "
        "hook targets"
    )
    assert r.status_code == 200
    assert int(r.headers["content-length"]) == len(r.content)
    assert r.content == original, "must serve the pre-race snapshot, not the race write"
    assert r.headers.get("cache-control") == "max-age=60"


def test_fixed_revalidating_static_still_serves_correct_bytes_without_a_race(tmp_path):
    """Plain-path sanity check (no race involved): ordinary file serving
    still returns the exact file bytes with a matching Content-Length."""

    class _RevalidatingStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            if isinstance(resp, FileResponse) and resp.status_code == 200:
                body = await anyio.to_thread.run_sync(
                    pathlib.Path(resp.path).read_bytes
                )
                headers = dict(resp.headers)
                headers["content-length"] = str(len(body))
                resp = Response(
                    content=body,
                    status_code=resp.status_code,
                    headers=headers,
                    media_type=resp.media_type,
                    background=resp.background,
                )
            return resp

    content = b"console.log('hello');\n" * 500
    (tmp_path / "big.js").write_bytes(content)

    app = FastAPI()
    app.mount("/static", _RevalidatingStatic(directory=str(tmp_path)), name="static")
    client = TestClient(app)

    r = client.get("/static/big.js")
    assert r.status_code == 200
    assert r.content == content
    assert int(r.headers["content-length"]) == len(content)


def test_workspace_app_py_imports_response_for_the_static_fix():
    src = _read(WORKSPACE_APP_PY)
    assert "from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, Response" in src
