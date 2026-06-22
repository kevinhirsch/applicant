"""Field-value normalization for conflict comparison (FR-ONBOARD-3, FR-FB-3).

The reconciliation / confirmation-gate comparison must ignore format-only
differences so the same value in two formats is never falsely flagged as a
change — most importantly a reformatted phone number.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.field_normalization import (
    is_phone_field,
    normalize_phone,
    normalize_value,
    values_match,
)


@pytest.mark.unit
class TestPhoneNormalization:
    def test_reformatted_phone_is_equal(self):
        # The reported false-conflict: same number, two formats.
        assert values_match("phone", "3146695386", "(314) 669-5386")
        assert values_match("phone", "3146695386", "314) 669-5386")

    def test_spaces_dashes_dots_parens_ignored(self):
        assert values_match("phone", "314.669.5386", "314 669 5386")
        assert values_match("phone", "+1 314-669-5386", "(314) 669 5386")

    def test_leading_country_code_ignored(self):
        assert values_match("phone", "+1 (314) 669-5386", "3146695386")
        assert values_match("phone", "1-314-669-5386", "314-669-5386")
        assert normalize_phone("+1 (314) 669-5386") == "3146695386"

    def test_genuinely_different_numbers_still_differ(self):
        assert not values_match("phone", "3146695386", "3126695386")
        assert not values_match("phone", "3146695386", "3146695387")

    def test_phone_field_detection(self):
        assert is_phone_field("phone")
        assert is_phone_field("mobile_phone")
        assert is_phone_field("work_telephone")
        assert not is_phone_field("email")
        assert not is_phone_field("full_name")


@pytest.mark.unit
class TestNonPhoneNormalization:
    def test_case_and_whitespace_insensitive(self):
        assert values_match("email", "Jane@Example.com", "jane@example.com")
        assert values_match("full_name", "  Jane   Candidate ", "jane candidate")

    def test_genuinely_different_values_still_differ(self):
        assert not values_match("full_name", "Jane Candidate", "Janet Different")
        assert not values_match("email", "jane@example.com", "jane@other.com")

    def test_substring_is_not_collapsed(self):
        # Conservative: "Acme" and "Acme Corp" are NOT the same value.
        assert not values_match("company", "Acme", "Acme Corp")

    def test_normalize_value_handles_none(self):
        assert normalize_value("full_name", None) == ""
        assert values_match("full_name", "", None)
