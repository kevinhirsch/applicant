"""Unit tests for applicant.core.rules.eligibility (work-auth filter)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from applicant.core.rules.eligibility import (
    EligibilityVerdict,
    _needs_sponsorship,
    _posting_mentions_sponsorship,
    assess_work_auth_eligibility,
)


@pytest.fixture(autouse=True)
def _no_cache():
    yield


# ---------------------------------------------------------------------------
# EligibilityVerdict
# ---------------------------------------------------------------------------


class TestEligibilityVerdictConstruction:
    """Verify EligibilityVerdict dataclass construction and defaults."""

    @pytest.mark.unit
    def test_minimal_construction(self):
        v = EligibilityVerdict(eligible=True)
        assert v.eligible is True
        assert v.reason == ""

    @pytest.mark.unit
    def test_eligible_false_with_reason(self):
        v = EligibilityVerdict(eligible=False, reason="some reason")
        assert v.eligible is False
        assert v.reason == "some reason"


class TestEligibilityVerdictFrozen:
    """EligibilityVerdict is frozen (attribute writes raise FrozenInstanceError)."""

    @pytest.mark.unit
    def test_set_eligible_raises(self):
        v = EligibilityVerdict(eligible=True)
        with pytest.raises(FrozenInstanceError):
            v.eligible = False

    @pytest.mark.unit
    def test_set_reason_raises(self):
        v = EligibilityVerdict(eligible=True)
        with pytest.raises(FrozenInstanceError):
            v.reason = "changed"


class TestEligibilityVerdictHashable:
    """EligibilityVerdict is hashable (frozen + all immutable fields)."""

    @pytest.mark.unit
    def test_hash_returns_int(self):
        v = EligibilityVerdict(eligible=False, reason="x")
        assert isinstance(hash(v), int)

    @pytest.mark.unit
    def test_usable_in_set(self):
        a = EligibilityVerdict(eligible=True)
        b = EligibilityVerdict(eligible=True)
        s = {a, b}
        assert len(s) == 1


class TestEligibilityVerdictEquality:
    """Equality compares by field values (frozen dataclass default)."""

    @pytest.mark.unit
    def test_equal_when_same_values(self):
        assert EligibilityVerdict(eligible=True) == EligibilityVerdict(eligible=True)

    @pytest.mark.unit
    def test_inequal_when_different(self):
        assert EligibilityVerdict(eligible=True) != EligibilityVerdict(eligible=False)


# ---------------------------------------------------------------------------
# _needs_sponsorship
# ---------------------------------------------------------------------------


class TestNeedsSponsorship:
    """Test _needs_sponsorship(work_auth: Mapping) helper."""

    @pytest.mark.unit
    def test_true_when_needs_sponsorship_is_true(self):
        assert _needs_sponsorship({"needs_sponsorship": True}) is True

    @pytest.mark.unit
    def test_true_when_can_be_sponsored_false_and_needs_sponsorship_truthy(self):
        assert _needs_sponsorship({"needs_sponsorship": True, "can_be_sponsored": False}) is True

    @pytest.mark.unit
    def test_false_when_needs_sponsorship_is_false(self):
        assert _needs_sponsorship({"needs_sponsorship": False}) is False

    @pytest.mark.unit
    def test_false_when_needs_sponsorship_is_false_and_can_be_sponsored_false(self):
        # _needs_sponsorship returns True only when can_be_sponsored is False
        # AND needs_sponsorship is truthy; needs_sponsorship=False is falsy, so False.
        assert (
            _needs_sponsorship({"needs_sponsorship": False, "can_be_sponsored": False})
            is False
        )

    @pytest.mark.unit
    def test_false_for_empty_mapping(self):
        assert _needs_sponsorship({}) is False

    @pytest.mark.unit
    def test_false_when_needs_sponsorship_missing(self):
        assert _needs_sponsorship({"can_be_sponsored": True}) is False

    @pytest.mark.unit
    def test_false_when_needs_sponsorship_none(self):
        assert _needs_sponsorship({"needs_sponsorship": None}) is False


# ---------------------------------------------------------------------------
# _posting_mentions_sponsorship
# ---------------------------------------------------------------------------


class TestPostingMentionsSponsorship:
    """Test _posting_mentions_sponsorship(posting_text) helper."""

    @pytest.mark.unit
    def test_true_for_visa_sponsorship(self):
        assert _posting_mentions_sponsorship("We offer visa sponsorship") is True

    @pytest.mark.unit
    def test_true_for_must_be_authorized_to_work(self):
        assert _posting_mentions_sponsorship("must be authorized to work in US") is True

    @pytest.mark.unit
    def test_true_for_h1b(self):
        assert _posting_mentions_sponsorship("H-1B candidates welcome") is True

    @pytest.mark.unit
    def test_true_for_us_citizen(self):
        assert _posting_mentions_sponsorship("Must be a US citizen") is True

    @pytest.mark.unit
    def test_true_for_security_clearance(self):
        assert _posting_mentions_sponsorship("Active security clearance required") is True

    @pytest.mark.unit
    def test_false_for_empty_string(self):
        assert _posting_mentions_sponsorship("") is False

    @pytest.mark.unit
    def test_false_for_generic_text(self):
        assert _posting_mentions_sponsorship("Looking for a Java developer") is False

    @pytest.mark.unit
    def test_case_insensitive(self):
        assert _posting_mentions_sponsorship("VISA SPONSORSHIP") is True


# ---------------------------------------------------------------------------
# assess_work_auth_eligibility
# ---------------------------------------------------------------------------


class TestAssessWorkAuthEligibility:
    """Test assess_work_auth_eligibility(posting_text, work_auth)."""

    @pytest.mark.unit
    def test_eligible_when_posting_empty(self):
        """Empty posting text => no mention of sponsorship => eligible."""
        v = assess_work_auth_eligibility("", {"needs_sponsorship": True})
        assert v.eligible is True

    @pytest.mark.unit
    def test_eligible_when_posting_has_no_sponsorship_cues(self):
        """Posting does not mention sponsorship => eligible regardless of work auth."""
        v = assess_work_auth_eligibility(
            "Looking for a Python developer", {"needs_sponsorship": True}
        )
        assert v.eligible is True

    @pytest.mark.unit
    def test_eligible_when_posting_mentions_sponsorship_but_user_does_not_need(self):
        """Posting asks for sponsorship but user doesn't need it => eligible."""
        v = assess_work_auth_eligibility(
            "Visa sponsorship available", {"needs_sponsorship": False}
        )
        assert v.eligible is True

    @pytest.mark.unit
    def test_ineligible_when_both_conditions_true(self):
        """Posting mentions sponsorship AND user needs sponsorship => ineligible."""
        v = assess_work_auth_eligibility(
            "Must be authorized to work in the US", {"needs_sponsorship": True}
        )
        assert v.eligible is False

    @pytest.mark.unit
    def test_ineligible_when_cannot_be_sponsored_and_sponsorship_mentioned(self):
        """User cannot be sponsored AND posting mentions sponsorship => ineligible."""
        v = assess_work_auth_eligibility(
            "H-1B sponsorship available",
            {"needs_sponsorship": True, "can_be_sponsored": False},
        )
        assert v.eligible is False

    @pytest.mark.unit
    def test_ineligible_reason(self):
        """Ineligible verdict carries the expected reason string."""
        v = assess_work_auth_eligibility(
            "US citizen only", {"needs_sponsorship": True}
        )
        assert v.eligible is False
        assert "work-authorization requirements conflict" in v.reason

    @pytest.mark.unit
    def test_eligible_when_no_work_auth_info(self):
        """Empty work_auth => needs_sponsorship is False by default => eligible."""
        v = assess_work_auth_eligibility("Visa sponsorship offered", {})
        assert v.eligible is True

    @pytest.mark.unit
    def test_eligible_reason_empty_when_eligible(self):
        """Eligible verdict returns empty reason."""
        v = assess_work_auth_eligibility("Java developer needed", {})
        assert v.eligible is True
        assert v.reason == ""

    @pytest.mark.unit
    def test_security_clearance_triggers_ineligible(self):
        """Security clearance cue triggers ineligibility when user needs sponsorship."""
        v = assess_work_auth_eligibility(
            "Applicants must hold an active security clearance",
            {"needs_sponsorship": True},
        )
        assert v.eligible is False

    @pytest.mark.unit
    def test_eligible_when_security_clearance_but_user_does_not_need_sponsorship(self):
        """Security clearance posting but user does not need sponsorship => eligible."""
        v = assess_work_auth_eligibility(
            "Security clearance required", {"needs_sponsorship": False}
        )
        assert v.eligible is True

    @pytest.mark.unit
    def test_citizenship_required_triggers_ineligible(self):
        v = assess_work_auth_eligibility(
            "Citizenship required for this role", {"needs_sponsorship": True}
        )
        assert v.eligible is False

    @pytest.mark.unit
    def test_eligible_with_no_posting_and_no_auth(self):
        """Empty posting + empty work_auth => eligible."""
        v = assess_work_auth_eligibility("", {})
        assert v.eligible is True

    @pytest.mark.unit
    def test_eligible_with_sponsorship_available_but_can_be_sponsored_true(self):
        """User can be sponsored even if needs_sponsorship=True => still needs_sponsorship=True so ineligible.
        Note: per _needs_sponsorship logic, needs_sponsorship=True alone returns True.
        """
        v = assess_work_auth_eligibility(
            "Sponsorship available",
            {"needs_sponsorship": True, "can_be_sponsored": True},
        )
        assert v.eligible is False

    @pytest.mark.unit
    def test_eligible_reason_is_empty_string(self):
        """Eligible always gets reason=""."""
        v = assess_work_auth_eligibility(
            "No sponsorship talk", {"needs_sponsorship": True}
        )
        assert v.reason == ""

    @pytest.mark.unit
    def test_return_type_is_eligibility_verdict(self):
        v = assess_work_auth_eligibility("test", {})
        assert isinstance(v, EligibilityVerdict)
