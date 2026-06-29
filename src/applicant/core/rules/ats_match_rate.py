"""Field-match-rate / probable-wrong-ATS rule (FR-PREFILL-2/6, issue #177).

Universal-ATS coverage drives ANY application form via the vendor-agnostic generic
live-DOM driver (issue #173). But "we filled the form" is only meaningful if the
values the engine resolved actually landed in the page's fields. When the wrong page
model is applied — or a form simply does not map to any stored attribute — the
selectors miss, pre-fill fills (almost) nothing, and a naive loop would happily walk
to the final-submit gate having filled garbage.

This pure rule turns that into an observable signal: compute the field-match rate
(fields actually filled / fields detected) and decide whether a run is a probable
wrong-ATS / near-empty fill that must be FLAGGED for human review rather than offered
for submission.

Pure core (no IO): the pre-fill service computes the counts during the live walk and
routes the verdict through here, so the floor is enforced in one place and is unit
testable without a browser.
"""

from __future__ import annotations

#: Default minimum acceptable field-match rate (filled / detected). Below this floor
#: a run is treated as a probable wrong-ATS / near-empty fill and flagged for human
#: review instead of being offered for final submission. Conservative (0.2 = 20%):
#: a real form where most detected fields go unfilled is the failure mode #177 targets,
#: while a normal run (most required fields mapped) clears it comfortably. The deploy
#: can tune it via ``ATS_MATCH_RATE_FLOOR``.
DEFAULT_MATCH_RATE_FLOOR = 0.2


def field_match_rate(filled: int, detected: int) -> float:
    """The fraction of detected fillable fields the engine actually filled.

    ``filled / detected`` clamped to ``[0.0, 1.0]``. A page with NO detected fields
    is treated as a perfect (1.0) rate: there was nothing to fill, so there is nothing
    to flag (e.g. a bare review/submit page). Negative / inverted inputs are clamped
    defensively so a miscount can never produce a nonsense rate.
    """
    if detected <= 0:
        return 1.0
    if filled <= 0:
        return 0.0
    return min(1.0, filled / detected)


def is_probable_wrong_ats(filled: int, detected: int, *, floor: float = DEFAULT_MATCH_RATE_FLOOR) -> bool:
    """True when a run looks like the wrong ATS / a near-empty fill (issue #177).

    Fires only when at least one fillable field was DETECTED (otherwise there was
    nothing to match) AND the field-match rate fell below ``floor``. A run that detected
    fields but matched none of them (rate 0.0) is the clearest wrong-ATS signal and is
    always flagged.
    """
    if detected <= 0:
        return False
    return field_match_rate(filled, detected) < floor
