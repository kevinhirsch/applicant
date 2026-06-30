"""Cold-start discovery gate (#344) — pure core rule, no IO.

At cold start a campaign has no search criteria configured. With zero criteria the
viability scorer returns the documented neutral 0.75 (75/100), which clears the
default 70 threshold — so an ungated discovery run would surface and "pass" arbitrary
postings before the user has said what they want. This rule is the guard: discovery
must REFUSE to run until at least one concrete criterion is configured.

Hexagonal: this is a pure decision over a ``SearchCriteria`` (or ``None``); the
discovery service calls it and declines the run when it returns ``False``.
"""

from __future__ import annotations

from typing import Any


def has_any_criterion(criteria: Any) -> bool:
    """True when ``criteria`` carries at least one concrete search signal.

    A concrete signal is any non-empty target title, location, work mode, salary floor,
    keyword, or a non-blank human-readable statement. An empty/``None`` criteria object
    (the cold-start default) has none, so discovery should not run yet.
    """
    if criteria is None:
        return False
    if (getattr(criteria, "human_readable", "") or "").strip():
        return True
    for attr in ("titles", "locations", "work_modes", "keywords"):
        if tuple(getattr(criteria, attr, ()) or ()):
            return True
    return getattr(criteria, "salary_floor", None) is not None


def require_criteria_before_discovery(criteria: Any) -> None:
    """Raise ``DiscoveryNotReady`` unless at least one criterion is configured (#344).

    Called at the top of a discovery run so the engine declines to run — with a clear,
    actionable reason — until the user has set what they are actually looking for,
    instead of surfacing arbitrary postings on the cold-start neutral score.
    """
    if not has_any_criterion(criteria):
        raise DiscoveryNotReady(
            "Discovery needs at least one search criterion (a target title, location, "
            "work mode, salary floor, or keyword) before it can run. Set your search "
            "criteria first."
        )


class DiscoveryNotReady(RuntimeError):
    """Discovery was asked to run before any search criterion was configured (#344)."""
