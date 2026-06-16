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

#: The canonical default when the user has no explicit stored answer (FR-ATTR-6).
DECLINE_TO_SELF_IDENTIFY = "decline to self-identify"

#: Unambiguous multi-character substrings that mark a field as sensitive/EEO.
#: These are distinctive enough that raw substring matching does not misfire.
_SENSITIVE_SUBSTRING_MARKERS: tuple[str, ...] = (
    "ethnicity",
    "ethnic",
    "gender",
    "disability",
    "disabilities",
    "veteran",
    "protected veteran",
    "sexual orientation",
    "lgbt",
    "pregnan",
    "religion",
    "national origin",
    "marital",
    "date of birth",
    "self-identification",
    "self identify",
    "self-identify",
    "diversity",
    "hispanic",
    "latino",
    "latinx",
    "military",
)

#: Short / ambiguous markers that appear inside ordinary words (e.g. "age" in
#: "Manager"/"Message", "sex" in "unisex", "race" in "embrace"). These must be
#: matched on WORD BOUNDARIES so they only fire on the real EEO field (FR-ATTR-6).
_SENSITIVE_WORD_MARKERS: tuple[str, ...] = (
    "race",
    "sex",
    "age",
    "dob",
    "eeo",
)

#: Pre-compiled word-boundary patterns for the ambiguous short markers.
_SENSITIVE_WORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in _SENSITIVE_WORD_MARKERS) + r")\b"
)


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
            "sensitive fields fill only from explicit stored answers (FR-ATTR-6)."
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
