"""Beta-distribution confidence for entity facts (Phase 1, ADR-009 analogue).

A fact's belief is modeled as Beta(alpha, beta). Each corroborating
observation bumps ``alpha``; each contradicting one bumps ``beta``. The
surfaced confidence is the distribution mean ``alpha / (alpha + beta)`` — it
rises toward 1.0 with repeated confirmation and falls when contradicted, while
a single unconfirmed fact sits near the 0.5 prior.

Pure standard-library so it can be unit-tested without app dependencies.
"""

from __future__ import annotations

from typing import Iterable, Tuple

# Uniform prior Beta(1, 1): a brand-new, unconfirmed fact => confidence 0.5.
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0


def confidence(alpha: float, beta: float) -> float:
    """Mean of Beta(alpha, beta), clamped to [0, 1]."""
    total = alpha + beta
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, alpha / total))


def observe(alpha: float, beta: float, positive: bool, weight: float = 1.0) -> Tuple[float, float]:
    """Apply one observation. ``positive`` corroborates; otherwise contradicts.

    ``weight`` lets a strong/explicit signal count for more than a weak/inferred
    one. Returns the updated ``(alpha, beta)``.
    """
    w = max(0.0, float(weight))
    if positive:
        return alpha + w, beta
    return alpha, beta + w


def fold(observations: Iterable[bool], alpha: float = PRIOR_ALPHA, beta: float = PRIOR_BETA,
         weight: float = 1.0) -> Tuple[float, float]:
    """Fold a sequence of boolean observations onto a prior."""
    for positive in observations:
        alpha, beta = observe(alpha, beta, positive, weight)
    return alpha, beta
