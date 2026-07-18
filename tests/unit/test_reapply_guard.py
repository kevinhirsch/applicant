"""Tests for applicant.core.rules.reapply_guard."""

from applicant.core.rules.reapply_guard import (
    DEFAULT_COOLDOWN_DAYS,
    is_duplicate_application,
)


class TestIsDuplicateApplication:
    """Tests for is_duplicate_application."""

    def _candidate(self, company="Acme Corp", role="Engineer"):
        return {"company": company, "role": role}

    def _history_entry(self, company="Acme Corp", role="Engineer", days_ago=1):
        return {"company": company, "role": role, "days_ago": days_ago}

    # -- basic correctness --

    def test_no_history(self):
        assert is_duplicate_application(self._candidate(), []) is False

    def test_matching_within_cooldown(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=1)]) is True

    def test_matching_at_exact_cooldown_boundary(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=DEFAULT_COOLDOWN_DAYS)]) is True

    def test_matching_beyond_cooldown(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=DEFAULT_COOLDOWN_DAYS + 1)]) is False

    def test_different_company(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(company="Other Co")]) is False

    def test_different_role(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(role="Designer")]) is False

    def test_case_insensitive_match(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(company="acme corp", role="engineer")]) is True

    def test_whitespace_stripped(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(company="  Acme Corp  ", role="  Engineer  ")]) is True

    def test_title_alias_accepted(self):
        assert is_duplicate_application(self._candidate(), [{"company": "Acme Corp", "title": "Engineer", "days_ago": 1}]) is True

    def test_none_days_ago_treats_as_duplicate(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=None)]) is True

    # -- negative days_ago (data corruption / future timestamp) --

    def test_negative_int_days_ago(self):
        """Negative int days_ago should be skipped, not treated as duplicate."""
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=-1)]) is False

    def test_negative_float_days_ago(self):
        """Negative float days_ago should be skipped."""
        assert is_duplicate_application(self._candidate(), [{"company": "Acme Corp", "role": "Engineer", "days_ago": -3.5}]) is False

    def test_negative_string_days_ago(self):
        """Negative string days_ago should be skipped."""
        assert is_duplicate_application(self._candidate(), [{"company": "Acme Corp", "role": "Engineer", "days_ago": "-7"}]) is False

    def test_negative_days_ago_multiple_entries(self):
        """Multiple negative entries should all be skipped; a matching entry wins."""
        history = [
            self._history_entry(days_ago=-1),
            self._history_entry(days_ago=-2),
            self._history_entry(days_ago=1),
        ]
        assert is_duplicate_application(self._candidate(), history) is True

    def test_all_negative_days_ago(self):
        """All entries with negative days_ago => no duplicate."""
        history = [
            self._history_entry(days_ago=-1),
            self._history_entry(days_ago=-2),
            self._history_entry(days_ago=-3),
        ]
        assert is_duplicate_application(self._candidate(), history) is False

    # -- edge cases for type conversion --

    def test_string_days_ago(self):
        assert is_duplicate_application(self._candidate(), [{"company": "Acme Corp", "role": "Engineer", "days_ago": "5"}]) is True

    def test_zero_days_ago(self):
        assert is_duplicate_application(self._candidate(), [self._history_entry(days_ago=0)]) is True

    def test_empty_company_and_role(self):
        assert is_duplicate_application({"company": "", "role": ""}, [self._history_entry()]) is False

    def test_missing_company_and_role(self):
        assert is_duplicate_application({}, [self._history_entry()]) is False

    def test_invalid_days_ago_string(self):
        """Non-numeric string days_ago should be treated as duplicate."""
        assert is_duplicate_application(self._candidate(), [{"company": "Acme Corp", "role": "Engineer", "days_ago": "abc"}]) is True

    def test_custom_cooldown(self):
        assert is_duplicate_application(
            self._candidate(),
            [self._history_entry(days_ago=10)],
            cooldown_days=5,
        ) is False
        assert is_duplicate_application(
            self._candidate(),
            [self._history_entry(days_ago=3)],
            cooldown_days=5,
        ) is True


class TestDefaultCooldownDays:
    """Tests for DEFAULT_COOLDOWN_DAYS constant."""

    def test_default_cooldown_is_positive_int(self):
        assert isinstance(DEFAULT_COOLDOWN_DAYS, int)
        assert DEFAULT_COOLDOWN_DAYS > 0

    def test_default_cooldown_value(self):
        assert DEFAULT_COOLDOWN_DAYS == 30
