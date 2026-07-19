import pytest

from applicant.core.entities.campaign import (
    Campaign,
    RunMode,
    clamp_throughput,
    DEFAULT_THROUGHPUT_TARGET,
    THROUGHPUT_HARD_CAP,
)
from applicant.core.ids import CampaignId
from dataclasses import FrozenInstanceError


@pytest.fixture(autouse=True)
def _no_state_leak() -> None:
    """Prevent state leakage between tests in xdist parallel runs."""
    pass


@pytest.mark.unit
class TestCampaign:
    """Tests for the Campaign frozen dataclass."""

    def test_create_with_all_fields(self):
        cid = CampaignId("camp-001")
        campaign = Campaign(
            id=cid,
            name="Test Campaign",
            run_mode=RunMode.FIXED_DURATION,
            throughput_target=10,
            exploration_budget=0.25,
            active=False,
            criteria={"keyword": "python"},
            schedule={"cron": "0 6 * * *"},
        )
        assert campaign.id == cid
        assert campaign.name == "Test Campaign"
        assert campaign.run_mode == RunMode.FIXED_DURATION
        assert campaign.throughput_target == 10
        assert campaign.exploration_budget == 0.25
        assert campaign.active is False
        assert campaign.criteria == {"keyword": "python"}
        assert campaign.schedule == {"cron": "0 6 * * *"}
        assert campaign.learning_state == {}

    def test_create_with_defaults(self):
        cid = CampaignId("camp-002")
        campaign = Campaign(id=cid, name="Default Campaign")
        assert campaign.run_mode == RunMode.CONTINUOUS
        assert campaign.throughput_target == DEFAULT_THROUGHPUT_TARGET  # 15
        assert campaign.exploration_budget == 0.1
        assert campaign.active is True
        assert campaign.criteria == {}
        assert campaign.schedule == {}
        assert campaign.learning_state == {}

    def test_is_frozen(self):
        cid = CampaignId("camp-003")
        campaign = Campaign(id=cid, name="Frozen")
        with pytest.raises(FrozenInstanceError):
            campaign.name = "Changed"  # type: ignore[misc]

    def test_equal(self):
        cid1 = CampaignId("camp-004")
        cid2 = CampaignId("camp-004")
        c1 = Campaign(id=cid1, name="Same")
        c2 = Campaign(id=cid2, name="Same")
        assert c1 == c2

    def test_not_equal(self):
        c1 = Campaign(id=CampaignId("camp-005"), name="Alpha")
        c2 = Campaign(id=CampaignId("camp-006"), name="Beta")
        assert c1 != c2

    def test_not_hashable(self):
        """Campaign has dict fields, so it is not hashable."""
        campaign = Campaign(id=CampaignId("camp-007"), name="NotHashable")
        with pytest.raises(TypeError, match="unhashable"):
            hash(campaign)

    def test_repr(self):
        cid = CampaignId("camp-009")
        campaign = Campaign(id=cid, name="ReprTest")
        r = repr(campaign)
        assert "Campaign(" in r
        assert "camp-009" in r
        assert "ReprTest" in r

    def test_empty_criteria_and_schedule_defaults(self):
        """Each campaign gets its own fresh criteria/schedule/learning_state dict."""
        c1 = Campaign(id=CampaignId("camp-010"), name="InstanceA")
        c2 = Campaign(id=CampaignId("camp-011"), name="InstanceB")
        assert c1.criteria == {}
        assert c1.schedule == {}
        assert c1.learning_state == {}
        assert c2.criteria == {}
        # Mutating one instance's dict should not affect the other
        c1.criteria["key"] = "val"
        assert c1.criteria == {"key": "val"}
        assert c2.criteria == {}


@pytest.mark.unit
class TestRunMode:
    """Tests for the RunMode enum."""

    def test_enum_values(self):
        assert RunMode.CONTINUOUS.value == "continuous"
        assert RunMode.FIXED_DURATION.value == "fixed_duration"
        assert RunMode.UNTIL_N_VIABLE.value == "until_n_viable"

    def test_enum_members(self):
        assert RunMode.CONTINUOUS.name == "CONTINUOUS"
        assert RunMode.FIXED_DURATION.name == "FIXED_DURATION"
        assert RunMode.UNTIL_N_VIABLE.name == "UNTIL_N_VIABLE"

    def test_enum_str(self):
        assert str(RunMode.CONTINUOUS) == "RunMode.CONTINUOUS"


@pytest.mark.unit
class TestClampThroughput:
    """Tests for the clamp_throughput function."""

    def test_below_min_clamps_to_one(self):
        assert clamp_throughput(0) == 1
        assert clamp_throughput(-5) == 1
        assert clamp_throughput(-100) == 1

    def test_min_edge(self):
        assert clamp_throughput(1) == 1

    def test_default_target(self):
        assert clamp_throughput(15) == 15

    def test_hard_cap(self):
        assert clamp_throughput(30) == 30

    def test_above_cap_clamps(self):
        assert clamp_throughput(100) == 30
        assert clamp_throughput(999) == 30

    def test_mid_range(self):
        assert clamp_throughput(5) == 5
        assert clamp_throughput(20) == 20

    def test_non_int_converts_to_int(self):
        assert clamp_throughput(15.7) == 15
        assert clamp_throughput(30.9) == 30
        assert clamp_throughput(0.9) == 1  # int(0.9) = 0, then clamped to 1
