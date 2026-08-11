"""Unit tests for the realtime frame envelope (no I/O, pure domain logic).

Tests cover:
- Frame dataclass construction + as_dict
- parse_frame validation (valid/invalid)
- authorize_upstream (allowed, denied, unknown channels, feature vs control)
- control_frame builder
"""

import pytest

from applicant.core.realtime.envelope import (
    CONTROL_CHANNEL,
    FEATURE_CHANNELS,
    Frame,
    UpstreamDecision,
    authorize_upstream,
    control_frame,
    parse_frame,
)


# ---------------------------------------------------------------------------
# Autouse fixture — parallel-safe isolation (xdist convention)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear any module-level state before each test.

    The envelope module currently has no LRU cache, but the fixture is kept
    as a safety convention for parallel xdist execution and future-proofing.
    """
    return


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

class TestFrame:
    """Tests for the Frame frozen dataclass."""

    @pytest.mark.unit
    def test_minimal_construction(self) -> None:
        """Frame with only required fields (chan, type)."""
        frame = Frame(chan="presence", type="ping")
        assert frame.chan == "presence"
        assert frame.type == "ping"
        assert frame.seq == 0
        assert frame.data == {}

    @pytest.mark.unit
    def test_full_construction(self) -> None:
        """Frame with all fields provided."""
        frame = Frame(chan="agent", type="pause", seq=42, data={"run_id": "abc"})
        assert frame.chan == "agent"
        assert frame.type == "pause"
        assert frame.seq == 42
        assert frame.data == {"run_id": "abc"}

    @pytest.mark.unit
    def test_as_dict(self) -> None:
        """as_dict returns the canonical envelope dict."""
        frame = Frame(chan="takeover", type="input", seq=7, data={"key": "x"})
        expected = {"chan": "takeover", "type": "input", "seq": 7, "data": {"key": "x"}}
        assert frame.as_dict() == expected

    @pytest.mark.unit
    def test_as_dict_defaults(self) -> None:
        """as_dict with omitted optional fields uses defaults."""
        frame = Frame(chan="notif", type="alert")
        expected = {"chan": "notif", "type": "alert", "seq": 0, "data": {}}
        assert frame.as_dict() == expected


# ---------------------------------------------------------------------------
# UpstreamDecision
# ---------------------------------------------------------------------------

class TestUpstreamDecision:
    """Tests for the UpstreamDecision frozen dataclass."""

    @pytest.mark.unit
    def test_allowed(self) -> None:
        """Allowed decision with default reason."""
        d = UpstreamDecision(True)
        assert d.allowed is True
        assert d.reason == ""

    @pytest.mark.unit
    def test_denied_with_reason(self) -> None:
        """Denied decision with explicit reason."""
        d = UpstreamDecision(False, "not enabled")
        assert d.allowed is False
        assert d.reason == "not enabled"


# ---------------------------------------------------------------------------
# parse_frame
# ---------------------------------------------------------------------------

class TestParseFrame:
    """Tests for parse_frame validation."""

    # -- valid frames -------------------------------------------------------

    @pytest.mark.unit
    def test_valid_minimal(self) -> None:
        """A minimal valid frame (only chan + type)."""
        frame = parse_frame({"chan": "presence", "type": "join"})
        assert isinstance(frame, Frame)
        assert frame.chan == "presence"
        assert frame.type == "join"

    @pytest.mark.unit
    def test_valid_full(self) -> None:
        """A fully-populated valid frame."""
        raw = {"chan": "agent", "type": "redirect", "seq": 9, "data": {"url": "/foo"}}
        frame = parse_frame(raw)
        assert frame.chan == "agent"
        assert frame.type == "redirect"
        assert frame.seq == 9
        assert frame.data == {"url": "/foo"}

    @pytest.mark.unit
    def test_valid_control_channel(self) -> None:
        """The sys control channel is accepted."""
        frame = parse_frame({"chan": "sys", "type": "pong"})
        assert frame.chan == "sys"
        assert frame.type == "pong"

    @pytest.mark.unit
    def test_valid_data_none_becomes_empty_dict(self) -> None:
        """data: None is coerced to empty dict."""
        frame = parse_frame({"chan": "presence", "type": "leave", "data": None})
        assert frame.data == {}

    @pytest.mark.unit
    def test_valid_seq_zero_explicit(self) -> None:
        """seq=0 is a valid integer."""
        frame = parse_frame({"chan": "presence", "type": "sync", "seq": 0})
        assert frame.seq == 0

    # -- bad input ----------------------------------------------------------

    @pytest.mark.unit
    def test_not_a_dict(self) -> None:
        """Non-dict raises ValueError."""
        with pytest.raises(ValueError, match="frame must be a JSON object"):
            parse_frame("not a dict")

    @pytest.mark.unit
    def test_missing_chan_key(self) -> None:
        """Missing 'chan' key raises ValueError."""
        with pytest.raises(ValueError, match="unknown channel"):
            parse_frame({"type": "ping"})

    @pytest.mark.unit
    def test_chan_not_str(self) -> None:
        """Non-string chan raises ValueError."""
        with pytest.raises(ValueError, match="unknown channel"):
            parse_frame({"chan": 123, "type": "ping"})

    @pytest.mark.unit
    def test_chan_empty_str(self) -> None:
        """Empty string chan raises ValueError."""
        with pytest.raises(ValueError, match="unknown channel"):
            parse_frame({"chan": "", "type": "ping"})

    @pytest.mark.unit
    def test_chan_unknown(self) -> None:
        """Unknown channel name raises ValueError."""
        with pytest.raises(ValueError, match="unknown channel"):
            parse_frame({"chan": "bogus", "type": "ping"})

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_type", [None, 0, True, "", []])
    def test_type_invalid(self, bad_type: object) -> None:
        """Missing, non-string, or empty type raises ValueError."""
        with pytest.raises(ValueError, match="frame type must be a non-empty string"):
            parse_frame({"chan": "presence", "type": bad_type})

    @pytest.mark.unit
    def test_type_missing_key(self) -> None:
        """Missing 'type' key raises ValueError."""
        with pytest.raises(ValueError, match="frame type must be a non-empty string"):
            parse_frame({"chan": "presence"})

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_seq", [True, False, "1", 1.5, [], {"a": 1}])
    def test_seq_not_int(self, bad_seq: object) -> None:
        """Non-int seq (including bool) raises ValueError."""
        with pytest.raises(ValueError, match="frame seq must be an integer"):
            parse_frame({"chan": "presence", "type": "ping", "seq": bad_seq})

    @pytest.mark.unit
    def test_seq_negative_valid(self) -> None:
        """Negative seq is a valid integer (sentinel -1 for control frames)."""
        frame = parse_frame({"chan": "sys", "type": "hello", "seq": -1})
        assert frame.seq == -1

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_data", ["", 0])  # None is coerced to {} by parse_frame, so it's valid, not an error
    def test_data_not_dict(self, bad_data: object) -> None:
        """Non-dict data (string, number) raises ValueError. (None is coerced to {})."""
        with pytest.raises(ValueError, match="frame data must be an object"):
            parse_frame({"chan": "presence", "type": "sync", "data": bad_data})

    @pytest.mark.unit
    def test_data_list_invalid(self) -> None:
        """List data raises ValueError."""
        with pytest.raises(ValueError, match="frame data must be an object"):
            parse_frame({"chan": "presence", "type": "sync", "data": [1, 2, 3]})


# ---------------------------------------------------------------------------
# authorize_upstream
# ---------------------------------------------------------------------------

class TestAuthorizeUpstream:
    """Tests for the upstream command authorization seam."""

    # -- allowed commands ---------------------------------------------------

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "chan, mtype",
        [
            ("presence", "join"),
            ("presence", "leave"),
            ("presence", "sync"),
            ("presence", "ping"),
            ("agent", "pause"),
            ("agent", "redirect"),
            ("agent", "approve"),
            ("takeover", "input"),
            ("takeover", "start"),
            ("takeover", "stop"),
        ],
    )
    def test_allowed_commands(self, chan: str, mtype: str) -> None:
        """All explicitly enabled upstream commands return allowed."""
        decision = authorize_upstream(chan, mtype)
        assert decision.allowed is True
        assert decision.reason == ""

    # -- disallowed commands on known feature channels ----------------------

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "chan, mtype",
        [
            ("presence", "approve"),
            ("presence", "submit"),
            ("presence", "input"),
            ("agent", "join"),
            ("agent", "leave"),
            ("agent", "submit"),
            ("agent", "finalize"),
            ("agent", "steer"),
            ("takeover", "approve"),
            ("takeover", "submit"),
            ("takeover", "authorize"),
            ("takeover", "confirm"),
            ("notif", "anything"),
            ("chat", "send"),
        ],
    )
    def test_disallowed_feature_commands(self, chan: str, mtype: str) -> None:
        """Upstream commands not in _ALLOWED_UPSTREAM for a feature channel are denied."""
        decision = authorize_upstream(chan, mtype)
        assert decision.allowed is False
        assert "not enabled" in decision.reason
        assert chan in decision.reason
        assert mtype in decision.reason

    # -- unknown channel (not feature, not control) -------------------------

    @pytest.mark.unit
    def test_unknown_channel(self) -> None:
        """A non-feature, non-control channel returns denied with 'does not accept'."""
        decision = authorize_upstream("bogus", "anything")
        assert decision.allowed is False
        assert "does not accept upstream commands" in decision.reason
        assert "bogus" in decision.reason

    # -- control channel ----------------------------------------------------

    @pytest.mark.unit
    def test_control_channel_denied(self) -> None:
        """The sys control channel is not a feature channel, so any upstream cmd is denied."""
        decision = authorize_upstream("sys", "hello")
        assert decision.allowed is False
        assert "does not accept upstream commands" in decision.reason

    @pytest.mark.unit
    def test_control_channel_any_type_denied(self) -> None:
        """Even seemingly harmless types on sys are denied upstream."""
        for mtype in ("pong", "error", "unknown"):
            decision = authorize_upstream("sys", mtype)
            assert decision.allowed is False
            assert "does not accept upstream commands" in decision.reason

    # -- feature channels without any commands enabled ----------------------

    @pytest.mark.unit
    def test_chat_channel_all_denied(self) -> None:
        """The 'chat' feature channel has no upstream commands enabled."""
        for mtype in ("send", "typing", "read"):
            decision = authorize_upstream("chat", mtype)
            assert decision.allowed is False

    @pytest.mark.unit
    def test_notif_channel_all_denied(self) -> None:
        """The 'notif' feature channel has no upstream commands enabled."""
        decision = authorize_upstream("notif", "anything")
        assert decision.allowed is False


# ---------------------------------------------------------------------------
# control_frame
# ---------------------------------------------------------------------------

class TestControlFrame:
    """Tests for the control_frame builder."""

    @pytest.mark.unit
    def test_hello(self) -> None:
        """control_frame builds a hello frame."""
        result = control_frame("hello")
        assert result == {"chan": "sys", "type": "hello", "seq": -1, "data": {}}

    @pytest.mark.unit
    def test_error(self) -> None:
        """control_frame builds an error frame with data."""
        result = control_frame("error", {"msg": "bad frame"})
        assert result == {"chan": "sys", "type": "error", "seq": -1, "data": {"msg": "bad frame"}}

    @pytest.mark.unit
    def test_pong_default_data(self) -> None:
        """control_frame with no data defaults to empty dict."""
        result = control_frame("pong")
        assert result["data"] == {}

    @pytest.mark.unit
    def test_seq_always_negative_one(self) -> None:
        """Control frames always use seq=-1."""
        result = control_frame("any", {"x": 1})
        assert result["seq"] == -1

    @pytest.mark.unit
    def test_chan_always_sys(self) -> None:
        """Control frames always use the sys channel."""
        result = control_frame("any")
        assert result["chan"] == CONTROL_CHANNEL
        assert result["chan"] == "sys"

    @pytest.mark.unit
    def test_control_frame_type_preserved(self) -> None:
        """The mtype argument is preserved exactly."""
        result = control_frame("custom-event")
        assert result["type"] == "custom-event"
