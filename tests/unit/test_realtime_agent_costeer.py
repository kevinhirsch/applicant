"""RT Phase 3 (SAFE SUBSET): the ``agent`` co-steer channel (realtime-websocket.md).

Engine-side tests for:

* the envelope seam — ``agent/pause`` + ``agent/redirect`` are the ONLY enabled
  upstream verbs; ``agent/approve`` and every submit/authorize verb stay DENIED
  (the socket can never self-authorize a final submit);
* the registry ``apply_upstream`` seam — an authorized ``pause``/``redirect`` frame
  delegates to the injected agent-control handler, and a denied frame mutates
  NOTHING (mirrors the Phase-1 denial test);
* the agent-control dispatcher — ``pause``/``redirect`` call the EXISTING owner-gated
  ``AgentRunService`` methods (``set_active`` / ``configure_run``), the SAME paths the
  HTTP surface uses (no new authority);
* the downstream fan-out — a recorded run publishes an ``agent`` event that fans into
  the channel and replays for a reconnecting tab.
"""

from __future__ import annotations

import asyncio

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.realtime.agent_control import make_agent_control_dispatcher
from applicant.app.realtime.registry import RealtimeRegistry, RealtimeSession
from applicant.application.services.agent_run_service import AgentRunService
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.ids import CampaignId, new_id
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


def _make_campaign(storage, *, run_mode=RunMode.CONTINUOUS, target=15) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(
        Campaign(id=cid, name="C", run_mode=run_mode, throughput_target=target, schedule={})
    )
    return cid


# --- SAFETY: the enabled verb set is exactly {pause, redirect} ---------------


def test_only_pause_and_redirect_are_enabled_upstream_on_the_agent_channel():
    assert authorize_upstream("agent", "pause").allowed is True
    assert authorize_upstream("agent", "redirect").allowed is True


def test_agent_approve_and_every_submit_authorize_verb_stay_upstream_denied():
    # The whole point of the scoping: `approve` touches the final-submit
    # authorization boundary and is DEFERRED — it must never be authorizable on
    # the socket, nor may any submit/authorize-shaped verb sneak through.
    for verb in (
        "approve",
        "submit",
        "authorize",
        "confirm",
        "final_submit",
        "finalize",
        "steer",  # the design's original name — we enabled `redirect`, not `steer`
    ):
        decision = authorize_upstream("agent", verb)
        assert decision.allowed is False, f"agent/{verb} must be upstream-denied"
        assert decision.reason  # never silent


# --- registry apply_upstream delegation --------------------------------------


def test_agent_pause_frame_delegates_to_the_agent_control_handler():
    calls: list[tuple[str, dict]] = []

    def _handler(frame):
        calls.append((frame.type, dict(frame.data)))
        return UpstreamDecision(True)

    s = RealtimeSession("s1", agent_control=_handler)
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame({"chan": "agent", "type": "pause", "data": {"campaign_id": "c-1"}})
    )
    assert decision.allowed is True
    assert calls == [("pause", {"campaign_id": "c-1"})]
    # Delegation does NOT itself publish anything downstream (the service does the work).
    assert _drain(q) == []


def test_agent_redirect_frame_delegates_to_the_agent_control_handler():
    calls: list[tuple[str, dict]] = []

    def _handler(frame):
        calls.append((frame.type, dict(frame.data)))
        return UpstreamDecision(True)

    s = RealtimeSession("s1", agent_control=_handler)
    s.apply_upstream(
        parse_frame(
            {
                "chan": "agent",
                "type": "redirect",
                "data": {"campaign_id": "c-1", "throughput_target": 5},
            }
        )
    )
    assert calls == [("redirect", {"campaign_id": "c-1", "throughput_target": 5})]


def test_agent_command_without_a_handler_is_a_noop_not_a_crash():
    s = RealtimeSession("s1")  # no handler bound (unit context)
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame({"chan": "agent", "type": "pause", "data": {"campaign_id": "c-1"}})
    )
    assert decision.allowed is True
    assert _drain(q) == []  # authorized-but-unwired command mutates nothing


def test_denied_agent_approve_frame_mutates_nothing():
    # Mirror the Phase-1 apply_upstream denial test: a crafted approve is refused
    # BEFORE any handler is consulted, so the socket never acts.
    calls: list = []
    s = RealtimeSession("s1", agent_control=lambda f: calls.append(f))
    q = s.attach()
    decision = s.apply_upstream(
        parse_frame({"chan": "agent", "type": "approve", "data": {"campaign_id": "c-1"}})
    )
    assert decision.allowed is False
    assert calls == []  # the handler is never even reached for a denied verb
    assert _drain(q) == []


def test_bind_agent_control_refreshes_existing_and_new_sessions():
    reg = RealtimeRegistry()
    early = reg.get_or_create("early")  # created before binding
    reg.bind_agent_control(lambda f: UpstreamDecision(True))
    late = reg.get_or_create("late")  # created after binding
    assert early.agent_control is not None
    assert late.agent_control is not None


# --- agent-control dispatcher delegates to the EXISTING AgentRunService -------


def test_dispatcher_pause_calls_set_active_false_on_the_existing_service():
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    svc = AgentRunService(storage)
    dispatch = make_agent_control_dispatcher(lambda: (svc, lambda: None))

    decision = dispatch(
        parse_frame({"chan": "agent", "type": "pause", "data": {"campaign_id": str(cid)}})
    )
    assert decision.allowed is True
    # It flipped the SAME persisted flag the HTTP pause path flips.
    assert storage.campaigns.get(cid).active is False


def test_dispatcher_redirect_calls_configure_run_on_the_existing_service():
    storage = InMemoryStorage()
    cid = _make_campaign(storage, run_mode=RunMode.CONTINUOUS, target=15)
    svc = AgentRunService(storage)
    dispatch = make_agent_control_dispatcher(lambda: (svc, lambda: None))

    decision = dispatch(
        parse_frame(
            {
                "chan": "agent",
                "type": "redirect",
                "data": {
                    "campaign_id": str(cid),
                    "run_mode": "until_n_viable",
                    "throughput_target": 7,
                },
            }
        )
    )
    assert decision.allowed is True
    updated = storage.campaigns.get(cid)
    assert updated.run_mode is RunMode.UNTIL_N_VIABLE
    assert updated.throughput_target == 7


def test_dispatcher_requires_a_campaign_id():
    storage = InMemoryStorage()
    svc = AgentRunService(storage)
    dispatch = make_agent_control_dispatcher(lambda: (svc, lambda: None))
    decision = dispatch(parse_frame({"chan": "agent", "type": "pause", "data": {}}))
    assert decision.allowed is False
    assert "campaign_id" in decision.reason


def test_dispatcher_unknown_campaign_is_a_clean_denial_not_a_raise():
    storage = InMemoryStorage()
    svc = AgentRunService(storage)
    closed: list[bool] = []
    dispatch = make_agent_control_dispatcher(lambda: (svc, lambda: closed.append(True)))
    decision = dispatch(
        parse_frame({"chan": "agent", "type": "pause", "data": {"campaign_id": "nope"}})
    )
    assert decision.allowed is False
    assert decision.reason  # a human-readable "not found", never silent
    assert closed == [True]  # the per-command session is always released


# --- downstream fan-out: recorded run -> agent event -> replay ---------------


def test_recording_a_run_publishes_an_agent_event():
    published: list[tuple[str, dict]] = []
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    svc = AgentRunService(storage, realtime=lambda mtype, data: published.append((mtype, data)))
    svc.start_run(cid, "Reviewing 3 new roles for you.", stats={"discovered": 3})
    assert len(published) == 1
    mtype, data = published[0]
    assert mtype == "event"
    assert data["campaign_id"] == str(cid)
    assert data["intent"] == "Reviewing 3 new roles for you."
    assert data["stats"] == {"discovered": 3}


def test_agent_run_service_without_realtime_is_unchanged():
    storage = InMemoryStorage()
    cid = _make_campaign(storage)
    svc = AgentRunService(storage)  # no publisher — byte-identical, must not raise
    run = svc.start_run(cid, "Working.", stats={})
    assert run.intent_sentence == "Working."


async def test_agent_events_fan_into_the_channel_and_replay_on_reconnect():
    reg = RealtimeRegistry()
    s1 = reg.get_or_create("owner")
    live = s1.attach()
    # A live agent event fans to the already-connected tab.
    reg.publish_all("agent", "event", {"campaign_id": "c-1", "intent": "Tailoring your resume."})
    f = _drain(live)
    assert f and f[0] == {
        "chan": "agent",
        "type": "event",
        "seq": 0,
        "data": {"campaign_id": "c-1", "intent": "Tailoring your resume."},
    }
    # A reconnecting tab (fresh subscriber, no resume hint) replays the buffer.
    replay = s1.attach()
    r = _drain(replay)
    assert r and r[0]["type"] == "event" and r[0]["seq"] == 0
