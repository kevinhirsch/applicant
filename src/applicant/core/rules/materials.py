"""Pure material-generation policy rules (FR-RESUME-9/10, FR-ANSWER-1).

Three pure, side-effect-free decisions that the ``MaterialService`` leans on so the
domain rules cannot be bypassed by an adapter:

* :func:`should_generate_cover_letter` — cover letters are generated **on demand**
  (FR-RESUME-10): a per-campaign default (off by default) the role can override.
* :func:`classify_screening_question` — split a screening question into **factual**
  (answer deterministically, no fabrication; EEO ones decline) vs **essay**
  (LLM-generated from true history, filtered, reviewed) (FR-ANSWER-1).
* :func:`clamp_aggressiveness` / :data:`AGGRESSIVENESS_*` — the truthful framing
  dial (FR-RESUME-9). The control ships present-but-grayed (FR-UI-2); the backend
  setting is clamped and ready so wiring it live is a UI change only.

Kept in the pure core (no I/O) so every path — service, router, BDD — shares one
definition and the truthfulness guardrail can never be gamed by the dial.
"""

from __future__ import annotations

from enum import Enum

from applicant.core.rules.sensitive_fields import is_sensitive_field

# === cover letters on demand (FR-RESUME-10) ================================


def should_generate_cover_letter(
    *,
    campaign_default: bool = False,
    role_requires: bool | None = None,
) -> bool:
    """Decide whether a role warrants a cover letter (FR-RESUME-10).

    Cover letters are **opt-in**: the per-campaign default (``campaign_default``,
    off by default) is the baseline, and a specific role may override it either way
    (``role_requires`` True forces one, False suppresses one). When the role has no
    opinion (``None``) the campaign default stands.
    """
    if role_requires is not None:
        return role_requires
    return campaign_default


# === screening: factual vs essay (FR-ANSWER-1) =============================


class ScreeningKind(str, Enum):
    """How a screening question must be answered (FR-ANSWER-1)."""

    FACTUAL = "factual"  # deterministic from the attribute cloud; no fabrication
    ESSAY = "essay"  # LLM-generated from true history; filtered + reviewed
    SENSITIVE = "sensitive"  # EEO/demographic: follow the sensitive-field policy


#: Cue phrases that mark a long-form / essay question (FR-ANSWER-1). Conservative:
#: anything not clearly factual is treated as essay so it routes through review.
_ESSAY_CUES: tuple[str, ...] = (
    "why do you want",
    "why are you",
    "describe a time",
    "tell us about",
    "tell me about",
    "describe your",
    "what interests you",
    "what excites you",
    "cover letter",
    "in your own words",
    "what makes you",
    "how would you",
    "how do you",
    "give an example",
    "give us an example",
    "walk us through",
    "what motivates",
    "describe how",
    "describe a",
    "describe the",
    "tell us",
    "tell me",
    "why do you",
    "share an example",
    "provide an example",
)

#: Cue phrases that mark a short, factual question answerable from stored data.
_FACTUAL_CUES: tuple[str, ...] = (
    "how many years",
    "years of experience",
    "work authorization",
    "authorized to work",
    "require sponsorship",
    "need sponsorship",
    "visa",
    "salary",
    "compensation",
    "desired pay",
    "expected pay",
    "willing to relocate",
    "start date",
    "available to start",
    "do you have",
    "are you able",
    "yes or no",
    "yes/no",
)

#: Self-identification EEO field is short (a bare label / closed question), not a
#: multi-word essay prompt that merely mentions a protected attribute. Above this
#: word count a sensitive substring is treated as essay subject-matter, not an EEO
#: self-id field (e.g. "How do you foster gender diversity?") (FR-ATTR-6).
_MAX_EEO_FIELD_WORDS = 6


def _is_eeo_self_identification(text: str) -> bool:
    """True only for an actual EEO self-identification field, not an essay prompt.

    A sensitive marker alone is not enough: "How do you foster gender diversity?"
    is an ESSAY about diversity, not a demographic self-id field. We require the
    field to be SHORT (a bare label / closed question) before treating a sensitive
    marker as a self-identification field (FR-ATTR-6, NFR-PRIV-1).
    """
    if not is_sensitive_field(text):
        return False
    return len(text.split()) <= _MAX_EEO_FIELD_WORDS


def classify_screening_question(question: str) -> ScreeningKind:
    """Classify a screening question as factual, essay, or sensitive (FR-ANSWER-1).

    Order matters: explicit ESSAY cues win first so a long-form prompt that merely
    mentions a protected attribute ("How do you foster gender diversity?") routes
    through review instead of the sensitive-field decline path. Then an actual EEO
    self-identification FIELD (short label / closed question) is detected, then
    factual cues. Anything ambiguous defaults to **essay** so it always passes
    through the truthfulness filters + the review gate rather than being answered
    blindly.
    """
    text = (question or "").strip().lower()
    if not text:
        return ScreeningKind.ESSAY
    if any(cue in text for cue in _ESSAY_CUES):
        return ScreeningKind.ESSAY
    if _is_eeo_self_identification(text):
        return ScreeningKind.SENSITIVE
    if any(cue in text for cue in _FACTUAL_CUES):
        return ScreeningKind.FACTUAL
    # Short closed questions (ends with '?', few words) lean factual; otherwise essay.
    words = text.split()
    if len(words) <= 8 and text.endswith("?"):
        return ScreeningKind.FACTUAL
    return ScreeningKind.ESSAY


# === aggressiveness dial (FR-RESUME-9, dormant per FR-UI-2) ================

#: The truthful-framing dial range (FR-RESUME-9). 0 = conservative phrasing,
#: 100 = maximally assertive (still truthful) framing.
AGGRESSIVENESS_MIN = 0
AGGRESSIVENESS_MAX = 100
#: Default sits low/conservative; the control is grayed until Phase 4 (FR-UI-2).
AGGRESSIVENESS_DEFAULT = 20


def clamp_aggressiveness(value: int | None) -> int:
    """Clamp the aggressiveness dial into [MIN, MAX] (FR-RESUME-9).

    Pure + total so the backend setting is always valid even though the UI control
    is dormant/grayed (FR-UI-2): an out-of-range or missing value falls back to the
    conservative default rather than raising.
    """
    if value is None:
        return AGGRESSIVENESS_DEFAULT
    try:
        v = int(value)
    except (TypeError, ValueError):
        return AGGRESSIVENESS_DEFAULT
    return max(AGGRESSIVENESS_MIN, min(v, AGGRESSIVENESS_MAX))


def aggressiveness_directive(value: int) -> str:
    """Render the dial as a generation directive (truthful framing only).

    Used to bias the LLM prompt's *framing* (assertive vs measured) WITHOUT ever
    relaxing the truthfulness guardrail — the dial reorders/re-emphasizes, it never
    licenses fabrication (FR-RESUME-2/9).
    """
    v = clamp_aggressiveness(value)
    if v >= 67:
        return (
            "Frame the candidate's REAL accomplishments assertively and lead with "
            "impact and metrics. Never add a claim that is not in the source."
        )
    if v <= 33:
        return (
            "Frame the candidate's REAL accomplishments in measured, understated "
            "terms. Never add a claim that is not in the source."
        )
    return (
        "Frame the candidate's REAL accomplishments in a balanced, confident voice. "
        "Never add a claim that is not in the source."
    )
