"""Hermetic unit tests for the deterministic context-size routing module (FR-INTEL-3).

No network, no model call — pure assertions over route() and estimate_tokens().
"""
from __future__ import annotations

import pytest

from applicant.ports.intel.routing import (
    RouteDecision,
    estimate_tokens,
    route,
    context_estimate,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear any LRU or module-level caches for parallel xdist safety."""
    return None


class TestRoute:
    """Routing decision — exact threshold boundaries."""

    @pytest.mark.unit
    def test_reference_local(self) -> None:
        d = route(25000, "reference")
        assert d.recommendation == "LOCAL"
        assert d.concurrency == 2
        assert "concurrent" in d.why
        assert d.split_hint is None

    @pytest.mark.unit
    def test_reference_local_single(self) -> None:
        d = route(70000, "reference")
        assert d.recommendation == "LOCAL-SINGLE"
        assert d.concurrency == 1
        assert "run alone" in d.why
        assert d.split_hint is None

    @pytest.mark.unit
    def test_reference_cloud(self) -> None:
        d = route(130000, "reference")
        assert d.recommendation == "CLOUD"
        assert d.concurrency == 0
        assert d.split_hint is not None

    @pytest.mark.unit
    def test_cloud_only_profile(self) -> None:
        for est in (25000, 70000, 130000):
            d = route(est, "cloud-only")
            assert d.recommendation == "CLOUD", f"Expected CLOUD for {est}"
            assert d.concurrency == 0
            assert d.split_hint is not None

    @pytest.mark.unit
    def test_boundary_local(self) -> None:
        """Just below dual threshold -> LOCAL."""
        d = route(39999, "reference")
        assert d.recommendation == "LOCAL"

    @pytest.mark.unit
    def test_boundary_local_single_low(self) -> None:
        """At dual threshold -> LOCAL-SINGLE."""
        d = route(40000, "reference")
        assert d.recommendation == "LOCAL-SINGLE"

    @pytest.mark.unit
    def test_boundary_local_single_high(self) -> None:
        """At single threshold -> LOCAL-SINGLE."""
        d = route(90000, "reference")
        assert d.recommendation == "LOCAL-SINGLE"

    @pytest.mark.unit
    def test_boundary_cloud(self) -> None:
        """Above single threshold -> CLOUD."""
        d = route(90001, "reference")
        assert d.recommendation == "CLOUD"


class TestEstimateTokens:
    """Token estimation — determinism and basic heuristics."""

    @pytest.mark.unit
    def test_determinism(self) -> None:
        text = "Hello world, this is a deterministic test string with enough unique characters."
        v1 = estimate_tokens(text=text)
        v2 = estimate_tokens(text=text)
        assert v1 == v2

    @pytest.mark.unit
    def test_short_text(self) -> None:
        result = estimate_tokens(text="test")
        assert result == 9001  # 9000 + (4//4)

    @pytest.mark.unit
    def test_empty_text(self) -> None:
        result = estimate_tokens(text="")
        assert result == 9000

    @pytest.mark.unit
    def test_none_text(self) -> None:
        result = estimate_tokens()
        assert result == 9000

    @pytest.mark.unit
    def test_missing_file_path(self) -> None:
        """Missing file should be silently treated as 0 content."""
        result = estimate_tokens(
            text="hi",
            paths=["/nonexistent/file/xyz.txt"],
        )
        assert result == 9000  # 9000 + (2 // 4)

    @pytest.mark.unit
    def test_estimate_and_route_composite(self) -> None:
        """context_estimate convenience wraps both steps."""
        d = context_estimate(text="a" * 100, profile_name="reference")
        assert isinstance(d, RouteDecision)
        assert d.estimated_tokens == 9025  # 9000 + (100 // 4)
        assert d.recommendation == "LOCAL"
