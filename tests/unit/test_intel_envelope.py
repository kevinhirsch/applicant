"""Unit tests for hardware-profile envelope accessor and predicates (FR-INTEL-2).

Hermetic — reads only the version-controlled config/hardware_profiles.yaml.
No network, no engine, no live probe.
"""
from __future__ import annotations

import pytest

from applicant.ports.intel.envelope import (
    envelope,
    is_local_capable,
    load_profiles,
    max_local_concurrency,
    supports_vision,
)


class TestEnvelopeReference:
    """AC1: ground-truth reference profile."""

    def test_envelope_values(self) -> None:
        prof = envelope("reference")
        assert prof["concurrency"] == 2
        assert prof["ctx_cap"] == 96000
        assert prof["decode_tok_s"] == 75
        assert prof["prefill_tok_s"] == 1600
        assert prof["vision"] is False

    def test_max_local_concurrency(self) -> None:
        assert max_local_concurrency("reference") == 2


class TestEnvelopeCloudOnly:
    """AC2: cloud-only collapses routing to always-cloud."""

    def test_max_local_concurrency_zero(self) -> None:
        assert max_local_concurrency("cloud-only") == 0

    def test_is_local_capable_always_false(self) -> None:
        assert is_local_capable("cloud-only", 1000) is False
        assert is_local_capable("cloud-only", 0) is False


class TestEnvelopeByoEndpoint:
    """AC3: byo-endpoint concurrency == 1 (fan-out can never pair two local workers)."""

    def test_max_local_concurrency_one(self) -> None:
        assert max_local_concurrency("byo-endpoint") == 1


class TestIsLocalCapable:
    """AC4: is_local_capable routing predicate."""

    def test_over_cap_refuses_local(self) -> None:
        assert is_local_capable("reference", 120000) is False

    def test_under_cap_allows_local(self) -> None:
        assert is_local_capable("reference", 30000) is True

    def test_cloud_only_always_false(self) -> None:
        assert is_local_capable("cloud-only", 50000) is False

    def test_byo_endpoint_within_cap(self) -> None:
        assert is_local_capable("byo-endpoint", 16000) is True

    def test_byo_endpoint_over_cap(self) -> None:
        assert is_local_capable("byo-endpoint", 64000) is False


class TestEdgeCases:
    """Edge case coverage."""

    def test_unknown_profile_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="unknown-profile"):
            envelope("unknown-profile")

    def test_all_profiles_have_correct_keys(self) -> None:
        profiles = load_profiles()
        expected_keys = {"concurrency", "ctx_cap", "decode_tok_s", "prefill_tok_s", "vision"}
        for name, prof in profiles.items():
            assert set(prof.keys()) == expected_keys, f"{name} keys mismatch"
            assert isinstance(prof["concurrency"], int)
            assert isinstance(prof["ctx_cap"], int)
            assert isinstance(prof["decode_tok_s"], int)
            assert isinstance(prof["prefill_tok_s"], int)
            assert isinstance(prof["vision"], bool)

    def test_all_profiles_vision_false(self) -> None:
        profiles = load_profiles()
        for name in profiles:
            assert supports_vision(name) is False, f"{name} has vision enabled"

    def test_supports_vision_for_unknown(self) -> None:
        with pytest.raises(KeyError):
            supports_vision("no-such-profile")
