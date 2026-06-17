"""Proactive awareness subsystem (Phase 2, Applicant parity).

The pure decision logic lives in ``engine`` (no DB/LLM/IO) so it is fully
unit-testable; the live loop, collectors, and notification dispatch are wired
on top of it in a later increment, behind the ``APPLICANT_AWARENESS`` flag.
"""

from services.awareness.engine import (
    FIRE,
    SKIP,
    NEEDS_LLM,
    evaluate_condition,
    cooldown_ok,
    rate_limit_ok,
    snapshot_digest,
    should_resynthesize,
    decide_tick,
)

__all__ = [
    "FIRE",
    "SKIP",
    "NEEDS_LLM",
    "evaluate_condition",
    "cooldown_ok",
    "rate_limit_ok",
    "snapshot_digest",
    "should_resynthesize",
    "decide_tick",
]
