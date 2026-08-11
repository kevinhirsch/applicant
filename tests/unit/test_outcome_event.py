import pytest

from applicant.core.entities.outcome_event import (
    OutcomeSource,
    OUTCOME_TYPES,
    is_recognized_outcome,
    OutcomeEvent,
)
from applicant.core.ids import ApplicationId, OutcomeEventId


class TestOutcomeSource:
    """Tests for the OutcomeSource enum."""

    def test_auto_value(self):
        assert OutcomeSource.AUTO.value == "auto"

    def test_manual_value(self):
        assert OutcomeSource.MANUAL.value == "manual"

    def test_auto_is_string_member(self):
        assert "auto" in OutcomeSource._value2member_map_

    def test_manual_is_string_member(self):
        assert "manual" in OutcomeSource._value2member_map_

    def test_auto_repr(self):
        assert repr(OutcomeSource.AUTO) == "<OutcomeSource.AUTO: 'auto'>"

    def test_manual_repr(self):
        assert repr(OutcomeSource.MANUAL) == "<OutcomeSource.MANUAL: 'manual'>"


class TestOutcomeTypes:
    """Tests for the OUTCOME_TYPES frozenset constant."""

    def test_is_frozenset(self):
        assert isinstance(OUTCOME_TYPES, frozenset)

    def test_contains_submitted(self):
        assert "submitted" in OUTCOME_TYPES

    def test_contains_converted(self):
        assert "converted" in OUTCOME_TYPES

    def test_contains_rejected(self):
        assert "rejected" in OUTCOME_TYPES

    def test_contains_interview_invited(self):
        assert "interview_invited" in OUTCOME_TYPES

    def test_contains_ghosted(self):
        assert "ghosted" in OUTCOME_TYPES

    def test_contains_offer(self):
        assert "offer" in OUTCOME_TYPES

    def test_does_not_contain_unknown_type(self):
        assert "withdrawn" not in OUTCOME_TYPES

    def test_does_not_contain_empty_string(self):
        assert "" not in OUTCOME_TYPES

    def test_exactly_six_types(self):
        assert len(OUTCOME_TYPES) == 6

    def test_immutable(self):
        with pytest.raises(AttributeError):
            OUTCOME_TYPES.add("new_type")

    def test_none(self):
        assert None not in OUTCOME_TYPES


class TestIsRecognizedOutcome:
    """Tests for the is_recognized_outcome function."""

    def test_submitted_is_recognized(self):
        assert is_recognized_outcome("submitted") is True

    def test_converted_is_recognized(self):
        assert is_recognized_outcome("converted") is True

    def test_rejected_is_recognized(self):
        assert is_recognized_outcome("rejected") is True

    def test_interview_invited_is_recognized(self):
        assert is_recognized_outcome("interview_invited") is True

    def test_ghosted_is_recognized(self):
        assert is_recognized_outcome("ghosted") is True

    def test_offer_is_recognized(self):
        assert is_recognized_outcome("offer") is True

    def test_unknown_type_not_recognized(self):
        assert is_recognized_outcome("withdrawn") is False

    def test_empty_string_not_recognized(self):
        assert is_recognized_outcome("") is False

    def test_none_returns_false(self):
        assert is_recognized_outcome(None) is False

    def test_case_sensitive(self):
        assert is_recognized_outcome("Submitted") is False


class TestOutcomeEvent:
    """Tests for the OutcomeEvent frozen dataclass."""

    def test_create_with_default_source(self):
        event = OutcomeEvent(
            id=OutcomeEventId("evt_1"),
            application_id=ApplicationId("app_1"),
            type="submitted",
        )
        assert event.id == "evt_1"
        assert event.application_id == "app_1"
        assert event.type == "submitted"
        assert event.source == OutcomeSource.AUTO

    def test_create_with_explicit_manual_source(self):
        event = OutcomeEvent(
            id=OutcomeEventId("evt_2"),
            application_id=ApplicationId("app_2"),
            type="rejected",
            source=OutcomeSource.MANUAL,
        )
        assert event.source == OutcomeSource.MANUAL

    def test_create_with_explicit_auto_source(self):
        event = OutcomeEvent(
            id=OutcomeEventId("evt_3"),
            application_id=ApplicationId("app_3"),
            type="offer",
            source=OutcomeSource.AUTO,
        )
        assert event.source == OutcomeSource.AUTO

    def test_frozen_dataclass(self):
        event = OutcomeEvent(
            id=OutcomeEventId("evt_4"),
            application_id=ApplicationId("app_4"),
            type="ghosted",
        )
        with pytest.raises(AttributeError):
            event.type = "rejected"

    def test_repr(self):
        event = OutcomeEvent(
            id=OutcomeEventId("evt_5"),
            application_id=ApplicationId("app_5"),
            type="interview_invited",
        )
        assert "OutcomeEvent" in repr(event)
        assert "evt_5" in repr(event)

    def test_equal_same_values(self):
        e1 = OutcomeEvent(
            id=OutcomeEventId("evt_6"),
            application_id=ApplicationId("app_6"),
            type="converted",
        )
        e2 = OutcomeEvent(
            id=OutcomeEventId("evt_6"),
            application_id=ApplicationId("app_6"),
            type="converted",
        )
        assert e1 == e2

    def test_not_equal_different_id(self):
        e1 = OutcomeEvent(
            id=OutcomeEventId("evt_7a"),
            application_id=ApplicationId("app_7"),
            type="submitted",
        )
        e2 = OutcomeEvent(
            id=OutcomeEventId("evt_7b"),
            application_id=ApplicationId("app_7"),
            type="submitted",
        )
        assert e1 != e2
