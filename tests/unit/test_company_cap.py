"""Tests for applicant.core.rules.company_cap — per-company volume cap."""

from __future__ import annotations

import pytest

from applicant.core.rules.company_cap import (
    DEFAULT_PER_COMPANY_CAP,
    admit_company_application,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel-execution safety (xdist)."""
    return


class TestDefaults:
    """Default cap (3) and constant."""

    def test_default_cap_constant(self) -> None:
        assert DEFAULT_PER_COMPANY_CAP == 3

    def test_default_cap_is_used(self) -> None:
        """Omitting cap applies the default (3)."""
        assert admit_company_application(company="acme", sent_in_window=2) is True
        assert admit_company_application(company="acme", sent_in_window=3) is False


@pytest.mark.unit
class TestAdmitCompanyApplication:
    """Core admission logic."""

    def test_below_cap_admits(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=0, cap=3) is True
        assert admit_company_application(company="acme", sent_in_window=1, cap=3) is True
        assert admit_company_application(company="acme", sent_in_window=2, cap=3) is True

    def test_at_cap_rejects(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=3, cap=3) is False

    def test_over_cap_rejects(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=4, cap=3) is False
        assert admit_company_application(company="acme", sent_in_window=99, cap=3) is False

    def test_cap_zero_always_rejects(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=0, cap=0) is False
        assert admit_company_application(company="acme", sent_in_window=1, cap=0) is False

    def test_cap_negative_always_rejects(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=0, cap=-1) is False
        assert admit_company_application(company="acme", sent_in_window=0, cap=-5) is False

    def test_fresh_window_resets(self) -> None:
        """A fresh window (sent_in_window=0) admits when cap > 0."""
        assert admit_company_application(company="acme", sent_in_window=0, cap=1) is True

    def test_different_companies_count_independently(self) -> None:
        """The function is stateless — each call is independent."""
        assert admit_company_application(company="acme", sent_in_window=0, cap=1) is True
        assert admit_company_application(company="globex", sent_in_window=0, cap=1) is True

    def test_varying_cap_values(self) -> None:
        assert admit_company_application(company="acme", sent_in_window=5, cap=10) is True
        assert admit_company_application(company="acme", sent_in_window=10, cap=10) is False
        assert admit_company_application(company="acme", sent_in_window=11, cap=10) is False

    def test_company_name_ignored_in_decision(self) -> None:
        """Company name is informational; logic depends only on counts."""
        assert admit_company_application(company="a", sent_in_window=0, cap=2) is True
        assert admit_company_application(company="very-long-name", sent_in_window=0, cap=2) is True
        assert admit_company_application(company="", sent_in_window=0, cap=2) is True
