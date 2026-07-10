"""RT Phase 4: the ``takeover`` channel (realtime-websocket.md).

Engine-side tests for:

* the envelope seam — ``takeover/input`` + ``start`` + ``stop`` are the ONLY enabled
  upstream verbs; every submit/approve/authorize verb stays DENIED (the socket can
  never self-authorize a final submit — takeover is a human hand-finishing);
* the registry ``apply_upstream`` seam — an authorized ``takeover`` frame delegates to
  the injected takeover-control handler, a denied frame mutates NOTHING, and a
  no-handler command is a clean no-op;
* the takeover-control dispatcher + :class:`TakeoverControl` — ``start``/``stop`` call
  the EXISTING owner-gated remote-view ``authorize_takeover``/``revoke_takeover``, and
  ``input`` forwards ONE raw event over the injected CDP driver ONLY while the user
  holds control (no submit path anywhere);
* the downstream fan-out — CDP screencast frames fan into the ``takeover`` channel and
  replay for a reconnecting tab (the SAME replay mechanic as ``agent``/``notif``).
"""

from __future__ import annotations

import asyncio

from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.sandbox.takeover import FakeTakeoverCdpDriver, TakeoverControl
from applicant.app.realtime.publish import make_takeover_publisher
from applicant.app.realtime.registry import RealtimeRegistry, RealtimeSession, get_registry
from applicant.app.realtime.takeover_control import make_takeover_control_dispatcher
from applicant.core.ids import ApplicationId, new_id
from applicant.core.realtime.envelope import (
    UpstreamDecision,
    authorize_upstream,
    parse_frame,
)


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _sandbox_with_session() -> tuple[LocalSandbox, str]:
    sandbox = LocalSandbox()
    session = sandbox.provision(ApplicationId(new_id()))
    return sandbox, session.session_id


# --- SAFETY: the enabled verb set is exactly {input, start, stop} ------------


def test_only_input_start_stop_are_enabled_upstream_on_the_takeover_channel():
    assert authorize_upstream("takeover", "input").allowed is True
    assert authorize_upstream("takeover", "start").allowed is True
    assert authorize_upstream("takeover", "stop").allowed is True


def test_takeover_submit_and_every_authorize_verb_stay_upstream_denied():
    # SAFETY: takeover is a HUMAN hand-finishing the application — the engine can
    # never self-authorize a final submit over this channel, so no submit/approve/
    # authorize-shaped verb may ever be authorizable on it.
    for verb in (
        "approve",
        "submit",
        "authorize",
        "authorize_engine_finish",
        "confirm",
        "final_submit",
        "finalize",
        "submit_self",
    ):
        decision = authorize_upstream("takeover", verb)
        assert decision.allowed is False, f"takeover/{verb} must be upstream-denied"
        assert decision.reason  # never silent


# --- registry apply_upstream delegation --------------------------------------


def test_takeover_input_frame_delegates_to_the_takeover_control_handler():
    calls: list[tuple[str, dict]] = []

    def _handler(frame):
        calls.append((frame.type, dict(frame.data)))
        return UpstreamDecision(True)

    s = RealtimeSession("s1", takeover_control=_handler)
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame(
            {"chan": "takeover", "type": "input", "data": {"session_id": "sbx-1"}}
        )
    )
    assert decision.allowed is True
    assert calls == [("input", {"session_id": "sbx-1"})]
    # Delegation does NOT itself publish anything downstream (the driver/pump does).
    assert _drain(q) == []


def test_takeover_command_without_a_handler_is_a_noop_not_a_crash():
    s = RealtimeSession("s1")  # no handler bound (unit context)
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame({"chan": "takeover", "type": "start", "data": {"session_id": "x"}})
    )
    assert decision.allowed is True
    assert _drain(q) == []  # authorized-but-unwired command mutates nothing


def test_denied_takeover_submit_frame_mutates_nothing():
    calls: list = []
    s = RealtimeSession("s1", takeover_control=lambda f: calls.append(f))
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame({"chan": "takeover", "type": "submit", "data": {"session_id": "x"}})
    )
    assert decision.allowed is False
    assert calls == []  # the handler is never even reached for a denied verb
    assert _drain(q) == []


def test_bind_takeover_control_refreshes_existing_and_new_sessions():
    reg = RealtimeRegistry()
    early = reg.get_or_create("early")  # created before binding
    reg.bind_takeover_control(lambda f: UpstreamDecision(True))
    late = reg.get_or_create("late")  # created after binding
    assert early.takeover_control is not None
    assert late.takeover_control is not None


# --- dispatcher delegates to the EXISTING owner-gated takeover surface --------


def test_dispatcher_start_authorizes_takeover_on_the_existing_remote_view():
    sandbox, sid = _sandbox_with_session()
    ctrl = TakeoverControl(sandbox, FakeTakeoverCdpDriver())
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: None))

    decision = dispatch(
        parse_frame({"chan": "takeover", "type": "start", "data": {"session_id": sid}})
    )
    assert decision.allowed is True
    # It flipped the SAME takeover flag the HTTP POST /takeover path flips.
    assert sandbox.remote_view().has_takeover(sid) is True


def test_dispatcher_stop_revokes_takeover_on_the_existing_remote_view():
    sandbox, sid = _sandbox_with_session()
    sandbox.remote_view().authorize_takeover(sid)
    ctrl = TakeoverControl(sandbox, FakeTakeoverCdpDriver())
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: None))

    decision = dispatch(
        parse_frame({"chan": "takeover", "type": "stop", "data": {"session_id": sid}})
    )
    assert decision.allowed is True
    assert sandbox.remote_view().has_takeover(sid) is False


def test_dispatcher_input_is_refused_until_the_user_holds_control():
    sandbox, sid = _sandbox_with_session()
    driver = FakeTakeoverCdpDriver()
    ctrl = TakeoverControl(sandbox, driver)
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: None))

    # No takeover held yet → the input is refused and NOTHING is dispatched to CDP.
    denied = dispatch(
        parse_frame(
            {
                "chan": "takeover",
                "type": "input",
                "data": {"session_id": sid, "event": {"kind": "click"}},
            }
        )
    )
    assert denied.allowed is False
    assert denied.reason
    assert driver.inputs == []


def test_dispatcher_input_forwards_a_raw_event_over_cdp_while_in_control():
    sandbox, sid = _sandbox_with_session()
    sandbox.remote_view().authorize_takeover(sid)  # user holds control
    driver = FakeTakeoverCdpDriver()
    ctrl = TakeoverControl(sandbox, driver)
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: None))

    ok = dispatch(
        parse_frame(
            {
                "chan": "takeover",
                "type": "input",
                "data": {
                    "session_id": sid,
                    "event": {"kind": "mousedown", "x": 0.5, "y": 0.25, "button": 0},
                },
            }
        )
    )
    assert ok.allowed is True
    # The raw human event reached the CDP driver — pure transport, no interpretation.
    assert len(driver.inputs) == 1
    _endpoint, event = driver.inputs[0]
    assert event == {"kind": "mousedown", "x": 0.5, "y": 0.25, "button": 0}


def test_dispatcher_requires_a_session_id():
    sandbox, _sid = _sandbox_with_session()
    ctrl = TakeoverControl(sandbox, FakeTakeoverCdpDriver())
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: None))
    decision = dispatch(parse_frame({"chan": "takeover", "type": "input", "data": {}}))
    assert decision.allowed is False
    assert "session_id" in decision.reason


def test_dispatcher_unknown_session_is_a_clean_denial_and_releases_the_service():
    sandbox, _sid = _sandbox_with_session()
    ctrl = TakeoverControl(sandbox, FakeTakeoverCdpDriver())
    closed: list[bool] = []
    dispatch = make_takeover_control_dispatcher(lambda: (ctrl, lambda: closed.append(True)))
    decision = dispatch(
        parse_frame(
            {"chan": "takeover", "type": "start", "data": {"session_id": "nope"}}
        )
    )
    assert decision.allowed is False
    assert decision.reason  # human-readable "unknown session", never silent
    assert closed == [True]  # the per-command handle is always released


def test_takeover_control_has_no_submit_or_approve_path_at_all():
    # SAFETY (structural): the takeover transport exposes ONLY authorize/revoke/input —
    # there is literally no submit/approve/finish method it could reach, so no crafted
    # frame could ever route to a final-submit through this channel.
    ctrl = TakeoverControl(LocalSandbox(), FakeTakeoverCdpDriver())
    for banned in ("submit", "approve", "authorize_engine_finish", "finalize", "finish"):
        assert not hasattr(ctrl, banned)


# --- downstream fan-out: CDP screencast frame -> takeover channel -> replay ---


def test_takeover_frames_fan_into_the_channel_and_replay_on_reconnect():
    reg = RealtimeRegistry()
    s1 = reg.get_or_create("owner")
    live = s1.attach()
    reg.publish_all("takeover", "frame", {"session_id": "sbx-1", "data": "QUJD", "seq_no": 0})
    f = _drain(live)
    assert f and f[0] == {
        "chan": "takeover",
        "type": "frame",
        "seq": 0,
        "data": {"session_id": "sbx-1", "data": "QUJD", "seq_no": 0},
    }
    # A reconnecting tab (fresh subscriber, no resume hint) replays the buffer.
    replay = s1.attach()
    r = _drain(replay)
    assert r and r[0]["type"] == "frame" and r[0]["seq"] == 0


def test_make_takeover_publisher_fans_a_frame_to_the_takeover_channel():
    # The engine-side publisher the screencast pump calls broadcasts to the module
    # registry. Bind the loop to None (its default) so the fan-out is inline — hermetic,
    # no app loop in a unit test — and read it off a subscribed tab.
    reg = get_registry()
    reg.bind_loop(None)
    sess = reg.get_or_create("owner-pub")
    q = sess.attach()
    try:
        make_takeover_publisher()("frame", {"session_id": "sbx-9", "data": "QQ=="})
        frames = [f for f in _drain(q) if f.get("chan") == "takeover"]
        assert frames, "make_takeover_publisher did not fan a frame into the takeover channel"
        assert frames[0]["type"] == "frame"
        assert frames[0]["data"] == {"session_id": "sbx-9", "data": "QQ=="}
    finally:
        sess.detach(q)


def test_authorize_starts_the_screencast_and_frames_fan_down_the_channel():
    # End-to-end seam: TakeoverControl.authorize() starts the CDP screencast via the
    # injected driver, whose scripted frames flow through the frame_sink -> registry
    # -> the takeover channel, and reach a subscribed tab. A FRESH registry (not the
    # module-global) keeps this hermetic regardless of any bound app loop elsewhere.
    reg = RealtimeRegistry()
    sess = reg.get_or_create("owner-e2e")
    q = sess.attach()

    def _sink(session_id, mtype, data):
        reg.publish_all("takeover", mtype, {"session_id": session_id, **data})

    sandbox, sid = _sandbox_with_session()
    driver = FakeTakeoverCdpDriver(scripted_frames=[{"data": "Rk9P", "format": "jpeg"}])
    ctrl = TakeoverControl(sandbox, driver, frame_sink=_sink)

    ok, reason = ctrl.authorize(sid)
    assert ok is True and reason == ""
    frames = [f for f in _drain(q) if f.get("chan") == "takeover" and f.get("type") == "frame"]
    assert frames, "no screencast frame fanned into the takeover channel"
    assert frames[0]["data"]["data"] == "Rk9P"
    assert frames[0]["data"]["session_id"] == sid
