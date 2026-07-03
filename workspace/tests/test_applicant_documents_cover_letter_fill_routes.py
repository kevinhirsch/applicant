"""Hermetic tests for the cover-letter template merge-fill proxy route (dark-engine
audit item 41; ``POST /api/applicant/documents/cover-letter/fill`` in
``routes/applicant_documents_routes.py``).

Zero network: the engine client is replaced with a fake async-context-manager,
mirroring ``test_applicant_documents_routes.py``'s pattern. Complementary to the
on-demand LLM cover-letter draft already covered there -- this route wraps the
engine's deterministic ``fill_cover_letter_template`` (no LLM, no fabrication risk).
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from src.applicant_engine import ApplicantEngineClient, EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient — records the call and returns/raises
    a canned result, used as an async context manager like the real client."""

    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fill_cover_letter_template(self, body):
        type(self).last_call = ("fill_cover_letter_template", (body,))
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

    app.include_router(setup_applicant_documents_routes())
    return TestClient(app)


# ── the real client method (no fake -- httpx.MockTransport) ─────────────────
# Mirrors ``test_applicant_engine.py``'s pattern: exercises the ACTUAL
# ``ApplicantEngineClient.fill_cover_letter_template`` request-building, not the
# fake used by the route tests above (which would still pass if the real client
# method were ever removed/renamed).


@pytest.mark.asyncio
async def test_client_fill_cover_letter_template_posts_to_engine_route():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode() if request.content else ""
        return httpx.Response(200, json={"filled": "Dear Acme,"})

    async with ApplicantEngineClient(
        base_url="http://api:8000", transport=httpx.MockTransport(handler)
    ) as engine:
        data = await engine.fill_cover_letter_template(
            {"template": "Dear {{company}},", "context": {"company": "Acme"}}
        )

    assert data == {"filled": "Dear Acme,"}
    assert captured["url"] == "http://api:8000/api/documents/cover-letter/fill"
    assert captured["method"] == "POST"
    assert '"template"' in captured["body"] and '"Acme"' in captured["body"]


# ── happy path ────────────────────────────────────────────────────────────


def test_fill_forwards_template_and_context(monkeypatch):
    _patch_engine(monkeypatch, result={"filled": "Dear Acme, I am applying for Engineer."})
    resp = _make_client().post(
        "/api/applicant/documents/cover-letter/fill",
        json={
            "template": "Dear {{company}}, I am applying for {{role}}.",
            "context": {"company": "Acme", "role": "Engineer"},
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"filled": "Dear Acme, I am applying for Engineer."}
    name, args = _FakeEngine.last_call
    assert name == "fill_cover_letter_template"
    assert args[0]["template"] == "Dear {{company}}, I am applying for {{role}}."
    assert args[0]["context"] == {"company": "Acme", "role": "Engineer"}


def test_fill_defaults_context_to_empty_dict(monkeypatch):
    _patch_engine(monkeypatch, result={"filled": "Dear ,"})
    resp = _make_client().post(
        "/api/applicant/documents/cover-letter/fill",
        json={"template": "Dear {{company}},"},
    )
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert args[0]["context"] == {}


# ── error translation (mirrors the other on-demand generation routes) ───────


def test_fill_engine_error_translates_to_502(monkeypatch):
    err = EngineError("connection refused")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post(
        "/api/applicant/documents/cover-letter/fill",
        json={"template": "Dear {{company}},", "context": {}},
    )
    assert resp.status_code == 502


# ── auth / privilege gates ───────────────────────────────────────────────────


def test_fill_requires_authentication(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()

    class _Configured:
        is_configured = True

    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_documents_routes())
    client = TestClient(app)

    resp = client.post(
        "/api/applicant/documents/cover-letter/fill",
        json={"template": "Dear {{company}},", "context": {}},
    )
    assert resp.status_code == 401


def test_fill_requires_can_use_documents_privilege(monkeypatch):
    """Matches the other on-demand generation routes: it still produces
    application material, so it requires the write privilege, not just a login."""

    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})

    resp = client.post(
        "/api/applicant/documents/cover-letter/fill",
        json={"template": "Dear {{company}},", "context": {}},
    )
    assert resp.status_code == 403


def test_fill_allowed_with_can_use_documents_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"filled": "Dear Acme,"})
    client = _make_priv_client({"can_use_documents": True})

    resp = client.post(
        "/api/applicant/documents/cover-letter/fill",
        json={"template": "Dear {{company}},", "context": {"company": "Acme"}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"filled": "Dear Acme,"}
