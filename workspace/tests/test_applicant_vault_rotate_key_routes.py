"""Hermetic tests for the vault MASTER-KEY ROTATION proxy (dark-engine audit
item 18): ``POST /api/applicant/vault/rotate-key``.

The engine already implements ``POST /api/credentials/rotate-key``
(``src/applicant/app/routers/credentials.py``) which mints a fresh master key
and re-seals every stored credential under it (FR-VAULT-3). Nothing in
``workspace/`` proxied it — this was the flagship vault-hygiene action,
curl-only. This file pins the new proxy route's mapping, error translation
reuse, and — the important part — that it is gated by the SAME
``can_use_documents`` privilege as the other mutating vault routes (it is the
heaviest mutation the vault offers, touching every stored secret at once, so
it must not be weaker than the routes it sits beside).

Zero network: the engine client is faked, following the exact convention of
``test_applicant_vault_routes.py`` in this same directory.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.applicant_vault_routes as vault_routes
from routes.applicant_vault_routes import setup_applicant_vault_routes
from src.applicant_engine import EngineError


class _FakeEngine:
    last_call = None

    def __init__(self, *, result=None, error: EngineError | None = None):
        self._result = result
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def vault_rotate_key(self):
        type(self).last_call = ("vault_rotate_key", ())
        if self._error is not None:
            raise self._error
        return self._result


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        vault_routes,
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
    app.include_router(setup_applicant_vault_routes())
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

    app.include_router(setup_applicant_vault_routes())
    return TestClient(app)


# ── happy path ────────────────────────────────────────────────────────────


def test_rotate_key_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"rotated": True, "records": 3})
    resp = _make_client().post("/api/applicant/vault/rotate-key")
    assert resp.status_code == 200
    assert resp.json() == {"rotated": True, "records": 3}
    assert _FakeEngine.last_call == ("vault_rotate_key", ())


def test_rotate_key_route_is_registered_under_the_vault_prefix():
    src_text = vault_routes.__file__
    with open(src_text, encoding="utf-8") as f:
        src = f.read()
    assert '@router.post("/rotate-key")' in src


# ── error translation (reuses the shared _engine_error_response) ───────────


def test_rotate_key_timeout_becomes_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("timed out", is_timeout=True))
    resp = _make_client().post("/api/applicant/vault/rotate-key")
    assert resp.status_code == 502
    assert resp.json()["engine_status"] is None


def test_rotate_key_engine_501_becomes_502(monkeypatch):
    # The engine returns 501 when the configured credential store doesn't
    # support rotation; the shared 5xx-scrub path turns that into a clean 502
    # rather than leaking the raw engine detail.
    _patch_engine(
        monkeypatch,
        error=EngineError("no rotation support", status=501, detail="no rotation support"),
    )
    resp = _make_client().post("/api/applicant/vault/rotate-key")
    assert resp.status_code == 502


# ── auth + privilege gate (MUST mirror the sibling mutating vault routes) ──


def test_rotate_key_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(vault_routes, "ApplicantEngineClient", _boom)
    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_vault_routes())
    client = TestClient(app)
    assert client.post("/api/applicant/vault/rotate-key").status_code == 401


def test_rotate_key_requires_can_use_documents_privilege(monkeypatch):
    """Same gate as store/capture/account (the other mutating vault routes) —
    rotation must not be reachable by a caller who lacks it, since it is the
    single heaviest mutation the vault offers."""
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege denied")

    monkeypatch.setattr(vault_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})
    assert client.post("/api/applicant/vault/rotate-key").status_code == 403


def test_rotate_key_allowed_with_can_use_documents_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"rotated": True, "records": 0})
    client = _make_priv_client({"can_use_documents": True})
    resp = client.post("/api/applicant/vault/rotate-key")
    assert resp.status_code == 200
    assert resp.json() == {"rotated": True, "records": 0}
