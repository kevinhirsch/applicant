"""Hermetic tests for Cookbook shell/download streaming over a WebSocket.

Mounts ONLY ``routes/shell_ws_routes.py`` on a bare FastAPI app with a fake
``auth_manager`` on ``app.state`` (the real global auth gate never runs for
WebSocket scopes anyway). The command-stream generator (``build_shell_stream``)
is stubbed to yield known SSE strings for the transport/auth/relay tests — no
real subprocess, no deps — plus ONE real ``echo`` run to prove the actual pipe
path works end-to-end over the socket. The live-dep serve/download binaries are
never exercised here (that's the integration lane); this covers the seam the FE
consumes.

Covers: an unauthenticated upgrade is rejected; a non-admin upgrade is rejected
(shell exec is admin-only, mirroring ``_require_admin``); the socket relays the
SAME SSE events the SSE route emits then a terminal ``end``; a non-``run`` or
empty-command first frame is refused; and ``_resolve_ws_admin`` fails closed /
opens only for an admin or a trusted first-run loopback.
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# Importing the WS route pulls routes.shell_routes → the workspace ``core``
# package, whose database module runs ``init_db()`` at import against
# ``DATABASE_URL`` (default a relative ``./data/app.db`` with no dir here). Point
# it at an in-memory DB ONLY for the duration of this import, then restore the
# env — the engine app (a different app that expects Postgres) is built by other
# tests in the same process and must not inherit our sqlite URL. These tests
# never touch the DB (shell is admin-gated, not owner-scoped: no query on the WS
# path).
_saved_db_url = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
try:
    from routes import shell_ws_routes
    from routes.shell_ws_routes import setup_shell_ws_routes, _resolve_ws_admin
finally:
    if _saved_db_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = _saved_db_url


# --- fakes ------------------------------------------------------------------


class FakeAuth:
    def __init__(self, configured: bool, tokens: dict[str, str], admins: set[str] | None = None):
        self.is_configured = configured
        self._tokens = tokens
        self._admins = admins if admins is not None else set(tokens.values())

    def get_username_for_token(self, token):
        return self._tokens.get(token)

    def is_admin(self, username):
        return username in self._admins


def _make_app(*, configured=True, tokens=None, admins=None) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = FakeAuth(configured, tokens or {}, admins)
    app.include_router(setup_shell_ws_routes())
    return app


def _cookie(token: str) -> dict:
    return {"cookie": f"applicant_session={token}"}


_SSE = [
    'data: {"stream": "stdout", "data": "START repo"}\n\n',
    'data: {"stream": "stdout", "data": "FILE model.bin [####----] 50% 1.0/2.0GB"}\n\n',
    'data: {"stream": "stdout", "data": "DONE /cache/model"}\n\n',
    'data: {"exit_code": 0}\n\n',
]


@pytest.fixture
def _stub_stream(monkeypatch):
    """Replace the real command-stream factory with a fake async generator."""
    def fake_build(cmd, timeout, use_pty, use_tmux, request):
        async def gen():
            for ev in _SSE:
                yield ev
        return gen()

    monkeypatch.setattr(shell_ws_routes, "build_shell_stream", fake_build)
    yield


# --- auth on upgrade --------------------------------------------------------


def test_unauthenticated_upgrade_is_rejected():
    app = _make_app(configured=True, tokens={})
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/shell/ws"):
                pass  # server closes the handshake before accept


def test_non_admin_upgrade_is_rejected():
    # Bob is authenticated but is NOT an admin — shell exec stays admin-only.
    app = _make_app(configured=True, tokens={"tok": "bob"}, admins=set())
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/api/shell/ws", headers=_cookie("tok")):
                pass


# --- stream relay (SSE parity) ----------------------------------------------


def test_admin_receives_relayed_events_then_end(_stub_stream):
    app = _make_app(configured=True, tokens={"tok": "alice"}, admins={"alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/shell/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "run", "command": "download something"})
            got = []
            while True:
                m = ws.receive_json()
                if m["type"] == "end":
                    break
                assert m["type"] == "chunk"
                got.append(m["data"])
            # Byte-identical to the SSE event strings the SSE route serves.
            assert got == _SSE


def test_non_run_first_frame_is_rejected(_stub_stream):
    app = _make_app(configured=True, tokens={"tok": "alice"}, admins={"alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/shell/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "subscribe"})
            m = ws.receive_json()
            assert m["type"] == "error"


def test_empty_command_is_rejected(_stub_stream):
    app = _make_app(configured=True, tokens={"tok": "alice"}, admins={"alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/shell/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "run", "command": "   "})
            m = ws.receive_json()
            assert m["type"] == "error"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX /bin/sh echo path")
def test_real_echo_streams_over_the_socket():
    # Prove the ACTUAL pipe generator (no stub) streams a trivial command over
    # the WS: the echoed line, an exit_code event, then a terminal end.
    app = _make_app(configured=True, tokens={"tok": "alice"}, admins={"alice"})
    with TestClient(app) as c:
        with c.websocket_connect("/api/shell/ws", headers=_cookie("tok")) as ws:
            ws.send_json({"type": "run", "command": "echo cookbook-ws-ok", "timeout": 15})
            saw_line = saw_exit = saw_end = False
            for _ in range(50):
                m = ws.receive_json()
                if m["type"] == "end":
                    saw_end = True
                    break
                assert m["type"] == "chunk"
                data = m["data"]
                if "cookbook-ws-ok" in data:
                    saw_line = True
                if '"exit_code"' in data:
                    saw_exit = True
            assert saw_line and saw_exit and saw_end


# --- _resolve_ws_admin fails closed / opens only for admin or loopback -------


class _FakeWS:
    def __init__(self, app, cookies=None, host="1.2.3.4", headers=None):
        self.app = app
        self.cookies = cookies or {}
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def _app_with_auth(auth):
    app = FastAPI()
    app.state.auth_manager = auth
    return app


def test_resolve_admin_true_for_admin_cookie():
    app = _app_with_auth(FakeAuth(True, {"tok": "alice"}, {"alice"}))
    ok, user = _resolve_ws_admin(_FakeWS(app, cookies={"applicant_session": "tok"}))
    assert ok and user == "alice"


def test_resolve_admin_false_for_non_admin_cookie():
    app = _app_with_auth(FakeAuth(True, {"tok": "bob"}, set()))
    ok, user = _resolve_ws_admin(_FakeWS(app, cookies={"applicant_session": "tok"}))
    assert not ok


def test_resolve_admin_first_run_loopback_is_admin_equiv():
    # No users configured yet: a DIRECT loopback caller (no proxy-forward headers)
    # is trusted as the "" owner, matching _require_admin's unconfigured rule.
    app = _app_with_auth(FakeAuth(False, {}, set()))
    ok, user = _resolve_ws_admin(_FakeWS(app, host="127.0.0.1"))
    assert ok and user == ""


def test_resolve_admin_first_run_non_loopback_is_rejected():
    app = _app_with_auth(FakeAuth(False, {}, set()))
    ok, _ = _resolve_ws_admin(_FakeWS(app, host="1.2.3.4"))
    assert not ok


def test_resolve_admin_loopback_with_proxy_header_is_rejected():
    # A forwarded header means the "loopback" is really the reverse proxy — not a
    # trusted direct caller, so an unconfigured upgrade is refused.
    app = _app_with_auth(FakeAuth(False, {}, set()))
    ws = _FakeWS(app, host="127.0.0.1", headers={"x-forwarded-for": "9.9.9.9"})
    ok, _ = _resolve_ws_admin(ws)
    assert not ok
