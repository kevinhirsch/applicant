"""Regression coverage for the standalone redline-render proxy (dark-engine
audit item 22): ``POST /api/applicant/documents/redline``.

The engine's ``POST /api/documents/redline`` (``src/applicant/app/routers/
documents.py``) is a pure, stateless line-diff of two caller-supplied text
blobs (``MaterialService.render_redline`` -> the LaTeX/docx tailor's
``difflib``-based diff -- confirmed the ``variant_id`` argument is unused by
the diff itself, just carried as a label) with NO workspace proxy at all.

This closes a real gap, not a redundant one: the review session's own
``redline_state`` (``RevisionSession.redline_state``, set by
``MaterialService.apply_turn``) only ever stores ``{"content": ...}`` -- it
never populates ``rendered_html``/``additions``/``subtractions`` in any
production code path (grepped: the only place those keys are set is the dev
fixture ``dev_seed.py``). So ``documentLibrary.js``'s "PRIMARY" highlighted
redline render was dead code until this endpoint is wired -- there was no
other source of a real diff anywhere in the product. This file covers:

  * ``workspace/src/applicant_engine.py`` -- new ``render_redline`` client
    method.
  * ``workspace/routes/applicant_documents_routes.py`` -- new
    ``POST /redline`` proxy (read-only auth tier, matching ``jd_match`` in
    this same file -- no persistence, just a computation over caller strings).
  * ``workspace/static/js/documentLibrary.js`` -- a "Compare to original"
    control on the résumé-variant review panel that renders the real diff
    once a turn has changed the content.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from src.applicant_engine import ApplicantEngineClient, EngineError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
DOC_LIBRARY_JS = WORKSPACE_DIR / "static" / "js" / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: render_redline ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_render_redline_hits_exact_engine_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(
            200,
            json={
                "variant_id": "var-1",
                "additions": ["new line"],
                "subtractions": ["old line"],
                "rendered_html": "<div>diff</div>",
            },
        )

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    result = await client.render_redline(
        {"variant_id": "var-1", "base_source": "old line", "new_source": "new line"}
    )
    assert seen["path"] == "/api/documents/redline"
    assert seen["method"] == "POST"
    assert result["rendered_html"] == "<div>diff</div>"


# ── workspace proxy route ───────────────────────────────────────────────────


class _FakeEngine:
    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def render_redline(self, body):
        type(self).last_call = ("render_redline", (body,))
        if self._error is not None:
            raise self._error
        return self._result


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        docs_routes,
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
    app.include_router(setup_applicant_documents_routes())
    return TestClient(app, raise_server_exceptions=True)


_BODY = {"variant_id": "var-1", "base_source": "old", "new_source": "new"}


def test_redline_maps_to_engine(monkeypatch):
    _patch_engine(
        monkeypatch,
        result={"variant_id": "var-1", "additions": ["new"], "subtractions": ["old"], "rendered_html": "<div></div>"},
    )
    resp = _make_client().post("/api/applicant/documents/redline", json=_BODY)
    assert resp.status_code == 200
    assert resp.json()["rendered_html"] == "<div></div>"
    name, args = _FakeEngine.last_call
    assert name == "render_redline"
    assert args[0]["variant_id"] == "var-1"
    assert args[0]["aggressiveness"] == 20  # default carried through


def test_redline_requires_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)

    class _Configured:
        is_configured = True

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_documents_routes())
    client = TestClient(app)
    resp = client.post("/api/applicant/documents/redline", json=_BODY)
    assert resp.status_code == 401


def test_redline_engine_error_translates_to_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down", is_timeout=True))
    resp = _make_client().post("/api/applicant/documents/redline", json=_BODY)
    assert resp.status_code == 502


# ── front-end: "Compare to original" control on the review panel ──────────


def _render_review_body() -> str:
    src = _read(DOC_LIBRARY_JS)
    fn = re.search(
        r"function _renderApplicantReview\(item, appId, panel, session, card, results\) \{.*?\n    \}\n",
        src,
        re.S,
    )
    assert fn, "expected the _renderApplicantReview(...) renderer"
    return fn.group(0)


def test_review_panel_offers_compare_to_original_control():
    body = _render_review_body()
    assert "Compare to original" in body
    assert "doclib-compare" not in body  # no stray leftover class name from drafting


def test_compare_control_posts_to_the_redline_proxy():
    body = _render_review_body()
    assert "${_APPLICANT_BASE}/redline" in body
    assert "variant_id: item.id" in body


def test_compare_control_is_gated_to_resume_variants_with_a_real_change():
    body = _render_review_body()
    assert "isVariant && originalContent && currentContent && currentContent !== originalContent" in body
