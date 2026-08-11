import pytest
from datetime import UTC, datetime

from applicant.core.entities.action_event import ActionEvent
from applicant.core.ids import ActionEventId, ApplicationId, CampaignId


class TestActionEventDefaults:
    """ActionEvent uses sensible defaults for all optional fields."""

    def test_minimal_construction(self):
        ev = ActionEvent(id=ActionEventId("evt-1"))
        assert ev.id == "evt-1"
        assert ev.application_id is None
        assert ev.campaign_id is None
        assert ev.actor == "engine"
        assert ev.action == ""
        assert ev.reason == ""
        assert ev.context == {}

    def test_occurred_at_defaults_to_now(self):
        before = datetime.now(UTC)
        ev = ActionEvent(id=ActionEventId("evt-2"))
        after = datetime.now(UTC)
        assert before <= ev.occurred_at <= after

    def test_context_is_independent_per_instance(self):
        ev1 = ActionEvent(id=ActionEventId("evt-3"))
        ev2 = ActionEvent(id=ActionEventId("evt-4"))
        assert ev1.context is not ev2.context


class TestActionEventCustomValues:
    """All fields accept custom values."""

    def test_full_construction(self):
        ev = ActionEvent(
            id=ActionEventId("evt-5"),
            occurred_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            application_id=ApplicationId("app-1"),
            campaign_id=CampaignId("camp-1"),
            actor="user",
            action="applied",
            reason="manual submission",
            context={"url": "https://example.com"},
        )
        assert ev.id == "evt-5"
        assert ev.occurred_at == datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
        assert ev.application_id == "app-1"
        assert ev.campaign_id == "camp-1"
        assert ev.actor == "user"
        assert ev.action == "applied"
        assert ev.reason == "manual submission"
        assert ev.context == {"url": "https://example.com"}


class TestActionEventFrozen:
    """ActionEvent is a frozen dataclass."""

    def test_cannot_modify_id(self):
        ev = ActionEvent(id=ActionEventId("evt-6"))
        with pytest.raises(AttributeError):
            ev.id = ActionEventId("evt-7")

    def test_cannot_modify_action(self):
        ev = ActionEvent(id=ActionEventId("evt-7"))
        with pytest.raises(AttributeError):
            ev.action = "scored"

    def test_cannot_modify_context(self):
        ev = ActionEvent(id=ActionEventId("evt-8"))
        with pytest.raises(AttributeError):
            ev.context = {"key": "value"}
