import dataclasses

import pytest

from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId


class TestSearchCriteriaDefaults:
    """Test that SearchCriteria has correct default values."""

    def test_default_values(self):
        """All optional fields should have their documented defaults."""
        criteria = SearchCriteria(campaign_id=CampaignId("test-campaign"))
        assert criteria.human_readable == ""
        assert criteria.titles == ()
        assert criteria.locations == ()
        assert criteria.work_modes == ()
        assert criteria.salary_floor is None
        assert criteria.keywords == ()
        assert criteria.learned_adjustments == {}

    def test_campaign_id_is_stored(self):
        """campaign_id should be stored as-is."""
        cid = CampaignId("my-campaign-id")
        criteria = SearchCriteria(campaign_id=cid)
        assert criteria.campaign_id == cid


class TestSearchCriteriaCustomValues:
    """Test that SearchCriteria accepts and stores custom values."""

    def test_custom_human_readable(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            human_readable="Senior Python Developer in Berlin",
        )
        assert criteria.human_readable == "Senior Python Developer in Berlin"

    def test_custom_titles(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            titles=("Engineer", "Developer"),
        )
        assert criteria.titles == ("Engineer", "Developer")

    def test_custom_locations(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            locations=("Berlin", "Remote"),
        )
        assert criteria.locations == ("Berlin", "Remote")

    def test_custom_work_modes(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            work_modes=("remote", "hybrid"),
        )
        assert criteria.work_modes == ("remote", "hybrid")

    def test_custom_salary_floor(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            salary_floor=80000,
        )
        assert criteria.salary_floor == 80000

    def test_custom_keywords(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            keywords=("python", "fastapi"),
        )
        assert criteria.keywords == ("python", "fastapi")

    def test_custom_learned_adjustments(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            learned_adjustments={"boost": 1.5},
        )
        assert criteria.learned_adjustments == {"boost": 1.5}


class TestSearchCriteriaImmutability:
    """Test that SearchCriteria is frozen (frozen dataclass)."""

    def test_cannot_modify_campaign_id(self):
        criteria = SearchCriteria(campaign_id=CampaignId("c1"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            criteria.campaign_id = CampaignId("c2")

    def test_cannot_modify_human_readable(self):
        criteria = SearchCriteria(campaign_id=CampaignId("c1"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            criteria.human_readable = "new value"

    def test_cannot_modify_tuples(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            titles=("A",),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            criteria.titles = ("B",)

    def test_cannot_modify_salary_floor(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            salary_floor=50000,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            criteria.salary_floor = 60000

    def test_cannot_modify_learned_adjustments_dict(self):
        criteria = SearchCriteria(
            campaign_id=CampaignId("c1"),
            learned_adjustments={"key": "value"},
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            criteria.learned_adjustments = {"new_key": "new_value"}


class TestSearchCriteriaIsolation:
    """Test that mutable defaults are not shared between instances."""

    def test_learned_adjustments_not_shared(self):
        """Each instance should get a fresh dict for learned_adjustments."""
        c1 = SearchCriteria(campaign_id=CampaignId("c1"))
        c2 = SearchCriteria(campaign_id=CampaignId("c2"))
        c1.learned_adjustments["x"] = 1
        assert "x" not in c2.learned_adjustments

    def test_tuple_defaults_are_empty_tuples(self):
        """Tuple defaults should be empty tuples, not lists."""
        criteria = SearchCriteria(campaign_id=CampaignId("c1"))
        assert isinstance(criteria.titles, tuple)
        assert isinstance(criteria.locations, tuple)
        assert isinstance(criteria.work_modes, tuple)
        assert isinstance(criteria.keywords, tuple)
