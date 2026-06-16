"""Sensitive-field (EEO/demographic) policy (FR-ATTR-6).

Demographic / EEO / self-identification fields are filled **only** from the user's
explicit stored answer, **never** AI-guessed. When the user has not provided an
explicit answer the policy default is "decline to self-identify".

This rule lives in the pure core so the pre-fill adapter (Phase 2) physically
cannot AI-guess these fields: it must route every fill decision through
``decide_sensitive_fill``.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.errors import SensitiveFieldViolation

#: The canonical default when the user has no explicit stored answer (FR-ATTR-6).
DECLINE_TO_SELF_IDENTIFY = "decline to self-identify"

#: Substrings that mark a form field as sensitive/EEO. Conservative + broad:
#: a false positive only forces the safe default, which is acceptable.
_SENSITIVE_MARKERS: tuple[str, ...] = (
    "race",
    "ethnicity",
    "ethnic",
    "gender",
    "sex",
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
    "age",
    "date of birth",
    "dob",
    "eeo",
    "self-identification",
    "self identify",
    "self-identify",
    "diversity",
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
    return any(marker in low for marker in _SENSITIVE_MARKERS)


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
            from_explicit_answer=explicit_answer is not None,
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
