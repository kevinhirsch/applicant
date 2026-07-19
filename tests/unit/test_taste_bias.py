import pytest

from applicant.core.rules.taste_bias import (
    _TASTE_CAP,
    _TASTE_FULL_AT,
    _value_polarity,
    matched_values,
    taste_bias,
)


@pytest.fixture(autouse=True)
def _noop():
    """Module is stateless — no cache or global state to clear."""
    yield


class TestTasteBias:
    """Tests for taste_bias — bounded multiplicative bias from taste history."""

    def test_empty_feature_stats_returns_one(self):
        assert taste_bias({}, "something") == 1.0
        assert taste_bias(None, "something") == 1.0

    def test_no_match_returns_one(self):
        stats = {"keyword": {"python:approve": 5}}
        assert taste_bias(stats, "golang") == 1.0

    def test_positive_polarity_gives_bias_above_one(self):
        stats = {"keyword": {"python:approve": 8}}
        result = taste_bias(stats, "python", cap=_TASTE_CAP)
        assert result > 1.0

    def test_negative_polarity_gives_bias_below_one(self):
        stats = {"keyword": {"python:decline": 8}}
        result = taste_bias(stats, "python", cap=_TASTE_CAP)
        assert result < 1.0
        assert result >= 1.0 - _TASTE_CAP

    def test_bias_bounded_by_cap_even_with_extreme_stats(self):
        max_stats = {"keyword": {"python:approve": 100}}
        result = taste_bias(max_stats, "python", cap=_TASTE_CAP)
        assert result <= 1.0 + _TASTE_CAP

        min_stats = {"keyword": {"python:decline": 100}}
        result = taste_bias(min_stats, "python", cap=_TASTE_CAP)
        assert result >= 1.0 - _TASTE_CAP

    def test_cold_model_returns_one(self):
        assert taste_bias(None, "") == 1.0
        assert taste_bias({}, "") == 1.0


class TestMatchedValues:
    """Tests for matched_values — filters feature values by presence in haystack."""

    def test_returns_only_features_whose_values_appear_in_haystack(self):
        stats = {
            "keyword": {"python:approve": 3},
            "location": {"remote:approve": 5},
        }
        result = matched_values(stats, "python")
        assert "keyword" in result
        assert "location" not in result

    def test_case_insensitive_matching(self):
        stats = {"keyword": {"Python:approve": 3}}
        result = matched_values(stats, "python developer")
        # net=3, magnitude = min(1.0, 3/8) = 0.375
        assert result == {"keyword": pytest.approx(3.0 / _TASTE_FULL_AT, abs=1e-6)}

    def test_empty_stats_returns_empty(self):
        assert matched_values({}, "anything") == {}
        assert matched_values(None, "anything") == {}

    def test_empty_haystack_returns_empty(self):
        stats = {"keyword": {"python:approve": 3}}
        assert matched_values(stats, "") == {}


class TestValuePolarity:
    """Tests for _value_polarity — net approve/decline polarity."""

    def test_zero_net_returns_zero(self):
        slot = {"python:approve": 4, "python:decline": 4}
        assert _value_polarity(slot) == 0.0

    def test_confidence_ramp_partial_at_low_counts(self):
        # net=1  -> magnitude = min(1.0, 1/8) = 0.125
        slot = {"python:approve": 1}
        assert _value_polarity(slot) == pytest.approx(1.0 / _TASTE_FULL_AT, abs=1e-6)

        # net=4  -> magnitude = min(1.0, 4/8) = 0.5
        slot2 = {"python:approve": 4}
        assert _value_polarity(slot2) == pytest.approx(4.0 / _TASTE_FULL_AT, abs=1e-6)

        # net=8  -> magnitude = min(1.0, 8/8) = 1.0
        slot3 = {"python:approve": 8}
        assert _value_polarity(slot3) == 1.0

        # net=16 -> magnitude = min(1.0, 16/8) = 1.0 (clamped)
        slot4 = {"python:approve": 16}
        assert _value_polarity(slot4) == 1.0

    def test_approve_increases_net_positive(self):
        slot = {"python:approve": 5}
        assert _value_polarity(slot) > 0.0

    def test_decline_decreases_net_negative(self):
        slot = {"python:decline": 5}
        assert _value_polarity(slot) < 0.0

    def test_mixed_signals_net_differs(self):
        slot = {"python:approve": 6, "golang:decline": 2}
        # net = 6 - 2 = 4, magnitude = min(1.0, 4/8) = 0.5
        assert _value_polarity(slot) == pytest.approx(4.0 / _TASTE_FULL_AT, abs=1e-6)
        assert _value_polarity(slot) > 0.0

    def test_invalid_counts_are_skipped(self):
        slot = {"python:approve": "invalid", "golang:approve": 5}
        # "invalid" skipped, net=5, magnitude=min(1.0,5/8)=0.625
        assert _value_polarity(slot) == pytest.approx(5.0 / _TASTE_FULL_AT, abs=1e-6)
