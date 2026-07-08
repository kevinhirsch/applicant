"""Sensitive-field (EEO/demographic) policy (FR-ATTR-6).

Demographic / EEO / self-identification fields are filled **only** from the user's
explicit stored answer, **never** AI-guessed. When the user has not provided an
explicit answer the policy default is "decline to self-identify".

This rule lives in the pure core so the pre-fill adapter (Phase 2) physically
cannot AI-guess these fields: it must route every fill decision through
``decide_sensitive_fill``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from applicant.core.errors import SensitiveFieldViolation
from applicant.core.locale_config import DEFAULT_LOCALE, LocaleConfig

#: Active locale configuration. Replace to adapt EEO labels for non-US locales.
_LOCALE: LocaleConfig = DEFAULT_LOCALE

#: The canonical default when the user has no explicit stored answer (FR-ATTR-6).
DECLINE_TO_SELF_IDENTIFY: str = DEFAULT_LOCALE.decline_to_self_identify

#: Unambiguous multi-character substrings that mark a field as sensitive/EEO.
#: These are distinctive enough that raw substring matching does not misfire.
_SENSITIVE_SUBSTRING_MARKERS: tuple[str, ...] = DEFAULT_LOCALE.sensitive_eeo_markers

#: Short / ambiguous markers that appear inside ordinary words (e.g. "age" in
#: "Manager"/"Message", "sex" in "unisex", "race" in "embrace"). These must be
#: matched on WORD BOUNDARIES so they only fire on the real EEO field (FR-ATTR-6).
_SENSITIVE_WORD_MARKERS: tuple[str, ...] = DEFAULT_LOCALE.sensitive_word_markers

#: Pre-compiled word-boundary patterns for the ambiguous short markers.
_SENSITIVE_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _SENSITIVE_WORD_MARKERS) + r")\b"
)


# === work authorization (P2-7) ==============================================
# Work-authorization questions are in the same never-guess family as the EEO
# fields below, but with the OPPOSITE default: EEO defaults to declining to
# self-identify, while work auth is a routine, expected application question —
# answered from the user's OWN stored answer when present, and otherwise left
# for the human. This module only decides membership; the handling lives with
# the callers (MaterialService / PrefillService).

#: Strong multi-word substrings that unambiguously mark a work-auth question.
_WORK_AUTH_SUBSTRING_CUES: tuple[str, ...] = DEFAULT_LOCALE.work_auth_cues

#: Short/ambiguous markers ("visa", "citizen", "sponsorship") matched on word
#: boundaries — and only for SHORT questions, so a long essay prompt that merely
#: mentions a visa or citizens does not misroute (mirrors the EEO word markers).
_WORK_AUTH_WEAK_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(m) for m in DEFAULT_LOCALE.work_auth_weak_markers)
    + r")\b"
)

#: A weak marker counts only when the question is this short (a bare field
#: label or closed question, e.g. "Visa status" / "Are you a citizen?").
_MAX_WEAK_WORK_AUTH_WORDS = 8


def is_work_auth_question(text: str) -> bool:
    """True if ``text`` asks about the candidate's own work authorization,
    visa, or sponsorship status (P2-7).

    These questions must NEVER be answered by an LLM guess: an invented "No, I
    don't need sponsorship" contains no fact-class tokens, so it would sail
    through the fabrication check — the refusal has to happen at classification
    time. Detection is deliberately conservative in the safe direction: a
    matched question routes to the user's own stored answer (or to the human),
    and an unmatched phrasing still lands in the ordinary review lane.
    """
    if not text:
        return False
    low = text.lower()
    if any(cue in low for cue in _WORK_AUTH_SUBSTRING_CUES):
        return True
    if len(low.split()) <= _MAX_WEAK_WORK_AUTH_WORDS:
        return bool(_WORK_AUTH_WEAK_RE.search(low))
    return False


@dataclass(frozen=True)
class SensitiveFillDecision:
    """Outcome of evaluating a sensitive field."""

    field_label: str
    is_sensitive: bool
    value: str  # the value to fill (never AI-derived for sensitive fields)
    from_explicit_answer: bool


def is_sensitive_field(field_label: str) -> bool:
    """True if ``field_label`` looks like an EEO/demographic/self-id field."""
    if not field_label:
        return False
    low = field_label.lower()
    if any(marker in low for marker in _SENSITIVE_SUBSTRING_MARKERS):
        return True
    return bool(_SENSITIVE_WORD_RE.search(low))


def decide_sensitive_fill(
    field_label: str,
    explicit_answer: str | None,
    *,
    ai_suggested: str | None = None,
) -> SensitiveFillDecision:
    """Decide what (if anything) to fill into a sensitive field.

    Args:
        field_label: the detected form field label.
        explicit_answer: the user's explicitly stored answer, or ``None``.
        ai_suggested: a value an LLM *would have* guessed. Providing this for a
            sensitive field is a programming error and raises
            ``SensitiveFieldViolation`` — it exists so callers can pass through a
            single decision point and have the core reject the guess.

    For non-sensitive fields this returns the explicit answer unchanged (the
    caller's normal mapping/AI path applies elsewhere).
    """
    sensitive = is_sensitive_field(field_label)
    if not sensitive:
        return SensitiveFillDecision(
            field_label=field_label,
            is_sensitive=False,
            value=explicit_answer or "",
            from_explicit_answer=bool(explicit_answer),
        )

    if ai_suggested is not None:
        raise SensitiveFieldViolation(
            f"Refusing to AI-guess sensitive field {field_label!r}; "
            "sensitive fields fill only from explicit stored answers."
        )

    if explicit_answer:
        return SensitiveFillDecision(
            field_label=field_label,
            is_sensitive=True,
            value=explicit_answer,
            from_explicit_answer=True,
        )

    return SensitiveFillDecision(
        field_label=field_label,
        is_sensitive=True,
        value=DECLINE_TO_SELF_IDENTIFY,
        from_explicit_answer=False,
    )
