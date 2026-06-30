"""Hermetic tests for the Applicant DOCUMENTS proxy (routes/applicant_documents_routes.py).

Zero network: the engine client is replaced with a fake async-context-manager so
every route is exercised without an engine. Covers the happy path (engine JSON
passed through), the typed-error translation (timeout -> 502, HTTP status passed
through), request-body forwarding for the change loop, and the auth gate.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_documents_routes as docs_routes
from routes.applicant_documents_routes import setup_applicant_documents_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    """Stand-in for ApplicantEngineClient.

    Records the (method, args) of the call made and returns a canned result, or
    raises a canned EngineError. Used as an async context manager exactly like
    the real client (``async with ApplicantEngineClient() as engine``).
    """

    last_call = None  # class-level so the test can read it after the request

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _dispatch(self, name, *args):
        type(self).last_call = (name, args)
        if self._error is not None:
            raise self._error
        return self._result

    # Each engine method the proxy uses, all routed through _dispatch.
    async def list_documents(self):
        return await self._dispatch("list_documents")

    async def documents_for_application(self, application_id):
        return await self._dispatch("documents_for_application", application_id)

    async def list_variants(self, campaign_id):
        return await self._dispatch("list_variants", campaign_id)

    async def generate_cover_letter(self, body):
        return await self._dispatch("generate_cover_letter", body)

    async def generate_screening_answer(self, body):
        return await self._dispatch("generate_screening_answer", body)

    async def review_document(self, document_id):
        return await self._dispatch("review_document", document_id)

    async def turn_document(self, document_id, body):
        return await self._dispatch("turn_document", document_id, body)

    async def approve_document(self, document_id):
        return await self._dispatch("approve_document", document_id)

    async def decline_document(self, document_id):
        return await self._dispatch("decline_document", document_id)

    async def approve_variant(self, variant_id):
        return await self._dispatch("approve_variant", variant_id)

    async def set_document_aggressiveness(self, value):
        return await self._dispatch("set_document_aggressiveness", value)

    async def get_banned_phrases(self):
        return await self._dispatch("get_banned_phrases")

    async def set_banned_phrases(self, phrases):
        return await self._dispatch("set_banned_phrases", phrases)


def _make_client(*, authed: bool = True):
    """Bare app with only the documents router mounted.

    When ``authed`` is True a tiny middleware sets ``request.state.current_user``
    the same way the real auth middleware does, so ``require_user`` passes
    without standing up the full auth stack.
    """
    app = FastAPI()

    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)

    app.include_router(setup_applicant_documents_routes())
    return TestClient(app, raise_server_exceptions=True)


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        docs_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(result=result, error=error),
    )


# ── happy path ────────────────────────────────────────────────────────────


def test_library_passes_engine_json_through(monkeypatch):
    payload = {"surface": "documents", "items": [{"id": "d1"}]}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/documents/library")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("list_documents", ())


def test_application_documents_forwards_path_param(monkeypatch):
    _patch_engine(monkeypatch, result={"application_id": "app-7", "items": []})
    resp = _make_client().get("/api/applicant/documents/applications/app-7")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("documents_for_application", ("app-7",))


def test_application_documents_passes_provenance_through(monkeypatch):
    """The advisory "What I drew on" provenance (FR-MIND-5/-11, FR-OBS-2) rides
    on each material and reaches the review UI unchanged through the proxy."""
    payload = {
        "application_id": "app-7",
        "items": [
            {
                "id": "doc-1",
                "type": "cover_letter",
                "approved": False,
                "content": "Dear hiring team,",
                "provenance": [
                    {"kind": "memory", "label": "your preference for concise bullets", "ref": "..."},
                    {"kind": "playbook", "label": "the 'acme-tone' playbook", "ref": "acme-tone"},
                ],
            }
        ],
        "all_approved": False,
    }
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/documents/applications/app-7")
    assert resp.status_code == 200
    assert resp.json() == payload
    prov = resp.json()["items"][0]["provenance"]
    assert {p["kind"] for p in prov} == {"memory", "playbook"}


def test_variant_library_forwards_campaign_and_passes_through(monkeypatch):
    payload = {"campaign_id": "camp-3", "variants": [{"variant_id": "v1", "is_root": True}]}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/documents/variants/camp-3")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("list_variants", ("camp-3",))


def test_variant_library_requires_auth(monkeypatch):
    _patch_engine(monkeypatch, result={"variants": []})
    resp = _make_client(authed=False).get("/api/applicant/documents/variants/camp-3")
    assert resp.status_code in (401, 403)


def test_cover_letter_generation_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result={"generated": True, "id": "doc-9", "type": "cover_letter"})
    resp = _make_client().post(
        "/api/applicant/documents/cover-letter",
        json={"campaign_id": "c1", "application_id": "a1"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "doc-9"
    name, args = _FakeEngine.last_call
    assert name == "generate_cover_letter"
    # No true_source goes over the wire — the engine derives it from the profile.
    assert "true_source" not in args[0]
    assert args[0]["campaign_id"] == "c1" and args[0]["application_id"] == "a1"


def test_screening_answer_generation_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result={"id": "doc-10", "type": "screening_answer"})
    resp = _make_client().post(
        "/api/applicant/documents/screening-answer",
        json={"campaign_id": "c1", "application_id": "a1", "question": "Why us?"},
    )
    assert resp.status_code == 201
    name, args = _FakeEngine.last_call
    assert name == "generate_screening_answer"
    assert args[0]["question"] == "Why us?"
    assert "true_source" not in args[0]


def test_open_review(monkeypatch):
    _patch_engine(monkeypatch, result={"session_id": "s1", "redline_state": {}})
    resp = _make_client().post("/api/applicant/documents/doc-1/review")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "s1"
    assert _FakeEngine.last_call == ("review_document", ("doc-1",))


def test_turn_forwards_body(monkeypatch):
    _patch_engine(monkeypatch, result={"status": "in_review"})
    body = {"kind": "subtract", "instruction": "trim the summary", "true_source": "CV text"}
    resp = _make_client().post("/api/applicant/documents/doc-9/turn", json=body)
    assert resp.status_code == 200
    name, args = _FakeEngine.last_call
    assert name == "turn_document"
    assert args[0] == "doc-9"
    assert args[1] == body


def test_turn_defaults_when_body_omitted(monkeypatch):
    _patch_engine(monkeypatch, result={"status": "in_review"})
    resp = _make_client().post("/api/applicant/documents/doc-9/turn", json={})
    assert resp.status_code == 200
    _, args = _FakeEngine.last_call
    assert args[1] == {"kind": "free_text", "instruction": "", "true_source": None}


def test_approve_decline_variant(monkeypatch):
    _patch_engine(monkeypatch, result={"id": "doc-1", "approved": True})
    client = _make_client()
    assert client.post("/api/applicant/documents/doc-1/approve").status_code == 200
    assert _FakeEngine.last_call == ("approve_document", ("doc-1",))

    _patch_engine(monkeypatch, result={"id": "doc-1", "approved": False})
    assert client.post("/api/applicant/documents/doc-1/decline").status_code == 200
    assert _FakeEngine.last_call == ("decline_document", ("doc-1",))

    _patch_engine(monkeypatch, result={"id": "var-1", "approved": True})
    assert client.post("/api/applicant/documents/variants/var-1/approve").status_code == 200
    assert _FakeEngine.last_call == ("approve_variant", ("var-1",))


def test_aggressiveness_forwards_value(monkeypatch):
    _patch_engine(monkeypatch, result={"aggressiveness": 42, "dormant_ui": False})
    resp = _make_client().post(
        "/api/applicant/documents/aggressiveness", json={"aggressiveness": 42}
    )
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("set_document_aggressiveness", (42,))


# ── banned phrases (FR-RESUME-5) ─────────────────────────────────────────────


def test_banned_phrases_get_passes_through(monkeypatch):
    payload = {"phrases": ["circle back"], "seed_phrases": ["delve into"]}
    _patch_engine(monkeypatch, result=payload)
    resp = _make_client().get("/api/applicant/documents/banned-phrases")
    assert resp.status_code == 200
    assert resp.json() == payload
    assert _FakeEngine.last_call == ("get_banned_phrases", ())


def test_banned_phrases_set_forwards_list(monkeypatch):
    _patch_engine(monkeypatch, result={"phrases": ["circle back"], "seed_phrases": []})
    resp = _make_client().post(
        "/api/applicant/documents/banned-phrases", json={"phrases": ["circle back"]}
    )
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("set_banned_phrases", (["circle back"],))


# ── error translation ───────────────────────────────────────────────────────


def test_engine_http_status_is_passed_through(monkeypatch):
    """A 409 review-required from the engine surfaces as a 409 to the UI."""
    err = EngineError("review required", status=409, detail="approve cover letter first")
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().post("/api/applicant/documents/doc-1/approve")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "engine_error"
    assert body["engine_status"] == 409
    assert body["detail"] == "approve cover letter first"


def test_engine_timeout_becomes_502(monkeypatch):
    err = EngineError("timed out", is_timeout=True)
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/documents/library")
    assert resp.status_code == 502
    body = resp.json()
    assert body["engine_status"] is None
    assert "timed out" in body["message"].lower()


def test_engine_connection_error_becomes_502(monkeypatch):
    err = EngineError("connection refused")  # status None, not a timeout
    _patch_engine(monkeypatch, error=err)
    resp = _make_client().get("/api/applicant/documents/applications/app-1")
    assert resp.status_code == 502
    assert resp.json()["message"] == "The application engine is unavailable."


# ── auth gate ────────────────────────────────────────────────────────────────


def test_requires_authentication(monkeypatch):
    """With a configured auth manager and no logged-in user, the proxy rejects.

    The engine must never be called for an unauthenticated request, so the fake
    is wired to explode if it is.
    """

    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)

    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_documents_routes())
    client = TestClient(app)

    resp = client.get("/api/applicant/documents/library")
    assert resp.status_code == 401


# ── privilege gate (writes require can_use_documents) ────────────────────────


class _PrivAuthManager:
    """Minimal AuthManager stand-in: a resolved user whose privileges are fixed.

    Mirrors the real ``require_privilege`` contract (``get_privileges(user)``).
    """

    is_configured = True

    def __init__(self, privileges):
        self._privs = privileges

    def get_privileges(self, _user):
        return dict(self._privs)


def _make_priv_client(privileges, *, user="restricted"):
    """App where the user is authenticated but has the given privilege map."""
    app = FastAPI()
    app.state.auth_manager = _PrivAuthManager(privileges)

    @app.middleware("http")
    async def _set_user(request: Request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_documents_routes())
    return TestClient(app)


def test_document_writes_require_can_use_documents(monkeypatch):
    """A user without ``can_use_documents`` is blocked from every write, and the
    engine is never contacted — matching the native documents surface, so the
    privilege gate can't be bypassed through the proxy."""

    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege is denied")

    monkeypatch.setattr(docs_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})

    writes = [
        ("POST", "/api/applicant/documents/doc-1/turn", {"instruction": "x"}),
        ("POST", "/api/applicant/documents/doc-1/approve", None),
        ("POST", "/api/applicant/documents/doc-1/decline", None),
        ("POST", "/api/applicant/documents/variants/var-1/approve", None),
        ("POST", "/api/applicant/documents/aggressiveness", {"aggressiveness": 30}),
    ]
    for method, path, body in writes:
        resp = client.request(method, path, json=body)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


def test_document_reads_allowed_without_write_privilege(monkeypatch):
    """Reads (and opening a review session) stay available to a user who only
    lacks the write privilege — the gate applies to mutations, not viewing."""
    _patch_engine(monkeypatch, result={"application_id": "app-1", "items": []})
    client = _make_priv_client({"can_use_documents": False})
    assert client.get("/api/applicant/documents/library").status_code == 200
    assert client.get("/api/applicant/documents/applications/app-1").status_code == 200


def test_document_writes_allowed_with_privilege(monkeypatch):
    """With the privilege granted, writes go through to the engine as before."""
    _patch_engine(monkeypatch, result={"id": "doc-1", "approved": True})
    client = _make_priv_client({"can_use_documents": True})
    resp = client.post("/api/applicant/documents/doc-1/approve")
    assert resp.status_code == 200
    assert _FakeEngine.last_call == ("approve_document", ("doc-1",))
