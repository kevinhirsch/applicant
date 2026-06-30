"""Per-company application volume cap (Issue #371).

The campaign-level throughput hard cap (``core/entities/campaign.py``, #195)
bounds total volume per campaign. This is a distinct, finer-grained guard: a
configurable cap on how many applications go to a SINGLE employer within a time
window, holding overflow for the next window / human review. The cap is
window-scoped, so it resets when a new window begins (the caller passes the
in-window count, which is zero at the start of a fresh window).

Pure core rule (no I/O): window accounting (which applications fall in the
current window) is the caller's concern; this rule is the admission decision.
"""

from __future__ import annotations

#: Conservative default: at most this many applications to one company per window.
DEFAULT_PER_COMPANY_CAP = 3


def admit_company_application(
    *,
    company: str,
    sent_in_window: int,
    cap: int = DEFAULT_PER_COMPANY_CAP,
) -> bool:
    """Decide whether one more application to ``company`` may be sent (#371).

    ``sent_in_window`` is the count of applications already sent to this company
    in the current window. Returns ``True`` if admitting one more stays within
    ``cap``; ``False`` (hold the overflow) once the cap is reached. Because the
    count is window-scoped, a fresh window (``sent_in_window == 0``) admits
    again — the cap resets per window.
    """
    if cap <= 0:
        return False
    return sent_in_window < cap
