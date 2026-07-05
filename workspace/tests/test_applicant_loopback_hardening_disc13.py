"""DISC-13: loopback-trust bypass via a forwarding proxy/tunnel header.

A bare ``client.host in ("127.0.0.1", "::1")`` check is unsafe behind a
Cloudflare tunnel / reverse proxy: those connect to this app FROM loopback,
so a remote, unauthenticated caller tunneled through one would otherwise
inherit local-operator trust during unconfigured/first-run mode.

``workspace/app.py``'s ``_is_trusted_loopback`` (and
``applicant_ops_routes.py``'s copy of it) already exclude requests carrying
a proxy/tunnel forwarding header. This pins the same hardening at the two
remaining call sites:

- ``src.auth_helpers.require_user`` (and its new shared
  ``src.auth_helpers.is_trusted_loopback`` helper)
- ``routes.applicant_admin_routes._require_admin``

For each: a loopback request carrying a forwarding header must fail closed
(401), a bare direct-loopback request must still pass, and normal
cookie/token auth (an already-resolved user) must be unaffected either way.
"""

from __future__ import annotations

import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# --- routes/applicant_admin_routes.py ---------------------------------------


class _AuthMgr:
    def __init__(self, *, configured: bool, admins: set[str] | None = None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user: str) -> bool:
        return user in self._admins


def _make_app(*, user="", configured=False, admins=()) -> FastAPI:
    from routes.applicant_admin_routes import setup_applicant_admin_routes

    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_admin_routes())
    return app


class _FakeEngine:
    """Never actually called when the gate fails closed at 401, but patched
    in so a passing bare-loopback case doesn't reach out over the network."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def admin_logs(self, limit=100):
        return {"entries": []}


def test_admin_routes_bare_loopback_still_trusted(monkeypatch):
    import routes.applicant_admin_routes as mod

    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(), client=("127.0.0.1", 51000))
    resp = c.get("/api/applicant/admin/logs")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "header,value",
    [
        ("x-forwarded-for", "203.0.113.9"),
        ("cf-connecting-ip", "203.0.113.9"),
        ("x-real-ip", "203.0.113.9"),
        ("forwarded", "for=203.0.113.9"),
    ],
)
def test_admin_routes_loopback_behind_forwarding_header_fails_closed(
    monkeypatch, header, value
):
    import routes.applicant_admin_routes as mod

    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(), client=("127.0.0.1", 51000))
    resp = c.get("/api/applicant/admin/logs", headers={header: value})
    assert resp.status_code == 401


def test_admin_routes_normal_admin_auth_unaffected_by_forwarding_header(monkeypatch):
    """A real, already-authenticated admin must not be penalized just
    because a request happens to carry a forwarding header (e.g. the
    deployment really does sit behind a reverse proxy) — only the
    unconfigured/first-run loopback BYPASS is tightened."""
    import routes.applicant_admin_routes as mod

    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(
        _make_app(user="alice", configured=True, admins=("alice",)),
        client=("127.0.0.1", 51000),
    )
    resp = c.get("/api/applicant/admin/logs", headers={"x-forwarded-for": "203.0.113.9"})
    assert resp.status_code == 200


# --- src/auth_helpers.py ----------------------------------------------------


class _Mgr:
    def __init__(self, configured: bool):
        self.is_configured = configured


class _AppState:
    def __init__(self, configured: bool):
        self.auth_manager = _Mgr(configured)


class _App:
    def __init__(self, configured: bool):
        self.state = _AppState(configured)


class _Client:
    def __init__(self, host: str):
        self.host = host


class _Req:
    """Minimal Request double: current_user unset, plus a client + headers
    (a real Starlette ``Request.headers`` supports ``.get`` the same way)."""

    def __init__(self, *, host: str, configured: bool, headers: dict | None = None, user=None):
        class _State:
            pass

        state = _State()
        state.current_user = user
        self.state = state
        self.app = _App(configured)
        self.client = _Client(host)
        self.headers = headers or {}


def _auth_helpers():
    sys.modules.pop("src.auth_helpers", None)
    from src import auth_helpers  # noqa: WPS433

    return auth_helpers


def test_require_user_bare_loopback_still_trusted_when_unconfigured():
    auth_helpers = _auth_helpers()
    req = _Req(host="127.0.0.1", configured=False)
    assert auth_helpers.require_user(req) == ""


def test_require_user_loopback_behind_forwarding_header_fails_closed():
    auth_helpers = _auth_helpers()
    req = _Req(
        host="127.0.0.1",
        configured=False,
        headers={"x-forwarded-for": "203.0.113.9"},
    )
    with pytest.raises(HTTPException) as exc:
        auth_helpers.require_user(req)
    assert exc.value.status_code == 401


def test_require_user_remote_forwarding_header_still_fails_closed_directly():
    """A remote host is already rejected on host alone (belt-and-suspenders:
    the forwarding-header check must not be the only thing standing between
    a remote caller and the bypass)."""
    auth_helpers = _auth_helpers()
    req = _Req(
        host="203.0.113.9",
        configured=False,
        headers={"x-forwarded-for": "203.0.113.9"},
    )
    with pytest.raises(HTTPException) as exc:
        auth_helpers.require_user(req)
    assert exc.value.status_code == 401


def test_require_user_normal_auth_unaffected_by_forwarding_header():
    """An already-resolved cookie/token user sails through regardless of
    host or forwarding headers -- only the unconfigured loopback BYPASS
    is tightened, not real authentication."""
    auth_helpers = _auth_helpers()
    req = _Req(
        host="127.0.0.1",
        configured=True,
        headers={"x-forwarded-for": "203.0.113.9"},
        user="alice",
    )
    assert auth_helpers.require_user(req) == "alice"


def test_is_trusted_loopback_direct_true_forwarded_false():
    auth_helpers = _auth_helpers()
    assert auth_helpers.is_trusted_loopback(_Req(host="127.0.0.1", configured=False)) is True
    assert (
        auth_helpers.is_trusted_loopback(
            _Req(host="127.0.0.1", configured=False, headers={"forwarded": "for=1.2.3.4"})
        )
        is False
    )
    assert auth_helpers.is_trusted_loopback(_Req(host="203.0.113.9", configured=False)) is False
