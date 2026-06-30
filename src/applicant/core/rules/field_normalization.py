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
_NON_DIGIT_NO_PLUS_RE = re.compile(r"[^\d+]")
_WS_RE = re.compile(r"\s+")

#: Country dialling codes whose international ``+CC`` form maps to a national
#: number reached by replacing the code with a trunk prefix (usually ``0``).
#: Ordered longest-first so e.g. ``+44`` is tried before ``+4``. The US/Canada
#: ``+1`` is handled separately (its national form is the bare number, no trunk
#: prefix), so it is not in this table. This makes a number written in its stated
#: international form (``+44 7700 900123``) reconcile with the same number written
#: in national form (``07700 900123``) instead of being mangled into a mismatch.
_COUNTRY_TRUNK: tuple[tuple[str, str], ...] = (
    ("44", "0"),   # United Kingdom
    ("61", "0"),   # Australia
    ("64", "0"),   # New Zealand
    ("33", "0"),   # France
    ("49", "0"),   # Germany
    ("91", "0"),   # India
    ("81", "0"),   # Japan
    ("353", "0"),  # Ireland
)


def is_phone_field(name: str) -> bool:
    """True if ``name`` denotes a phone-number field (digits-only comparison)."""
    low = (name or "").lower()
    return any(marker in low for marker in _PHONE_FIELD_MARKERS)


def normalize_phone(value: str) -> str:
    """Reduce a phone number to its comparable national digits (country-aware).

    Formatting (spaces, dashes, parentheses, dots) is stripped. A leading country
    code is reconciled to the number's NATIONAL form so the same number written
    in its stated international ``+CC`` form and in its local national form
    compare equal rather than being mangled into a mismatch:

    * US/Canada ``+1`` / a bare leading ``1`` on an 11-digit number drops to the
      bare ten-digit national number — ``+1 (314) 669-5386`` and ``3146695386``
      both reduce to ``3146695386``;
    * other known country codes (``+44`` UK, ``+61`` AU, …) are replaced with the
      national trunk prefix — ``+44 7700 900123`` and ``07700 900123`` both reduce
      to ``07700900123``.

    An unrecognized ``+CC`` number is left as its digits so genuinely different
    numbers stay different.
    """
    raw = (value or "").strip()
    # Preserve a leading "+" so an explicit international prefix can be detected
    # before we collapse to digits.
    had_plus = raw.startswith("+")
    digits = _NON_DIGIT_RE.sub("", raw)

    if had_plus:
        # US/Canada: +1 NXX... → bare national (drop the single-digit code).
        if digits.startswith("1") and len(digits) == 11:
            return digits[1:]
        for code, trunk in _COUNTRY_TRUNK:
            if digits.startswith(code):
                return trunk + digits[len(code):]
        return digits

    # No explicit "+": only the long-standing US 11-digit "1NXX..." shorthand is
    # treated as a country code (unchanged behaviour); everything else is verbatim.
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
