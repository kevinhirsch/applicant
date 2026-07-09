"""Pure-domain tests for the realtime frame envelope + upstream safety seam."""

from __future__ import annotations

import pytest

from applicant.core.realtime.envelope import (
    CONTROL_CHANNEL,
    FEATURE_CHANNELS,
    authorize_upstream,
    control_frame,
    parse_frame,
)


def test_parse_frame_accepts_a_well_formed_envelope():
    f = parse_frame({"chan": "presence", "type": "join", "seq": 3, "data": {"tab": "a"}})
    assert f.chan == "presence"
    assert f.type == "join"
    assert f.seq == 3
    assert f.data == {"tab": "a"}
    assert f.as_dict() == {"chan": "presence", "type": "join", "seq": 3, "data": {"tab": "a"}}


def test_parse_frame_defaults_seq_and_data():
    f = parse_frame({"chan": "presence", "type": "ping"})
    assert f.seq == 0
    assert f.data == {}


@pytest.mark.parametrize(
    "raw",
    [
        [],  # not an object
        {"type": "join"},  # missing chan
        {"chan": "nope", "type": "join"},  # unknown chan
        {"chan": "presence"},  # missing type
        {"chan": "presence", "type": ""},  # empty type
        {"chan": "presence", "type": "join", "seq": "1"},  # non-int seq
        {"chan": "presence", "type": "join", "seq": True},  # bool is not a valid seq
        {"chan": "presence", "type": "join", "data": []},  # non-object data
    ],
)
def test_parse_frame_rejects_malformed_envelopes(raw):
    with pytest.raises(ValueError):
        parse_frame(raw)


def test_presence_upstream_verbs_are_allowed():
    for verb in ("join", "leave", "sync", "ping"):
        assert authorize_upstream("presence", verb).allowed is True


def test_consequential_upstream_commands_are_denied_by_default():
    # The whole point of the seam: the socket can NOT self-authorize a submit.
    for chan, verb in (
        ("agent", "approve"),
        ("agent", "steer"),
        ("takeover", "input"),
        ("chat", "message"),
        ("presence", "state"),  # 'state' is server->client only, not an upstream verb
    ):
        decision = authorize_upstream(chan, verb)
        assert decision.allowed is False
        assert decision.reason  # a human-readable reason, never silent


def test_control_channel_never_accepts_upstream_commands():
    assert authorize_upstream(CONTROL_CHANNEL, "hello").allowed is False


def test_control_frame_uses_sentinel_seq_on_the_control_channel():
    cf = control_frame("error", {"reason": "x"})
    assert cf["chan"] == CONTROL_CHANNEL
    assert cf["seq"] == -1
    assert cf["data"] == {"reason": "x"}
    assert "presence" in FEATURE_CHANNELS
    assert CONTROL_CHANNEL not in FEATURE_CHANNELS
