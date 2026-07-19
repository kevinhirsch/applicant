"""Unit tests for CaptchaSolver composite adapter (issue #350).

Tests the config-driven composite in isolation by injecting fake strategy
adapters with controllable classify/resolve return values, so no browser,
network, or real adapter internals are exercised.

CaptchaContext (frozen dataclass with a dict field) is NOT hashable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from applicant.adapters.captcha.composite import (
    CaptchaSolver,
    STRATEGIES,
    STRATEGY_AVOID,
    STRATEGY_HUMAN,
    STRATEGY_SERVICE,
)
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaOutcome,
)


# ---------------------------------------------------------------------------
# Parallel-safety: no module-level lru_cache or state to clear in this
# module, but the autouse fixture ensures xdist workers don't cross-pollute.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_module_state() -> None:
    """No module-level cache to clear; present for parallel safety."""
    return


# ---------------------------------------------------------------------------
# Adapter fake — controllable classify/resolve, records calls for assertion.
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Mini fake: returns fixed classify/resolve values, records invocations."""

    def __init__(
        self,
        classify: CaptchaDisposition = CaptchaDisposition.HANDOFF,
        resolve: CaptchaOutcome | None = None,
    ) -> None:
        self._classify = classify
        self._resolve = resolve or CaptchaOutcome(
            disposition=classify, solved=False, detail="fake"
        )
        self.classify_calls: list[CaptchaContext] = []
        self.resolve_calls: list[CaptchaContext] = []

    def classify(self, context: CaptchaContext) -> CaptchaDisposition:
        self.classify_calls.append(context)
        return self._classify

    def resolve(self, context: CaptchaContext) -> CaptchaOutcome:
        self.resolve_calls.append(context)
        return self._resolve


# ---------------------------------------------------------------------------
# Shared fixture context + adapter fixture instances.
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> CaptchaContext:
    return CaptchaContext(url="https://example.com/login")


@pytest.fixture
def handoff_adapter() -> _FakeAdapter:
    return _FakeAdapter(
        classify=CaptchaDisposition.HANDOFF,
        resolve=CaptchaOutcome(
            disposition=CaptchaDisposition.HANDOFF, solved=False
        ),
    )


@pytest.fixture
def avoid_adapter() -> _FakeAdapter:
    return _FakeAdapter(
        classify=CaptchaDisposition.AVOID,
        resolve=CaptchaOutcome(
            disposition=CaptchaDisposition.AVOID, solved=False
        ),
    )


@pytest.fixture
def solve_adapter() -> _FakeAdapter:
    return _FakeAdapter(
        classify=CaptchaDisposition.SOLVE,
        resolve=CaptchaOutcome(
            disposition=CaptchaDisposition.SOLVE, solved=True
        ),
    )


# ===================================================================
# Construction
# ===================================================================


class TestConstruction:
    """CaptchaSolver construction and strategy defaults."""

    @pytest.mark.unit
    def test_default_strategy_is_human(self) -> None:
        solver = CaptchaSolver()
        assert solver.strategy == STRATEGY_HUMAN

    @pytest.mark.unit
    def test_explicit_strategy(self) -> None:
        solver = CaptchaSolver(strategy=STRATEGY_AVOID)
        assert solver.strategy == STRATEGY_AVOID

    @pytest.mark.unit
    def test_invalid_strategy_falls_back_to_human(self) -> None:
        solver = CaptchaSolver(strategy="bogus")
        assert solver.strategy == STRATEGY_HUMAN

    @pytest.mark.unit
    def test_all_valid_strategies(self) -> None:
        for s in STRATEGIES:
            solver = CaptchaSolver(strategy=s)
            assert solver.strategy == s

    @pytest.mark.unit
    def test_strategy_property_returns_stored_value(self) -> None:
        solver = CaptchaSolver(strategy=STRATEGY_SERVICE)
        assert solver.strategy == STRATEGY_SERVICE

    @pytest.mark.unit
    def test_injected_adapters_are_stored(
        self,
        handoff_adapter: _FakeAdapter,
        avoid_adapter: _FakeAdapter,
        solve_adapter: _FakeAdapter,
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID,
            avoidance=avoid_adapter,
            service=solve_adapter,
            handoff=handoff_adapter,
        )
        assert solver._avoidance is avoid_adapter
        assert solver._service is solve_adapter
        assert solver._handoff is handoff_adapter


# ===================================================================
# stats
# ===================================================================


class TestStats:
    """stats() telemetry snapshot."""

    @pytest.mark.unit
    def test_initial_stats_zeros(self) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE, service=MagicMock()
        )
        s = solver.stats()
        assert s["strategy"] == STRATEGY_SERVICE
        assert s["service_configured"] is True
        assert s["attempts"] == 0
        assert s["solved"] == 0
        assert s["avoided"] == 0
        assert s["handed_off"] == 0

    @pytest.mark.unit
    def test_no_service_reports_not_configured(self) -> None:
        solver = CaptchaSolver()
        s = solver.stats()
        assert s["service_configured"] is False

    @pytest.mark.unit
    def test_stats_reflects_resolve_counts(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN,
            handoff=handoff_adapter,
            avoidance=MagicMock(),
        )
        solver.resolve(ctx)
        s = solver.stats()
        assert s["attempts"] == 1
        assert s["handed_off"] == 1
        assert s["solved"] == 0
        assert s["avoided"] == 0


# ===================================================================
# classify
# ===================================================================


class TestClassify:
    """classify() dispatching logic."""

    @pytest.mark.unit
    def test_human_strategy_always_handoff(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        """human strategy short-circuits — no adapter classify called."""
        avoidance = MagicMock()
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN,
            handoff=handoff_adapter,
            avoidance=avoidance,
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.HANDOFF
        avoidance.classify.assert_not_called()

    @pytest.mark.unit
    def test_avoid_strategy_returns_avoidance_classify(
        self, ctx: CaptchaContext, avoid_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID, avoidance=avoid_adapter
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.AVOID
        assert avoid_adapter.classify_calls == [ctx]

    @pytest.mark.unit
    def test_avoid_strategy_when_avoidance_returns_handoff(
        self, ctx: CaptchaContext
    ) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID, avoidance=handoff_avoid
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.HANDOFF

    @pytest.mark.unit
    def test_service_strategy_avoidance_takes_priority(
        self, ctx: CaptchaContext, avoid_adapter: _FakeAdapter
    ) -> None:
        """Even in service mode, avoidance classify is checked first."""
        service = MagicMock()
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE,
            avoidance=avoid_adapter,
            service=service,
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.AVOID
        service.classify.assert_not_called()

    @pytest.mark.unit
    def test_service_strategy_solve_when_not_avoidable(
        self, ctx: CaptchaContext, solve_adapter: _FakeAdapter
    ) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE,
            avoidance=handoff_avoid,
            service=solve_adapter,
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.SOLVE
        assert solve_adapter.classify_calls == [ctx]

    @pytest.mark.unit
    def test_service_strategy_no_service_handoff(
        self, ctx: CaptchaContext
    ) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE,
            avoidance=handoff_avoid,
            service=None,
        )
        result = solver.classify(ctx)
        assert result is CaptchaDisposition.HANDOFF

    @pytest.mark.unit
    def test_classify_passes_context(self, ctx: CaptchaContext) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID, avoidance=handoff_avoid
        )
        solver.classify(ctx)
        assert handoff_avoid.classify_calls == [ctx]


# ===================================================================
# resolve
# ===================================================================


class TestResolve:
    """resolve() dispatching and counters."""

    @pytest.mark.unit
    def test_human_strategy_routes_to_handoff(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN, handoff=handoff_adapter
        )
        result = solver.resolve(ctx)
        assert result is handoff_adapter._resolve
        assert len(handoff_adapter.resolve_calls) == 1

    @pytest.mark.unit
    def test_avoid_routes_to_avoidance(
        self, ctx: CaptchaContext, avoid_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID, avoidance=avoid_adapter
        )
        result = solver.resolve(ctx)
        assert result is avoid_adapter._resolve

    @pytest.mark.unit
    def test_solve_routes_to_service(
        self, ctx: CaptchaContext, solve_adapter: _FakeAdapter
    ) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE,
            avoidance=handoff_avoid,
            service=solve_adapter,
        )
        result = solver.resolve(ctx)
        assert result is solve_adapter._resolve

    @pytest.mark.unit
    def test_classify_handoff_routes_to_handoff(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        """When classify doesn't return AVOID or SOLVE, hand off."""
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN, handoff=handoff_adapter
        )
        result = solver.resolve(ctx)
        assert result is handoff_adapter._resolve

    @pytest.mark.unit
    def test_resolve_passes_context(self, ctx: CaptchaContext) -> None:
        avoid = _FakeAdapter(classify=CaptchaDisposition.AVOID)
        solver = CaptchaSolver(strategy=STRATEGY_AVOID, avoidance=avoid)
        solver.resolve(ctx)
        assert avoid.resolve_calls == [ctx]

    @pytest.mark.unit
    def test_avoid_records_avoided(
        self, ctx: CaptchaContext, avoid_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_AVOID, avoidance=avoid_adapter
        )
        solver.resolve(ctx)
        s = solver.stats()
        assert s["attempts"] == 1
        assert s["avoided"] == 1
        assert s["solved"] == 0
        assert s["handed_off"] == 0

    @pytest.mark.unit
    def test_handoff_records_handed_off(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN, handoff=handoff_adapter
        )
        solver.resolve(ctx)
        s = solver.stats()
        assert s["attempts"] == 1
        assert s["handed_off"] == 1
        assert s["solved"] == 0
        assert s["avoided"] == 0

    @pytest.mark.unit
    def test_solve_records_solved(
        self, ctx: CaptchaContext, solve_adapter: _FakeAdapter
    ) -> None:
        handoff_avoid = _FakeAdapter(classify=CaptchaDisposition.HANDOFF)
        solver = CaptchaSolver(
            strategy=STRATEGY_SERVICE,
            avoidance=handoff_avoid,
            service=solve_adapter,
        )
        solver.resolve(ctx)
        s = solver.stats()
        assert s["attempts"] == 1
        assert s["solved"] == 1
        assert s["avoided"] == 0
        assert s["handed_off"] == 0

    @pytest.mark.unit
    def test_multiple_resolves_accumulate(
        self, ctx: CaptchaContext, handoff_adapter: _FakeAdapter
    ) -> None:
        solver = CaptchaSolver(
            strategy=STRATEGY_HUMAN, handoff=handoff_adapter
        )
        solver.resolve(ctx)
        solver.resolve(ctx)
        solver.resolve(ctx)
        s = solver.stats()
        assert s["attempts"] == 3
        assert s["handed_off"] == 3
        assert s["solved"] == 0
        assert s["avoided"] == 0


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge cases and degrade-to-handoff contract."""

    @pytest.mark.unit
    def test_empty_url_does_not_raise(
        self, ctx: CaptchaContext
    ) -> None:
        solver = CaptchaSolver(strategy=STRATEGY_HUMAN)
        empty_ctx = CaptchaContext(url="")
        result = solver.resolve(empty_ctx)
        assert result.disposition is CaptchaDisposition.HANDOFF
        assert result.solved is False
