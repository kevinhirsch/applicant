"""Unit tests for FollowUpService — threshold logic and message drafting."""

from __future__ import annotations

import pytest

from applicant.application.services.followup_service import (
    DEFAULT_FOLLOWUP_DUE_DAYS,
    FollowUpService,
)


@pytest.fixture(autouse=True)
def _xdist_isolation() -> None:
    """Clear any module-level state so xdist parallel workers don't collide."""
    pass


class TestFollowUpServiceConstruction:
    """FollowUpService instantiation and property."""

    @pytest.mark.unit
    def test_default_construction(self) -> None:
        svc = FollowUpService()
        assert svc.due_after_days == DEFAULT_FOLLOWUP_DUE_DAYS

    @pytest.mark.unit
    def test_custom_due_after_days(self) -> None:
        svc = FollowUpService(due_after_days=5)
        assert svc.due_after_days == 5

    @pytest.mark.unit
    def test_zero_due_after_days(self) -> None:
        svc = FollowUpService(due_after_days=0)
        assert svc.due_after_days == 0


class TestFollowUpIsDue:
    """Static helper: followup_is_due."""

    @pytest.mark.unit
    def test_default_constant_value(self) -> None:
        assert DEFAULT_FOLLOWUP_DUE_DAYS == 10

    # --- instance-method style ---

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("days_since", "expected"),
        [
            pytest.param(0, False, id="same-day-not-due"),
            pytest.param(5, False, id="half-threshold-not-due"),
            pytest.param(9, False, id="one-below-threshold-not-due"),
            pytest.param(10, True, id="at-threshold-due"),
            pytest.param(11, True, id="one-above-threshold-due"),
            pytest.param(100, True, id="well-above-due"),
        ],
    )
    def test_followup_is_due_instance(self, days_since: int, expected: bool) -> None:
        svc = FollowUpService()
        assert svc.followup_is_due(days_since) == expected

    @pytest.mark.unit
    def test_followup_is_due_negative_days(self) -> None:
        svc = FollowUpService()
        assert svc.followup_is_due(-1) is False
        assert svc.followup_is_due(-100) is False

    # --- static-method style ---

    @pytest.mark.unit
    def test_called_on_class(self) -> None:
        assert FollowUpService.followup_is_due(10) is True
        assert FollowUpService.followup_is_due(9) is False

    # --- custom due_after_days override ---

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("days_since", "due_after", "expected"),
        [
            pytest.param(2, 3, False, id="below-custom"),
            pytest.param(3, 3, True, id="at-custom"),
            pytest.param(4, 3, True, id="above-custom"),
            pytest.param(0, 1, False, id="zero-below-custom"),
            pytest.param(0, 0, True, id="zero-at-zero"),
        ],
    )
    def test_followup_is_due_custom_threshold(
        self, days_since: int, due_after: int, expected: bool
    ) -> None:
        assert FollowUpService.followup_is_due(days_since, due_after_days=due_after) == expected


class TestDraftFollowup:
    """Static helper: draft_followup."""

    _EXPECTED_TEMPLATE = (
        "Hi,\n\n"
        "I wanted to follow up on my application for {role} at {company}. "
        "I remain very interested in the opportunity and would welcome the "
        "chance to discuss how I can contribute. Please let me know if there "
        "is anything further I can provide.\n\n"
        "Thank you for your time and consideration."
    )

    @pytest.mark.unit
    def test_default_draft(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="the role", company="your team")
        assert FollowUpService.draft_followup() == expected

    @pytest.mark.unit
    def test_custom_role_company(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="Software Engineer", company="Acme Inc")
        assert FollowUpService.draft_followup(role="Software Engineer", company="Acme Inc") == expected

    @pytest.mark.unit
    def test_empty_role_uses_default(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="the role", company="My Corp")
        assert FollowUpService.draft_followup(role="", company="My Corp") == expected

    @pytest.mark.unit
    def test_empty_company_uses_default(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="Engineer", company="your team")
        assert FollowUpService.draft_followup(role="Engineer", company="") == expected

    @pytest.mark.unit
    def test_whitespace_role_stripped(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="Dev", company="Startup")
        assert FollowUpService.draft_followup(role="  Dev  ", company="  Startup  ") == expected

    @pytest.mark.unit
    def test_whitespace_only_falls_back(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="the role", company="your team")
        assert FollowUpService.draft_followup(role="   ", company="   ") == expected

    @pytest.mark.unit
    def test_none_role_falls_back(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="the role", company="Team")
        assert FollowUpService.draft_followup(role=None, company="Team") == expected  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_none_company_falls_back(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="Role", company="your team")
        assert FollowUpService.draft_followup(role="Role", company=None) == expected  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_both_none_falls_back(self) -> None:
        expected = self._EXPECTED_TEMPLATE.format(role="the role", company="your team")
        assert FollowUpService.draft_followup(role=None, company=None) == expected  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_instance_call_draft(self) -> None:
        svc = FollowUpService()
        expected = self._EXPECTED_TEMPLATE.format(role="Data Analyst", company="DataCo")
        assert svc.draft_followup(role="Data Analyst", company="DataCo") == expected
