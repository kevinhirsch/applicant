"""Duplicate-application / re-apply cooldown guard (Issue #368).

Discovery dedup (#196) collapses near-duplicate *listings* within one run. This
guard is a separate, application-level concern: before applying, the engine must
check the user's own application **history** and skip (or hold) a posting that
matches an already-applied company+role within a configurable cooldown window.
After the window elapses, the same role is eligible again.

Pure core rule (no I/O): the history is passed in as a list of prior-application
records so the same definition is shared by the service, router, and BDD specs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

#: Conservative default cooldown: don't re-apply to the same role within 30 days.
DEFAULT_COOLDOWN_DAYS = 30


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


def is_duplicate_application(
    candidate: Mapping,
    history: Iterable[Mapping],
    *,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> bool:
    """True if applying to ``candidate`` now would duplicate a recent application.

    A duplicate is a history record with the same company AND role whose
    ``days_ago`` is within ``cooldown_days``. Records older than the cooldown
    do not count — the role becomes eligible again once the window elapses.
    """
    cand_company = _norm(candidate.get("company"))
    cand_role = _norm(candidate.get("role") or candidate.get("title"))
    if not cand_company or not cand_role:
        return False

    for prior in history:
        if _norm(prior.get("company")) != cand_company:
            continue
        if _norm(prior.get("role") or prior.get("title")) != cand_role:
            continue
        days_ago = prior.get("days_ago")
        if days_ago is None:
            # No age information → treat as a recent duplicate (fail-safe).
            return True
        try:
            if float(days_ago) <= cooldown_days:
                return True
        except (TypeError, ValueError):
            return True
    return False
