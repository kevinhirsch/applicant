"""ScoreBreakdown entity — per-posting weighted greens/reds score EXPLANATION.

Frozen dataclasses, pure, no IO — mirrors ``core/entities/viability_scoring.py``'s
style. ``ScoreBreakdown`` is the STORED explanation of a posting's persisted
``ViabilityScoring.score``: an ordered list of :class:`BreakdownFactor` entries
whose ``contribution`` values reconcile with that same 0..100 score, so a review
surface can show, transparently, WHAT drove a role's number instead of just the
bare number itself (EXPLAIN backend).

Built + persisted by ``application/services/explain_service.ExplainService``;
this module carries no behavior of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from applicant.core.ids import JobPostingId

#: "green" = helped the score, "red" = hurt it, "neutral" = informational / no
#: material directional pull (e.g. an unmeasured signal, or the optional LLM
#: nuance line, which carries no score weight of its own).
Polarity = Literal["green", "red", "neutral"]

#: Where a factor's NUMBER came from. "deterministic" covers every pure-rule
#: signal (posting_quality, jd_match, freshness, eligibility, ats_match_rate)
#: plus the reconciliation factor's arithmetic; "llm" tags a factor whose
#: content was produced by a model call. Today only the optional nuance line
#: is "llm" — and it is always weight/contribution 0, so a breakdown's SCORE
#: reconciliation never depends on the LLM being configured (deterministic
#: first, NFR-TOKEN-1 / offline parity).
Source = Literal["deterministic", "llm"]


@dataclass(frozen=True)
class BreakdownFactor:
    """One weighted signal that fed a posting's viability score.

    ``weight`` is this factor's share of the reconciled score (weights across
    a breakdown's deterministic factors sum to ~1.0; the reconciliation
    factor's weight is its own share of the total residual, informational
    only). ``contribution`` is the signed points on the SAME 0..100 scale as
    ``ScoreBreakdown.score * 100`` — summing every factor's ``contribution``
    reconciles with the persisted score (see ``ExplainService.build_breakdown``).
    """

    label: str
    polarity: Polarity
    weight: float
    contribution: float
    source: Source = "deterministic"
    detail: str = ""


@dataclass(frozen=True)
class ScoreBreakdown:
    """The persisted, per-posting greens/reds explanation for a viability score."""

    posting_id: JobPostingId
    score: float  # 0.0..1.0, same scale as ViabilityScoring.score
    factors: tuple[BreakdownFactor, ...] = field(default_factory=tuple)
    summary: str = ""
