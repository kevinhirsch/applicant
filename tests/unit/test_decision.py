import pytest
from dataclasses import FrozenInstanceError

from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.ids import DecisionId, ApplicationId


class TestDecisionType:
    """Tests for the DecisionType enum."""

    def test_approve_value(self):
        assert DecisionType.APPROVE.value == "approve"

    def test_decline_value(self):
        assert DecisionType.DECLINE.value == "decline"

    def test_approve_is_member(self):
        assert DecisionType.APPROVE in DecisionType

    def test_decline_is_member(self):
        assert DecisionType.DECLINE in DecisionType


class TestDecision:
    """Tests for the Decision frozen dataclass."""

    # --- construction ---

    def test_create_minimal(self):
        d = Decision(DecisionId("dec-1"), ApplicationId("app-1"), DecisionType.APPROVE)
        assert d.id == "dec-1"
        assert d.application_id == "app-1"
        assert d.type == DecisionType.APPROVE
        assert d.feedback_text == ""
        assert d.criteria_delta == {}

    def test_create_decline_with_feedback(self):
        d = Decision(
            DecisionId("dec-2"),
            ApplicationId("app-2"),
            DecisionType.DECLINE,
            feedback_text="Score too low",
        )
        assert d.type == DecisionType.DECLINE
        assert d.feedback_text == "Score too low"

    def test_create_with_criteria_delta(self):
        d = Decision(
            DecisionId("dec-3"),
            ApplicationId("app-3"),
            DecisionType.APPROVE,
            criteria_delta={"skill_match": 0.9},
        )
        assert d.criteria_delta == {"skill_match": 0.9}

    # --- immutability ---

    def test_cannot_mutate_id(self):
        d = Decision(DecisionId("dec-4"), ApplicationId("app-4"), DecisionType.APPROVE)
        with pytest.raises(FrozenInstanceError):
            d.id = "other"  # type: ignore[misc]

    def test_cannot_mutate_type(self):
        d = Decision(DecisionId("dec-5"), ApplicationId("app-5"), DecisionType.DECLINE)
        with pytest.raises(FrozenInstanceError):
            d.type = DecisionType.APPROVE  # type: ignore[misc]

    # --- equality ---

    def test_equality(self):
        d1 = Decision(DecisionId("dec-6"), ApplicationId("app-6"), DecisionType.APPROVE)
        d2 = Decision(DecisionId("dec-6"), ApplicationId("app-6"), DecisionType.APPROVE)
        assert d1 == d2

    def test_inequality(self):
        d1 = Decision(DecisionId("dec-7"), ApplicationId("app-7"), DecisionType.APPROVE)
        d2 = Decision(DecisionId("dec-8"), ApplicationId("app-8"), DecisionType.APPROVE)
        assert d1 != d2

    def test_repr(self):
        d = Decision(DecisionId("dec-10"), ApplicationId("app-10"), DecisionType.APPROVE)
        r = repr(d)
        assert "Decision" in r
        assert "dec-10" in r
