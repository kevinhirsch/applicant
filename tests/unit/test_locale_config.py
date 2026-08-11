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


class TestIsPhoneField:
    """Cover is_phone_field: case-insensitive substring match against
    phone_field_markers."""

    def test_none_returns_false(self):
        assert DEFAULT_LOCALE.is_phone_field(None) is False

    def test_empty_string_returns_false(self):
        assert DEFAULT_LOCALE.is_phone_field("") is False

    def test_exact_marker_matches(self):
        assert DEFAULT_LOCALE.is_phone_field("phone") is True
        assert DEFAULT_LOCALE.is_phone_field("mobile") is True
        assert DEFAULT_LOCALE.is_phone_field("telephone") is True
        assert DEFAULT_LOCALE.is_phone_field("fax") is True

    def test_case_insensitive(self):
        assert DEFAULT_LOCALE.is_phone_field("PHONE") is True
        assert DEFAULT_LOCALE.is_phone_field("Phone") is True
        assert DEFAULT_LOCALE.is_phone_field("MoBiLe") is True

    def test_substring_in_composite_name(self):
        assert DEFAULT_LOCALE.is_phone_field("phone_number") is True
        assert DEFAULT_LOCALE.is_phone_field("mobile_phone") is True
        assert DEFAULT_LOCALE.is_phone_field("home_telephone") is True

    def test_non_phone_field_returns_false(self):
        assert DEFAULT_LOCALE.is_phone_field("email") is False
        assert DEFAULT_LOCALE.is_phone_field("name") is False
        assert DEFAULT_LOCALE.is_phone_field("address") is False


class TestIsSensitiveField:
    """Cover is_sensitive_field: substring match on sensitive_eeo_markers
    plus word-boundary match on sensitive_word_markers."""

    def test_none_returns_false(self):
        assert DEFAULT_LOCALE.is_sensitive_field(None) is False

    def test_empty_string_returns_false(self):
        assert DEFAULT_LOCALE.is_sensitive_field("") is False

    def test_substring_eo_markers_match(self):
        assert DEFAULT_LOCALE.is_sensitive_field("ethnicity") is True
        assert DEFAULT_LOCALE.is_sensitive_field("gender") is True
        assert DEFAULT_LOCALE.is_sensitive_field("disability status") is True
        assert DEFAULT_LOCALE.is_sensitive_field("veteran status") is True
        assert DEFAULT_LOCALE.is_sensitive_field("sexual orientation") is True
        assert DEFAULT_LOCALE.is_sensitive_field("religion") is True
        assert DEFAULT_LOCALE.is_sensitive_field("marital status") is True
        assert DEFAULT_LOCALE.is_sensitive_field("date of birth") is True
        assert DEFAULT_LOCALE.is_sensitive_field("diversity") is True
        assert DEFAULT_LOCALE.is_sensitive_field("hispanic") is True
        assert DEFAULT_LOCALE.is_sensitive_field("latino") is True
        assert DEFAULT_LOCALE.is_sensitive_field("military service") is True

    def test_word_boundary_markers_match(self):
        assert DEFAULT_LOCALE.is_sensitive_field("race") is True
        assert DEFAULT_LOCALE.is_sensitive_field("sex") is True
        assert DEFAULT_LOCALE.is_sensitive_field("age") is True
        assert DEFAULT_LOCALE.is_sensitive_field("dob") is True
        assert DEFAULT_LOCALE.is_sensitive_field("eeo-1") is True

    def test_case_insensitive(self):
        assert DEFAULT_LOCALE.is_sensitive_field("GENDER") is True
        assert DEFAULT_LOCALE.is_sensitive_field("Race") is True
        assert DEFAULT_LOCALE.is_sensitive_field("AGE") is True

    def test_non_sensitive_field_returns_false(self):
        assert DEFAULT_LOCALE.is_sensitive_field("name") is False
        assert DEFAULT_LOCALE.is_sensitive_field("email address") is False
        assert DEFAULT_LOCALE.is_sensitive_field("job title") is False
        assert DEFAULT_LOCALE.is_sensitive_field("experience") is False

    def test_word_boundary_prevents_false_positives(self):
        # "race" inside a word shouldn't match via substring, but it does
        # because "race" is in sensitive_word_markers with word boundaries.
        # However, "ra" or "ce" alone shouldn't match.
        assert DEFAULT_LOCALE.is_sensitive_field("preference") is False
        assert DEFAULT_LOCALE.is_sensitive_field("sexiness") is False
