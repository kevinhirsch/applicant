"""Unit tests for AgentRun entity (FR-AGENT-1/2/7).

Covers construction with defaults, explicit fields, immutability (frozen),
equality, repr, unhashability (stats dict makes it unhashable),
timestamp/seq defaults, and dict default_factory isolation.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from applicant.core.entities.agent_run import AgentRun
from applicant.core.entities.campaign import RunMode
from applicant.core.ids import AgentRunId, CampaignId


@pytest.fixture(autouse=True)
def _reset_seq():
    """Reset the module-level _SEQ counter to avoid cross-test pollution (xdist)."""
    import applicant.core.entities.agent_run as ar

    ar._SEQ = itertools.count(1)


class TestAgentRun:
    """AgentRun entity tests (FR-AGENT-1/2/7)."""

    @pytest.mark.unit
    def test_construction_with_defaults(self):
        run = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        assert run.id == "r1"
        assert run.campaign_id == "c1"
        assert run.intent_sentence == ""
        assert run.run_mode == RunMode.CONTINUOUS
        assert run.throughput_target == 15
        assert run.stats == {}
        assert isinstance(run.timestamp, datetime)
        assert run.seq == 1

    @pytest.mark.unit
    def test_construction_with_all_fields(self):
        ts = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
        run = AgentRun(
            id=AgentRunId("r2"),
            campaign_id=CampaignId("c2"),
            intent_sentence="process first batch",
            run_mode=RunMode.FIXED_DURATION,
            throughput_target=30,
            stats={"processed": 5, "viable": 3},
            timestamp=ts,
        )
        assert run.id == "r2"
        assert run.campaign_id == "c2"
        assert run.intent_sentence == "process first batch"
        assert run.run_mode == RunMode.FIXED_DURATION
        assert run.throughput_target == 30
        assert run.stats == {"processed": 5, "viable": 3}
        assert run.timestamp == ts
        assert run.seq == 1

    @pytest.mark.unit
    def test_frozen_immutability(self):
        run = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        with pytest.raises(AttributeError):
            run.intent_sentence = "changed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_equality(self):
        ts = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
        r1 = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
            seq=1,
        )
        r2 = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
            seq=1,
        )
        r3 = AgentRun(
            id=AgentRunId("r2"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
        )
        assert r1 == r2
        assert r1 != r3

    @pytest.mark.unit
    def test_unhashable(self):
        """AgentRun has a dict field (stats) — frozen dataclass auto-sets
        __hash__ to None when any field type is unhashable."""
        run = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        with pytest.raises(TypeError):
            hash(run)

    @pytest.mark.unit
    def test_seq_monotonic(self):
        """Sequential runs get increasing seq values (FR-AGENT-7)."""
        ts = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
        r1 = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
        )
        r2 = AgentRun(
            id=AgentRunId("r2"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
        )
        r3 = AgentRun(
            id=AgentRunId("r3"),
            campaign_id=CampaignId("c1"),
            timestamp=ts,
        )
        assert r1.seq == 1
        assert r2.seq == 2
        assert r3.seq == 3

    @pytest.mark.unit
    def test_repr(self):
        run = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        rep = repr(run)
        assert "AgentRun(" in rep
        assert "r1" in rep
        assert "c1" in rep

    @pytest.mark.unit
    def test_timestamp_default_is_utc_now(self):
        """Default timestamp should be near the current UTC time."""
        before = datetime.now(UTC)
        run = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        after = datetime.now(UTC)
        assert before <= run.timestamp <= after

    @pytest.mark.unit
    def test_dict_default_factory_isolation(self):
        """Each instance gets its own stats dict, not shared state."""
        r1 = AgentRun(
            id=AgentRunId("r1"),
            campaign_id=CampaignId("c1"),
        )
        r2 = AgentRun(
            id=AgentRunId("r2"),
            campaign_id=CampaignId("c1"),
        )
        r1.stats["processed"] = 5
        assert r2.stats == {}

    @pytest.mark.unit
    def test_field_types(self):
        """Verify fields() returns the expected names."""
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(AgentRun)}
        expected = {
            "id",
            "campaign_id",
            "intent_sentence",
            "run_mode",
            "throughput_target",
            "stats",
            "timestamp",
            "seq",
        }
        assert field_names == expected
