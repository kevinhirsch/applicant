"""Tests for LocaleConfig.normalize_phone (FR-LOCALE-1).

Hermetic: no network, no filesystem, no I/O.
"""

from __future__ import annotations

import pytest

from applicant.core.locale_config import DEFAULT_LOCALE


@pytest.mark.unit
class TestNormalizePhone:
    """Cover the actual normalize_phone logic — strip non-digits, then
    conditionally remove the country-code prefix if the digit count
    and starting digit match the default US locale."""

    def test_none_returns_empty_string(self):
        assert DEFAULT_LOCALE.normalize_phone(None) == ""

    def test_empty_string_returns_empty(self):
        assert DEFAULT_LOCALE.normalize_phone("") == ""

    def test_us_number_with_formatting_strips_country_code(self):
        # "+1 (555) 123-4567" → digits="15551234567" (11 digits, starts "1")
        # → strips leading "1" → "5551234567"
        result = DEFAULT_LOCALE.normalize_phone("+1 (555) 123-4567")
        assert result == "5551234567"

    def test_ten_digit_number_preserved_as_is(self):
        # "555-123-4567" → "5551234567" (10 digits, not 11 → as-is)
        result = DEFAULT_LOCALE.normalize_phone("555-123-4567")
        assert result == "5551234567"

    def test_eleven_digits_starting_with_one(self):
        # "12345678901" → 11 digits starting with "1" → strip first → "2345678901"
        result = DEFAULT_LOCALE.normalize_phone("12345678901")
        assert result == "2345678901"

    def test_ten_digits_eleven_rule_does_not_apply(self):
        # "1234567890" → 10 digits → as-is
        result = DEFAULT_LOCALE.normalize_phone("1234567890")
        assert result == "1234567890"

    def test_non_us_number_prefix_preserved(self):
        # "+44 20 7946 0958" → "442079460958" (12 digits, not 11 → as-is)
        result = DEFAULT_LOCALE.normalize_phone("+44 20 7946 0958")
        assert result == "442079460958"

    def test_only_non_digits_returns_empty(self):
        # "abc" → no digits → ""
        result = DEFAULT_LOCALE.normalize_phone("abc")
        assert result == ""

    def test_whitespace_only_returns_empty(self):
        # "   " → no digits → ""
        result = DEFAULT_LOCALE.normalize_phone("   ")
        assert result == ""
