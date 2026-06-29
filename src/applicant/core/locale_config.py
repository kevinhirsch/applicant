"""Locale-aware configuration for phone parsing, EEO labels, salary cues,
ATS field labels, and other locale-sensitive application logic (issue #194).

By default all patterns target US/English. An operator can supply a custom
LocaleConfig to adapt phone formats, EEO field markers, salary cues, and
ATS label patterns for a different locale without modifying the core rules.

Usage:

    from applicant.core.locale_config import LocaleConfig, DEFAULT_LOCALE

    # Use the default (US/English)
    is_sensitive = DEFAULT_LOCALE.is_sensitive_field("Gender")

    # Supply a custom locale
    de_locale = LocaleConfig(
        phone_field_markers=("telefon", "mobil", "handy", "fax"),
        sensitive_eeo_markers=("geschlecht", "behinderung", "ethnische"),
        ...
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LocaleConfig:
    """Locale-sensitive configuration for application parsing and labeling.

    All fields have US/English defaults. Replace individual fields to adapt
    the engine to a non-US locale.
    """

    #: Field name markers that identify phone number fields (case-insensitive
    #: substring match on the lowercased field name).
    phone_field_markers: tuple[str, ...] = ("phone", "mobile", "telephone", "fax")

    #: Country code prefix to strip from phone numbers during normalization.
    #: The leading digit(s) to strip when the digit count reaches this threshold.
    #: US/NA numbers use 11-digit format with leading "1".
    phone_country_code_length: int = 1
    phone_country_code_digit_count: int = 11

    #: EEO/demographic field substring markers (unambiguous multi-character
    #: substrings that mark a field as sensitive).
    sensitive_eeo_markers: tuple[str, ...] = (
        "ethnicity", "ethnic", "gender", "disability", "disabilities",
        "veteran", "protected veteran", "sexual orientation", "lgbt",
        "pregnan", "religion", "national origin", "marital",
        "date of birth", "self-identification", "self identify",
        "self-identify", "diversity", "hispanic", "latino", "latinx",
        "military",
    )

    #: Short ambiguous EEO markers matched on word boundaries.
    sensitive_word_markers: tuple[str, ...] = ("race", "sex", "age", "dob", "eeo")

    #: Default decline-to-self-identify label for EEO fields.
    decline_to_self_identify: str = "decline to self-identify"

    #: Salary-related cue phrases for factual screening detection.
    salary_cues: tuple[str, ...] = (
        "salary", "compensation", "desired pay", "expected pay",
        "pay expectation", "salary expectation",
    )

    #: Work authorization cue phrases.
    work_auth_cues: tuple[str, ...] = (
        "work authorization", "authorized to work", "require sponsorship",
        "need sponsorship", "visa",
    )

    #: Date format patterns for parsing work history (month names).
    month_names: tuple[str, ...] = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )

    #: Present/current keywords for open-ended date ranges.
    present_keywords: tuple[str, ...] = ("Present", "Current")

    def is_phone_field(self, name: str) -> bool:
        """True if *name* denotes a phone-number field."""
        low = (name or "").lower()
        return any(marker in low for marker in self.phone_field_markers)

    def normalize_phone(self, value: str) -> str:
        """Reduce a phone number to comparable digits, locale-aware."""
        import re as _re
        digits = _re.sub(r"\D", "", value or "")
        if len(digits) == self.phone_country_code_digit_count and digits.startswith(str(self.phone_country_code_length)):
            digits = digits[self.phone_country_code_length:]
        return digits

    def is_sensitive_field(self, field_label: str) -> bool:
        """True if *field_label* looks like an EEO/demographic/self-id field."""
        if not field_label:
            return False
        low = field_label.lower()
        if any(marker in low for marker in self.sensitive_eeo_markers):
            return True
        word_re = re.compile(
            r"(?:" + "|".join(re.escape(m) for m in self.sensitive_word_markers) + r")"
        )
        return bool(word_re.search(low))


#: The default US/English locale configuration.
DEFAULT_LOCALE = LocaleConfig()
