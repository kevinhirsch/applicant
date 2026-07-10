"""Hermetic end-to-end tests for the engine realtime WebSocket endpoint.

Uses Starlette's in-process WebSocket test transport (no network, no DB, no LLM
gate) to exercise the multiplexed envelope, presence round-trip, reconnect-replay,
and the server-side default-deny safety seam over the real ASGI app.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _url(session: str, resume: str | None = None) -> str:
    u = f"/api/realtime/ws?session={session}"
    if resume:
        u += f"&resume={resume}"
    return u


def _sid() -> str:
    return f"s-{uuid.uuid4().hex[:8]}"


def _next(ws, *, chan: str, mtype: str | None = None, tries: int = 6) -> dict:
    """Read frames until one matches ``chan`` (and ``mtype`` if given)."""
    for _ in range(tries):
        f = ws.receive_json()
        if f["chan"] == chan and (mtype is None or f["type"] == mtype):
            return f
    raise AssertionError(f"no {chan}/{mtype} frame arrived")


def test_hello_greets_the_new_connection(client):
    with client.websocket_connect(_url(_sid())) as ws:
        hello = ws.receive_json()
        assert hello["chan"] == "sys"
        assert hello["type"] == "hello"
        assert hello["seq"] == -1


def test_presence_join_leave_count_round_trip(client):
    sid = _sid()
    with client.websocket_connect(_url(sid)) as ws:
        ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "t1"}})
        st = _next(ws, chan="presence", mtype="state")
        assert st["data"]["count"] == 1
        ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "t2"}})
        assert _next(ws, chan="presence", mtype="state")["data"]["count"] == 2
        ws.send_json({"chan": "presence", "type": "leave", "seq": 0, "data": {"tab": "t1"}})
        assert _next(ws, chan="presence", mtype="state")["data"]["count"] == 1


def test_two_sockets_on_one_session_both_see_the_count(client):
    sid = _sid()
    with client.websocket_connect(_url(sid)) as a, client.websocket_connect(_url(sid)) as b:
        a.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "a"}})
        # BOTH attached sockets receive the broadcast state (co-driving).
        assert _next(a, chan="presence", mtype="state")["data"]["count"] == 1
        assert _next(b, chan="presence", mtype="state")["data"]["count"] == 1


def test_dropping_one_socket_keeps_the_session_and_the_other_socket_alive(client):
    sid = _sid()
    with client.websocket_connect(_url(sid)) as a:
        a.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "a"}})
        _next(a, chan="presence", mtype="state")
        # open + close a second socket
        with client.websocket_connect(_url(sid)) as b:
            _next(b, chan="presence", mtype="state")
        # after b drops, a still works and the session is intact
        a.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "c"}})
        assert _next(a, chan="presence", mtype="state")["data"]["count"] == 2


def test_reconnect_replays_buffer_then_goes_live(client):
    sid = _sid()
    with client.websocket_connect(_url(sid)) as ws:
        ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "a"}})
        first = _next(ws, chan="presence", mtype="state")
        assert first["seq"] == 0 and first["data"]["count"] == 1
    # reconnect with NO resume: the buffer replays from the start...
    with client.websocket_connect(_url(sid)) as ws2:
        replay = _next(ws2, chan="presence", mtype="state")
        assert replay["seq"] == 0 and replay["data"]["count"] == 1
        # ...then live frames continue with the next seq (gap-free).
        ws2.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "b"}})
        live = _next(ws2, chan="presence", mtype="state")
        assert live["seq"] == 1 and live["data"]["count"] == 2


def test_reconnect_with_resume_skips_already_seen_frames(client):
    sid = _sid()
    with client.websocket_connect(_url(sid)) as ws:
        ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "a"}})
        _next(ws, chan="presence", mtype="state")  # seq 0
    # resume from seq 0: nothing to replay, connection is otherwise idle
    with client.websocket_connect(_url(sid, resume="presence:0")) as ws2:
        assert ws2.receive_json()["type"] == "hello"  # only the greeting, no replayed state
        ws2.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "b"}})
        assert _next(ws2, chan="presence", mtype="state")["seq"] == 1


def test_denied_upstream_command_is_rejected_without_acting(client):
    # `agent/submit` is NOT an enabled verb (only pause/redirect/approve are), so it is
    # refused at the envelope seam and never reaches any handler.
    with client.websocket_connect(_url(_sid())) as ws:
        ws.receive_json()  # hello
        ws.send_json({"chan": "agent", "type": "submit", "seq": 0, "data": {}})
        err = _next(ws, chan="sys", mtype="error")
        assert "not enabled" in err["data"]["reason"]
        assert err["data"]["chan"] == "agent"


def test_agent_pause_reaches_the_bound_agent_control_dispatcher(client):
    # Phase 3: agent/pause is an ENABLED upstream verb, so it is NOT refused at the
    # envelope seam — it is forwarded to the container-bound dispatcher, which calls
    # the real AgentRunService. Sending it with no campaign_id proves the dispatcher
    # (not the deny seam) handled it: the reason is the dispatcher's own validation,
    # not "not enabled".
    with client.websocket_connect(_url(_sid())) as ws:
        ws.receive_json()  # hello
        ws.send_json({"chan": "agent", "type": "pause", "seq": 0, "data": {}})
        err = _next(ws, chan="sys", mtype="error")
        assert "campaign_id" in err["data"]["reason"]
        assert "not enabled" not in err["data"]["reason"]


def test_agent_approve_reaches_the_review_gate_not_the_deny_seam(client):
    # approve is ENABLED as PURE TRANSPORT: it is NOT refused at the envelope seam — it
    # is forwarded to the container-bound dispatcher, which calls the SAME owner-gated
    # MaterialService.approve the HTTP approve router uses. Sending an unknown
    # document_id proves the dispatcher/review gate (not the deny seam) handled it: the
    # reason is the review gate's own "no such document", never "not enabled". This is
    # the socket routing through the identical server-side gate, with no new authority.
    with client.websocket_connect(_url(_sid())) as ws:
        ws.receive_json()  # hello
        ws.send_json(
            {"chan": "agent", "type": "approve", "seq": 0, "data": {"document_id": "nope"}}
        )
        err = _next(ws, chan="sys", mtype="error")
        assert "not enabled" not in err["data"]["reason"]
        assert err["data"]["reason"]  # the review gate's own reason, surfaced to the socket


def test_agent_submit_and_finalize_stay_refused_at_the_seam_in_phase_3(client):
    # The still-deferred submit/authorize verbs stay default-DENIED: they never reach
    # any handler and the reason is the envelope seam's "not enabled", proving they
    # cannot self-authorize a final submit over the socket.
    with client.websocket_connect(_url(_sid())) as ws:
        ws.receive_json()  # hello
        for verb in ("submit", "finalize", "authorize", "confirm", "steer"):
            ws.send_json({"chan": "agent", "type": verb, "seq": 0, "data": {"campaign_id": "x"}})
            err = _next(ws, chan="sys", mtype="error")
            assert "not enabled" in err["data"]["reason"], f"agent/{verb} must stay denied"


def test_malformed_frame_is_rejected_but_keeps_the_socket_open(client):
    with client.websocket_connect(_url(_sid())) as ws:
        ws.receive_json()  # hello
        ws.send_json({"chan": "bogus", "type": "x"})
        err = _next(ws, chan="sys", mtype="error")
        assert "unknown channel" in err["data"]["reason"]
        # socket still usable afterwards
        ws.send_json({"chan": "presence", "type": "join", "seq": 0, "data": {"tab": "a"}})
        assert _next(ws, chan="presence", mtype="state")["data"]["count"] == 1
