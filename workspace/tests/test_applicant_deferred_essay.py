"""Regression coverage for resolving a DEFERRED essay screening question from
the front door (dark-engine audit item 21): ``POST /api/applicant/documents/
deferred-essay``.

Phase 2 pre-fill parks essay screening questions it must not auto-answer as
``agent_question`` pending actions (``src/applicant/application/services/
prefill_service.py``'s ``_emit_agent_question``), and the engine already
implements the resolution path (``POST /api/documents/deferred-essay``,
``src/applicant/app/routers/documents.py``) -- generate + route to review,
then clear the originating pending action by its dedup key. Until this
change, nothing in ``workspace/`` reached it: the Portal's ``agent_question``
row only offered a free-text box that resolved the action with the RAW typed
answer, bypassing the classified/filtered/fabrication-gated generation
entirely. This file covers:

  * ``workspace/src/applicant_engine.py`` -- new ``generate_deferred_essay``
    client method.
  * ``workspace/routes/applicant_documents_routes.py`` -- new
    ``POST /deferred-essay`` proxy (``can_use_documents`` privilege, matching
    the other on-demand generation routes in this file).
  * ``workspace/static/js/applicantPortal.js`` -- a "Generate a draft" control
    on ``agent_question`` Portal rows, alongside the existing free-text
    answer box.
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
PORTAL_JS = WORKSPACE_DIR / "static" / "js" / "applicantPortal.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── engine client: generate_deferred_essay ──────────────────────────────────


@pytest.mark.asyncio
async def test_client_generate_deferred_essay_hits_exact_engine_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["json"] = __import__("json").loads(request.content)
        return httpx.Response(201, json={"id": "doc-1", "type": "screening_answer", "approved": False})

    client = ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    )
    body = {
        "campaign_id": "camp-1",
        "application_id": "app-1",
        "true_source": "",
        "label": "Why do you want this role?",
        "question": "Why do you want this role?",
        "selector": "#essay-1",
        "url": "https://boards.example/apply",
    }
    result = await client.generate_deferred_essay(body)
    assert seen["path"] == "/api/documents/deferred-essay"
    assert seen["method"] == "POST"
    assert seen["json"]["selector"] == "#essay-1"
    assert result["id"] == "doc-1"


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

    async def generate_deferred_essay(self, body):
        type(self).last_call = ("generate_deferred_essay", (body,))
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


_BODY = {
    "campaign_id": "camp-1",
    "application_id": "app-1",
    "question": "Why do you want this role?",
    "selector": "#essay-1",
    "url": "https://boards.example/apply",
}


def test_deferred_essay_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"id": "doc-1", "type": "screening_answer", "approved": False})
    resp = _make_client().post("/api/applicant/documents/deferred-essay", json=_BODY)
    assert resp.status_code == 201
    assert resp.json()["id"] == "doc-1"
    name, args = _FakeEngine.last_call
    assert name == "generate_deferred_essay"
    assert args[0]["campaign_id"] == "camp-1"
    assert args[0]["selector"] == "#essay-1"
    # true_source defaults blank so the engine derives the ground truth itself
    # (mirrors CoverLetterIn/ScreeningAnswerIn's precedent in this same file).
    assert args[0]["true_source"] == ""


def test_deferred_essay_requires_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)

    class _Configured:
        is_configured = True

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_documents_routes())
    client = TestClient(app)
    resp = client.post("/api/applicant/documents/deferred-essay", json=_BODY)
    assert resp.status_code == 401


def test_deferred_essay_requires_can_use_documents_privilege():
    class _PrivAuthManager:
        is_configured = True

        def get_privileges(self, _user):
            return {"can_use_documents": False}

    app = FastAPI()
    app.state.auth_manager = _PrivAuthManager()

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = "restricted"
        return await call_next(request)

    app.include_router(setup_applicant_documents_routes())
    client = TestClient(app)
    resp = client.post("/api/applicant/documents/deferred-essay", json=_BODY)
    assert resp.status_code == 403


def test_deferred_essay_engine_error_translates_to_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("down", is_timeout=True))
    resp = _make_client().post("/api/applicant/documents/deferred-essay", json=_BODY)
    assert resp.status_code == 502


# ── front-end: "Generate a draft" control on agent_question Portal rows ────


def _render_answer_body() -> str:
    src = _read(PORTAL_JS)
    fn = re.search(r"function _renderAnswer\(item\) \{.*?\n\}", src, re.S)
    assert fn, "expected the _renderAnswer(item) renderer"
    return fn.group(0)


def test_render_answer_offers_generate_draft_for_agent_questions():
    body = _render_answer_body()
    assert "applicant-portal-generate-essay" in body
    assert "item.kind === 'agent_question'" in body


def test_generate_essay_handler_posts_to_the_deferred_essay_proxy():
    src = _read(PORTAL_JS)
    handler = re.search(
        r"applicant-portal-generate-essay'\)\.forEach\(\(btn\) => \{.*?\n  \}\);", src, re.S
    )
    assert handler, "expected the generate-essay click handler"
    assert "/api/applicant/documents/deferred-essay" in handler.group(0)
    assert "campaign_id: campaignId" in handler.group(0)
    assert "application_id: applicationId" in handler.group(0)
