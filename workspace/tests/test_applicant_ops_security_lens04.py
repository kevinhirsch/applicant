"""Security-lens tests (lens 04, findings #16 and #14) for the ops proxy's
auth gate and error-forwarding (``routes/applicant_ops_routes.py``).

#16 — the first-run loopback bypass must fail CLOSED for anything other than a
direct, unforwarded loopback connection: a request that merely LOOKS like
loopback at the TCP layer (e.g. arriving over a tunnel/reverse-proxy that
itself connects to us from 127.0.0.1) must not inherit that trust while auth
isn't configured yet.

#14 — a 4xx forwarded from the engine to the client must never carry the
engine's raw internal detail (a stack trace, an HTML page, a raw
validation-error body) — only a short, safe, plain-language message. The
status code itself is still preserved.

Zero network; same scripted-engine + ``TestClient`` approach as
``test_applicant_ops_routes.py``, defined locally so this file stands alone
(per the review lane's rule not to edit other test files).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.applicant_ops_routes as mod
from routes.applicant_ops_routes import setup_applicant_ops_routes
from src.applicant_engine import EngineError


class _AuthMgr:
    def __init__(self, *, configured, admins=None):
        self.is_configured = configured
        self._admins = admins or set()

    def is_admin(self, user):
        return user in self._admins


def _make_app(*, user="", configured=False, admins=()) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = _AuthMgr(configured=configured, admins=set(admins))

    @app.middleware("http")
    async def _auth(request, call_next):
        request.state.current_user = user
        return await call_next(request)

    app.include_router(setup_applicant_ops_routes())
    return app


class _FakeEngine:
    """Minimal scripted engine: only what's needed to exercise a write route."""

    raises: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def update_status(self):
        if "update_status" in _FakeEngine.raises:
            raise _FakeEngine.raises["update_status"]
        return {"surface": "update", "status": "live"}

    async def update_trigger(self):
        if "update_trigger" in _FakeEngine.raises:
            raise _FakeEngine.raises["update_trigger"]
        return {"started": False, "message": "Dry run"}


@pytest.fixture(autouse=True)
def _reset():
    _FakeEngine.raises = {}
    yield


# --- #16: the pre-auth-config loopback bypass must fail closed --------------


def test_bypass_unreachable_with_forwarded_for_header(monkeypatch):
    """A request whose peer looks like loopback but carries a forwarding
    header (i.e. it actually arrived via a proxy/tunnel that itself connects
    to us from 127.0.0.1) must NOT inherit local trust while auth isn't
    configured. This is the concrete bypass finding #16 flags: before the
    fix, only ``client.host`` was checked, so any tunneled/proxied remote
    caller passed as if it were the box's own operator."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("127.0.0.1", 51000))
    r = c.get("/api/applicant/ops/update", headers={"x-forwarded-for": "203.0.113.9"})
    assert r.status_code == 401


def test_bypass_unreachable_with_cf_connecting_ip_header(monkeypatch):
    """Same shape, for a Cloudflare-tunnel-style forwarding header."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("127.0.0.1", 51000))
    r = c.get("/api/applicant/ops/update", headers={"cf-connecting-ip": "203.0.113.9"})
    assert r.status_code == 401


def test_direct_loopback_without_forwarding_headers_still_allowed(monkeypatch):
    """Non-regression: a genuine, unforwarded loopback caller (the intended
    first-run setup path) is still let through."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("127.0.0.1", 51000))
    r = c.get("/api/applicant/ops/update")
    assert r.status_code == 200


def test_remote_caller_still_refused(monkeypatch):
    """Non-regression: a plain remote, unforwarded caller (#228) is still
    refused."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    c = TestClient(_make_app(user="", configured=False, admins=()), client=("203.0.113.9", 40000))
    r = c.get("/api/applicant/ops/update")
    assert r.status_code == 401


# --- #14: forwarded 4xx bodies are sanitized ---------------------------------


def test_forwarded_4xx_traceback_is_sanitized(monkeypatch):
    """A raw traceback-shaped detail from the engine must never reach the
    client verbatim."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    raw = (
        'Traceback (most recent call last):\n'
        '  File "/app/src/applicant/app/routers/agent_runs.py", line 42, in configure\n'
        '    raise ValueError("boom")\n'
        "ValueError: boom"
    )
    _FakeEngine.raises["update_trigger"] = EngineError("bad", status=400, detail=raw)
    c = TestClient(_make_app(user="alice", configured=True, admins=("alice",)))
    r = c.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 400
    body = r.json()
    assert "Traceback" not in body["detail"]
    assert "/app/src" not in body["detail"]
    assert raw not in body["detail"]


def test_forwarded_4xx_non_string_detail_is_sanitized(monkeypatch):
    """A raw validation-error body (list/dict — the engine's JSON had no
    top-level ``detail`` key) must not be forwarded as-is; it can leak
    internal field names/types."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    raw_detail = [{"loc": ["body", "internal_field"], "msg": "value error", "type": "value_error"}]
    _FakeEngine.raises["update_trigger"] = EngineError("bad", status=422, detail=raw_detail)
    c = TestClient(_make_app(user="alice", configured=True, admins=("alice",)))
    r = c.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str)
    assert "internal_field" not in body["detail"]


def test_forwarded_4xx_short_safe_message_still_passes_through(monkeypatch):
    """Non-regression: a short, intentional, plain-language message from the
    engine is still forwarded so the user sees the actionable detail."""
    monkeypatch.setattr(mod, "ApplicantEngineClient", _FakeEngine)
    _FakeEngine.raises["update_trigger"] = EngineError(
        "bad", status=400, detail="Updates are disabled on this deployment."
    )
    c = TestClient(_make_app(user="alice", configured=True, admins=("alice",)))
    r = c.post("/api/applicant/ops/update/trigger")
    assert r.status_code == 400
    assert r.json()["detail"] == "Updates are disabled on this deployment."
