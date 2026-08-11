import pytest
from dataclasses import FrozenInstanceError

from applicant.core.entities.agent_intent import AgentIntent
from applicant.core.ids import AgentRunId, CampaignId


class TestAgentIntent:
    """Tests for the AgentIntent frozen dataclass."""

    def test_create_with_all_fields(self):
        run_id = AgentRunId("run-abc-123")
        camp_id = CampaignId("camp-xyz-456")
        intent = AgentIntent(
            id=run_id,
            campaign_id=camp_id,
            intent_sentence="Process next batch of job postings.",
        )
        assert intent.id == run_id
        assert intent.campaign_id == camp_id
        assert intent.intent_sentence == "Process next batch of job postings."

    def test_default_timestamp_is_datetime(self):
        intent = AgentIntent(
            id=AgentRunId("run-1"),
            campaign_id=CampaignId("camp-1"),
            intent_sentence="Refresh discovery sources.",
        )
        from datetime import datetime
        assert isinstance(intent.timestamp, datetime)

    def test_dataclass_is_frozen(self):
        intent = AgentIntent(
            id=AgentRunId("run-1"),
            campaign_id=CampaignId("camp-1"),
            intent_sentence="N/A",
        )
        with pytest.raises(FrozenInstanceError):
            intent.intent_sentence = "changed"

    def test_equal_when_same_fields(self):
        from datetime import UTC, datetime
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        a = AgentIntent(
            id=AgentRunId("run-eq"),
            campaign_id=CampaignId("camp-eq"),
            intent_sentence="Score candidate profiles.",
            timestamp=ts,
        )
        b = AgentIntent(
            id=AgentRunId("run-eq"),
            campaign_id=CampaignId("camp-eq"),
            intent_sentence="Score candidate profiles.",
            timestamp=ts,
        )
        assert a == b

    def test_not_equal_when_different_intent(self):
        a = AgentIntent(
            id=AgentRunId("a"),
            campaign_id=CampaignId("c"),
            intent_sentence="First intent.",
        )
        b = AgentIntent(
            id=AgentRunId("a"),
            campaign_id=CampaignId("c"),
            intent_sentence="Second intent.",
        )
        assert a != b

    def test_not_equal_when_different_id(self):
        a = AgentIntent(
            id=AgentRunId("x"),
            campaign_id=CampaignId("c"),
            intent_sentence="Same sentence.",
        )
        b = AgentIntent(
            id=AgentRunId("y"),
            campaign_id=CampaignId("c"),
            intent_sentence="Same sentence.",
        )
        assert a != b

    def test_repr_contains_fields(self):
        intent = AgentIntent(
            id=AgentRunId("run-repr"),
            campaign_id=CampaignId("camp-repr"),
            intent_sentence="Test repr.",
        )
        r = repr(intent)
        assert "run-repr" in r
        assert "camp-repr" in r
        assert "Test repr." in r

    def test_hashable(self):
        kwargs = {
            "id": AgentRunId("run-hash"),
            "campaign_id": CampaignId("camp-hash"),
            "intent_sentence": "Hashable test.",
        }
        s = {AgentIntent(**kwargs)}
        assert len(s) == 1

    def test_newtype_ids_are_strings_at_runtime(self):
        run_id = AgentRunId("agent-run-001")
        camp_id = CampaignId("campaign-001")
        assert isinstance(run_id, str)
        assert isinstance(camp_id, str)
