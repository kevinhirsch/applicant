"""Hermetic tests for the Applicant CREDENTIAL VAULT proxy (applicant_vault_routes.py).

Zero network: the engine client is faked. Covers manual banking + auto-capture
forwarding (including that the secret is forwarded in the body, not dropped),
that the list maps to the engine's tenants endpoint, error translation, and the
auth + privilege gates.
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

    async def _dispatch(self, name, *args):
        type(self).last_call = (name, args)
        if self._error is not None:
            raise self._error
        return self._result

    async def vault_store_credential(self, body):
        return await self._dispatch("vault_store_credential", body)

    async def vault_capture_credential(self, body):
        return await self._dispatch("vault_capture_credential", body)

    async def vault_list_tenants(self, campaign_id):
        return await self._dispatch("vault_list_tenants", campaign_id)

    async def vault_store_account_credential(self, body):
        return await self._dispatch("vault_store_account_credential", body)

    async def vault_account_status(self):
        return await self._dispatch("vault_account_status")


def _make_client(*, authed: bool = True):
    app = FastAPI()
    if authed:
        @app.middleware("http")
        async def _set_user(request: Request, call_next):
            request.state.current_user = "tester"
            return await call_next(request)
    app.include_router(setup_applicant_vault_routes())
    return TestClient(app, raise_server_exceptions=True)


def _patch_engine(monkeypatch, *, result=None, error: EngineError | None = None):
    _FakeEngine.last_call = None
    monkeypatch.setattr(
        vault_routes,
        "ApplicantEngineClient",
        lambda *a, **k: _FakeEngine(result=result, error=error),
    )


# ── happy path ────────────────────────────────────────────────────────────


def test_list_tenants_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"campaign_id": "c1", "tenants": ["acme.workday.com"]})
    resp = _make_client().get("/api/applicant/vault/c1/tenants")
    assert resp.status_code == 200
    assert resp.json()["tenants"] == ["acme.workday.com"]
    assert _FakeEngine.last_call == ("vault_list_tenants", ("c1",))


def test_store_forwards_full_body_including_secret(monkeypatch):
    _patch_engine(monkeypatch, result={"tenant_key": "t1", "source": "manual"})
    body = {
        "campaign_id": "c1",
        "tenant_key": "acme.workday.com",
        "username": "me@x.com",
        "secret": "hunter2",
    }
    resp = _make_client().post("/api/applicant/vault/credentials", json=body)
    assert resp.status_code == 201
    name, args = _FakeEngine.last_call
    assert name == "vault_store_credential"
    assert args[0] == body  # secret must be forwarded to the (sealing) engine


def test_capture_maps_to_capture_endpoint(monkeypatch):
    _patch_engine(monkeypatch, result={"tenant_key": "t2", "source": "captured"})
    body = {
        "campaign_id": "c1",
        "tenant_key": "acme.workday.com",
        "username": "me@x.com",
        "secret": "s3cr3t",
    }
    resp = _make_client().post("/api/applicant/vault/capture", json=body)
    assert resp.status_code == 201
    name, args = _FakeEngine.last_call
    assert name == "vault_capture_credential"
    assert args[0] == body


def test_account_status_maps_to_engine(monkeypatch):
    _patch_engine(monkeypatch, result={"google": True, "predefined_account": False})
    resp = _make_client().get("/api/applicant/vault/account")
    assert resp.status_code == 200
    assert resp.json() == {"google": True, "predefined_account": False}
    assert _FakeEngine.last_call == ("vault_account_status", ())


def test_store_account_forwards_full_body_including_secret(monkeypatch):
    _patch_engine(monkeypatch, result={"kind": "google", "scope": "global"})
    body = {"kind": "google", "username": "me@gmail.com", "secret": "g-secret"}
    resp = _make_client().post("/api/applicant/vault/account", json=body)
    assert resp.status_code == 201
    name, args = _FakeEngine.last_call
    assert name == "vault_store_account_credential"
    assert args[0] == body  # secret must reach the (sealing) engine


def test_missing_fields_rejected_before_engine(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run on a bad body
        raise AssertionError("engine must not be called for an invalid body")

    monkeypatch.setattr(vault_routes, "ApplicantEngineClient", _boom)
    resp = _make_client().post(
        "/api/applicant/vault/credentials", json={"campaign_id": "c1"}
    )
    assert resp.status_code == 422  # pydantic validation


# ── error translation ───────────────────────────────────────────────────────


def test_timeout_becomes_502(monkeypatch):
    _patch_engine(monkeypatch, error=EngineError("timed out", is_timeout=True))
    resp = _make_client().get("/api/applicant/vault/c1/tenants")
    assert resp.status_code == 502
    assert resp.json()["engine_status"] is None


# ── auth + privilege gates ───────────────────────────────────────────────────


def test_requires_authentication(monkeypatch):
    class _Configured:
        is_configured = True

    def _boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("engine must not be called when unauthenticated")

    monkeypatch.setattr(vault_routes, "ApplicantEngineClient", _boom)
    app = FastAPI()
    app.state.auth_manager = _Configured()
    app.include_router(setup_applicant_vault_routes())
    client = TestClient(app)
    assert client.get("/api/applicant/vault/c1/tenants").status_code == 401


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


def test_writes_require_privilege(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover - must not run when forbidden
        raise AssertionError("engine must not be called when privilege denied")

    monkeypatch.setattr(vault_routes, "ApplicantEngineClient", _boom)
    client = _make_priv_client({"can_use_documents": False})
    body = {"campaign_id": "c1", "tenant_key": "t", "username": "u", "secret": "s"}
    assert client.post("/api/applicant/vault/credentials", json=body).status_code == 403
    assert client.post("/api/applicant/vault/capture", json=body).status_code == 403
    account = {"kind": "google", "username": "u", "secret": "s"}
    assert client.post("/api/applicant/vault/account", json=account).status_code == 403


def test_list_allowed_without_write_privilege(monkeypatch):
    _patch_engine(monkeypatch, result={"campaign_id": "c1", "tenants": []})
    client = _make_priv_client({"can_use_documents": False})
    assert client.get("/api/applicant/vault/c1/tenants").status_code == 200
