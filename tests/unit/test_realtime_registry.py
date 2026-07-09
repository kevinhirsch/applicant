"""Tests for the per-session, per-channel replay buffer + subscriber bus."""

from __future__ import annotations

import asyncio

from applicant.app.realtime.registry import RealtimeRegistry, RealtimeSession
from applicant.core.realtime.envelope import parse_frame


def _drain(q: asyncio.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_publish_assigns_monotonic_seq_per_channel():
    s = RealtimeSession("s1")
    a = s.publish("presence", "state", {"count": 1})
    b = s.publish("presence", "state", {"count": 2})
    c = s.publish("notif", "pending", {"n": 1})
    assert (a["seq"], b["seq"]) == (0, 1)  # per-channel monotonic
    assert c["seq"] == 0  # a different channel starts its own sequence


async def test_attach_replays_buffer_then_goes_live():
    s = RealtimeSession("s1")
    s.publish("presence", "state", {"count": 1})
    s.publish("presence", "state", {"count": 2})
    q = s.attach()  # fresh subscriber replays the whole buffer
    replayed = _drain(q)
    assert [f["data"]["count"] for f in replayed] == [1, 2]
    # now a live publish reaches the already-attached subscriber
    s.publish("presence", "state", {"count": 3})
    assert _drain(q)[0]["data"]["count"] == 3


async def test_reconnect_resume_replays_only_the_tail():
    s = RealtimeSession("s1")
    for n in range(4):
        s.publish("presence", "state", {"count": n})  # seqs 0..3
    q = s.attach(resume={"presence": 1})  # client already has seq 0 and 1
    seqs = [f["seq"] for f in _drain(q)]
    assert seqs == [2, 3]  # gap-free, no dupes


async def test_dropping_one_subscriber_does_not_affect_the_others():
    s = RealtimeSession("s1")
    q1 = s.attach()
    q2 = s.attach()
    s.detach(q1)  # one tab closes
    s.publish("presence", "state", {"count": 7})
    assert q2.get_nowait()["data"]["count"] == 7  # the other tab still lives
    assert q1.empty()  # the dropped subscriber gets nothing more


async def test_presence_join_leave_updates_the_broadcast_count():
    s = RealtimeSession("s1")
    q = s.attach()
    s.apply_upstream(parse_frame({"chan": "presence", "type": "join", "data": {"tab": "a"}}))
    s.apply_upstream(parse_frame({"chan": "presence", "type": "join", "data": {"tab": "b"}}))
    s.apply_upstream(parse_frame({"chan": "presence", "type": "leave", "data": {"tab": "a"}}))
    counts = [f["data"]["count"] for f in _drain(q)]
    assert counts == [1, 2, 1]


async def test_presence_sync_replaces_the_whole_member_set():
    s = RealtimeSession("s1")
    q = s.attach()
    s.apply_upstream(
        parse_frame({"chan": "presence", "type": "sync", "data": {"members": ["a", "b", "c"]}})
    )
    last = _drain(q)[-1]
    assert last["data"] == {"count": 3, "members": ["a", "b", "c"]}


async def test_denied_upstream_command_mutates_nothing():
    s = RealtimeSession("s1")
    q = s.attach()
    decision = s.apply_upstream(parse_frame({"chan": "agent", "type": "approve", "data": {}}))
    assert decision.allowed is False
    # No frame is published for a denied command — the socket never acted.
    assert _drain(q) == []


async def test_registry_evicts_an_idle_session_after_grace():
    reg = RealtimeRegistry(evict_grace_s=0.01)
    s = reg.get_or_create("s1")
    q = s.attach()
    s.detach(q)
    reg.maybe_evict("s1")
    await asyncio.sleep(0.05)
    assert reg.get("s1") is None  # buffers freed once no subscriber reconnected


async def test_registry_does_not_evict_a_session_with_a_live_subscriber():
    reg = RealtimeRegistry(evict_grace_s=0.01)
    s = reg.get_or_create("s1")
    s.attach()  # still connected
    reg.maybe_evict("s1")
    await asyncio.sleep(0.05)
    assert reg.get("s1") is s
