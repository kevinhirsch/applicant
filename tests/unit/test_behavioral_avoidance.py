"""Unit tests for BehavioralAvoidanceStrategy — score-based captcha avoidance.

Verifies that:
- classify() returns AVOID for score-based kinds (RECAPTCHA_V3, TURNSTILE)
- classify() returns HANDOFF for all other kinds
- resolve() returns CaptchaOutcome with the correct disposition and solved=False
- detail field is meaningful in both paths
- Seeded rng makes behavior deterministic
- _AVOIDABLE constant matches the classification logic
"""

from __future__ import annotations

import random

import pytest

from applicant.adapters.captcha.behavioral_avoidance import (
    BehavioralAvoidanceStrategy,
    _AVOIDABLE,
)
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaKind,
    CaptchaOutcome,
)


# ---------------------------------------------------------------------------
# Parallel-safety: clear any module-level caches so xdist workers stay
# isolated.  BehavioralAvoidanceStrategy currently has no lru_cache, but the
# fixture protects against future additions that might add one.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _xdist_safety() -> None:
    """
    Autouse fixture that resets module-level caches for parallel xdist safety.

    Currently a no-op because BehavioralAvoidanceStrategy has no lru_cache'd
    functions or module-level singletons; kept as a placeholder so adding a
    cache in the future does not silently break the parallel suite.
    """
    yield


# ============================== classify() ==================================


class TestClassify:
    """classify() must return the exact CaptchaDisposition per captcha kind."""

    @pytest.mark.unit
    def test_avoid_for_recaptcha_v3(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://example.com", kind=CaptchaKind.RECAPTCHA_V3)
        assert strategy.classify(ctx) is CaptchaDisposition.AVOID

    @pytest.mark.unit
    def test_avoid_for_turnstile(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://example.com", kind=CaptchaKind.TURNSTILE)
        assert strategy.classify(ctx) is CaptchaDisposition.AVOID

    @pytest.mark.unit
    def test_handoff_for_recaptcha_v2(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://example.com", kind=CaptchaKind.RECAPTCHA_V2)
        assert strategy.classify(ctx) is CaptchaDisposition.HANDOFF

    @pytest.mark.unit
    def test_handoff_for_hcaptcha(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://example.com", kind=CaptchaKind.HCAPTCHA)
        assert strategy.classify(ctx) is CaptchaDisposition.HANDOFF

    @pytest.mark.unit
    @pytest.mark.parametrize("kind", [CaptchaKind.UNKNOWN])
    def test_handoff_for_unknown(self, kind: CaptchaKind) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://example.com", kind=kind)
        assert strategy.classify(ctx) is CaptchaDisposition.HANDOFF

    @pytest.mark.unit
    def test_classify_returns_known_disposition_for_every_kind(self) -> None:
        """All known kinds produce either AVOID or HANDOFF (never SOLVE)."""
        strategy = BehavioralAvoidanceStrategy()
        for kind in CaptchaKind:
            ctx = CaptchaContext(url="https://example.com", kind=kind)
            disposition = strategy.classify(ctx)
            assert disposition in (
                CaptchaDisposition.AVOID,
                CaptchaDisposition.HANDOFF,
            ), f"unexpected disposition {disposition} for {kind}"


# ============================== resolve() ===================================


class TestResolve:
    """resolve() returns a CaptchaOutcome with the correct fields per path."""

    @pytest.mark.unit
    def test_resolve_returns_captcha_outcome_type(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.RECAPTCHA_V3)
        out = strategy.resolve(ctx)
        assert isinstance(out, CaptchaOutcome)

    @pytest.mark.unit
    def test_resolve_avoid_disposition_and_not_solved_for_avoidable(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.RECAPTCHA_V3)
        out = strategy.resolve(ctx)
        assert out.disposition is CaptchaDisposition.AVOID
        assert out.solved is False

    @pytest.mark.unit
    def test_resolve_handoff_disposition_and_not_solved_for_non_avoidable(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.RECAPTCHA_V2)
        out = strategy.resolve(ctx)
        assert out.disposition is CaptchaDisposition.HANDOFF
        assert out.solved is False

    @pytest.mark.unit
    def test_detail_mentions_stealth_for_avoid_path(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.TURNSTILE)
        out = strategy.resolve(ctx)
        assert "stealth" in out.detail.lower()
        assert len(out.detail) > 10  # meaningful, not a stub

    @pytest.mark.unit
    def test_detail_mentions_handoff_for_non_avoid_path(self) -> None:
        strategy = BehavioralAvoidanceStrategy()
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.HCAPTCHA)
        out = strategy.resolve(ctx)
        assert "handoff" in out.detail.lower() or "deferring" in out.detail.lower()
        assert len(out.detail) > 10


# ============================== determinism =================================


class TestDeterminism:
    """Seeded rng produces deterministic (reproducible) behavior."""

    @pytest.mark.unit
    def test_same_seed_produces_same_internal_state(self) -> None:
        """Two instances with the same rng seed reach identical elapsed_ms after
        an identical call sequence."""
        s1 = BehavioralAvoidanceStrategy(rng=random.Random(42))
        s2 = BehavioralAvoidanceStrategy(rng=random.Random(42))

        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.TURNSTILE)
        s1.resolve(ctx)
        s2.resolve(ctx)

        assert s1._human.elapsed_ms == pytest.approx(s2._human.elapsed_ms, abs=0.001)

    @pytest.mark.unit
    def test_different_seeds_produce_different_internal_state(self) -> None:
        """Different seeds almost certainly diverge on elapsed_ms (think_delay
        uses uniform random sampling)."""
        s1 = BehavioralAvoidanceStrategy(rng=random.Random(42))
        s2 = BehavioralAvoidanceStrategy(rng=random.Random(99))

        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.TURNSTILE)
        s1.resolve(ctx)
        s2.resolve(ctx)

        assert s1._human.elapsed_ms != pytest.approx(s2._human.elapsed_ms, abs=0.1)

    @pytest.mark.unit
    def test_resolve_outcome_is_deterministic_regardless_of_seed(self) -> None:
        """The CaptchaOutcome returned by resolve() is purely logic-driven;
        think_delay only advances the logical clock but does not change the
        outcome (disposition, solved, detail) returned to the caller."""
        ctx = CaptchaContext(url="https://x.com", kind=CaptchaKind.TURNSTILE)

        out1 = BehavioralAvoidanceStrategy(rng=random.Random(1)).resolve(ctx)
        out2 = BehavioralAvoidanceStrategy(rng=random.Random(9999)).resolve(ctx)

        assert out1 == out2


# ============================== _AVOIDABLE ==================================


class TestAvoidableConstant:
    """_AVOIDABLE defines which captcha kinds are treated as score-based."""

    @pytest.mark.unit
    def test_contains_recaptcha_v3(self) -> None:
        assert CaptchaKind.RECAPTCHA_V3 in _AVOIDABLE

    @pytest.mark.unit
    def test_contains_turnstile(self) -> None:
        assert CaptchaKind.TURNSTILE in _AVOIDABLE

    @pytest.mark.unit
    def test_excludes_recaptcha_v2(self) -> None:
        assert CaptchaKind.RECAPTCHA_V2 not in _AVOIDABLE

    @pytest.mark.unit
    def test_excludes_hcaptcha(self) -> None:
        assert CaptchaKind.HCAPTCHA not in _AVOIDABLE

    @pytest.mark.unit
    def test_excludes_unknown(self) -> None:
        assert CaptchaKind.UNKNOWN not in _AVOIDABLE
