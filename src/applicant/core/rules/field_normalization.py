"""Field-value normalization for equality comparison (FR-ONBOARD-3, FR-FB-3).

When a parsed-resume value is reconciled against an interview answer (or a new
attribute value is compared with a stored one) the comparison must ignore
purely *formatting* differences, otherwise the same value in two formats is
falsely surfaced as a conflict. For example a phone number written as
``3146695386`` and ``(314) 669-5386`` is the SAME number and must NOT be
flagged.

Pure rule (no IO) so both the onboarding reconciliation and the attribute-cloud
upsert gate share one definition of "same value":

* **phone** fields compare by digits only — spaces, dashes, parentheses, dots
  and a leading ``+1`` / single-digit country code are ignored;
* **every other** field compares case-insensitively with surrounding whitespace
  trimmed and internal runs of whitespace collapsed.

The normalization is intentionally conservative: it only collapses formatting,
never genuinely different values (``314...`` and ``312...`` stay different;
``"Acme"`` and ``"Acme Corp"`` stay different).
"""

from __future__ import annotations

import re

#: Field names (or name suffixes) whose values are phone numbers. Matched on the
#: lowercased name so ``phone``, ``mobile_phone``, ``work_phone`` etc. all count.
_PHONE_FIELD_MARKERS: tuple[str, ...] = ("phone", "mobile", "telephone", "fax")

_NON_DIGIT_RE = re.compile(r"\D")
_WS_RE = re.compile(r"\s+")


def is_phone_field(name: str) -> bool:
    """True if ``name`` denotes a phone-number field (digits-only comparison)."""
    low = (name or "").lower()
    return any(marker in low for marker in _PHONE_FIELD_MARKERS)


def normalize_phone(value: str) -> str:
    """Reduce a phone number to its comparable digits.

    Strips every non-digit (spaces, dashes, parentheses, dots, ``+``) and drops a
    leading single-digit country code (the US ``+1`` / bare ``1`` prefix on an
    11-digit number) so ``+1 (314) 669-5386``, ``314) 669-5386`` and
    ``3146695386`` all reduce to ``3146695386``.
    """
    digits = _NON_DIGIT_RE.sub("", value or "")
    # Drop a leading "1" country code on an 11-digit North-American number so a
    # "+1 314..." stated value matches a bare "314..." resume value.
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_value(name: str, value: str) -> str:
    """Normalize a field value for equality comparison (format-insensitive).

    Phone fields reduce to digits; all other fields lower-case + collapse
    whitespace. Returns the canonical comparable form, NOT a display value.
    """
    if value is None:
        return ""
    if is_phone_field(name):
        return normalize_phone(str(value))
    return _WS_RE.sub(" ", str(value).strip()).lower()


def values_match(name: str, a: str, b: str) -> bool:
    """True if two values for ``name`` are equal ignoring format-only differences.

    Used to decide whether a parsed/new value actually differs from a stored one,
    so a phone reformat or a case/whitespace change is never flagged as a change
    (FR-ONBOARD-3 reconciliation, FR-FB-3 confirmation gate).
    """
    return normalize_value(name, a) == normalize_value(name, b)
