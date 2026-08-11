"""Tests for DiscoverySource entity (AZ0-72)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from applicant.core.entities.discovery_source import DiscoverySource
from applicant.core.ids import CampaignId, DiscoverySourceId


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """No lru_cache in discovery_source.py, but autouse for xdist parallel safety."""
    pass


@pytest.mark.unit
class TestDiscoverySource:
    """Tests for the DiscoverySource frozen dataclass (FR-DISC-2/5)."""

    def test_construct_with_defaults(self):
        """Default enabled is True, yield_stats is an empty dict."""
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-01"),
            campaign_id=CampaignId("camp-test-01"),
            source_key="linkedin",
        )
        assert src.id == "ds-test-01"
        assert src.campaign_id == "camp-test-01"
        assert src.source_key == "linkedin"
        assert src.enabled is True
        assert src.yield_stats == {}

    def test_construct_with_explicit_values(self):
        """Explicit enabled=False and non-empty yield_stats are accepted."""
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-02"),
            campaign_id=CampaignId("camp-test-02"),
            source_key="indeed",
            enabled=False,
            yield_stats={"matches": 5},
        )
        assert src.enabled is False
        assert src.yield_stats == {"matches": 5}

    def test_frozen_prevents_attribute_assignment(self):
        """Frozen dataclass raises FrozenInstanceError on setattr."""
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-03"),
            campaign_id=CampaignId("camp-test-03"),
            source_key="monster",
        )
        with pytest.raises(FrozenInstanceError):
            src.enabled = False

    def test_internal_dict_mutation_possible(self):
        """Frozen prevents field reassignment, not mutation of the dict
        object referenced by yield_stats."""
        stats: dict = {"views": 1}
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-04"),
            campaign_id=CampaignId("camp-test-04"),
            source_key="ziprecruiter",
            yield_stats=stats,
        )
        stats["clicks"] = 2
        assert src.yield_stats == {"views": 1, "clicks": 2}

    def test_not_hashable(self):
        """Because yield_stats is a dict (unhashable), DiscoverySource
        instances raise TypeError on hash()."""
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-05"),
            campaign_id=CampaignId("camp-test-05"),
            source_key="google jobs",
        )
        with pytest.raises(TypeError):
            hash(src)

    def test_equal_by_field_values(self):
        """Two instances with identical field values compare equal."""
        a = DiscoverySource(
            id=DiscoverySourceId("ds-test-06"),
            campaign_id=CampaignId("camp-test-06"),
            source_key="glassdoor",
            yield_stats={"views": 10},
        )
        b = DiscoverySource(
            id=DiscoverySourceId("ds-test-06"),
            campaign_id=CampaignId("camp-test-06"),
            source_key="glassdoor",
            yield_stats={"views": 10},
        )
        assert a == b

    def test_not_equal_when_fields_differ(self):
        """Instances differing in any field are not equal."""
        a = DiscoverySource(
            id=DiscoverySourceId("ds-test-07"),
            campaign_id=CampaignId("camp-test-07"),
            source_key="linkedin",
        )
        b = DiscoverySource(
            id=DiscoverySourceId("ds-test-07"),
            campaign_id=CampaignId("camp-test-07"),
            source_key="indeed",
        )
        assert a != b

    def test_repr_contains_field_values(self):
        """repr() includes the dataclass fields for debugging."""
        src = DiscoverySource(
            id=DiscoverySourceId("ds-test-08"),
            campaign_id=CampaignId("camp-test-08"),
            source_key="dice",
        )
        r = repr(src)
        assert "DiscoverySource(" in r
        assert "ds-test-08" in r
        assert "camp-test-08" in r
        assert "dice" in r

    def test_type_annotations_via_dataclass_fields(self):
        """dataclass.fields() returns the correct field definitions."""
        import dataclasses
        fields = dataclasses.fields(DiscoverySource)
        names = [f.name for f in fields]
        assert names == ["id", "campaign_id", "source_key", "enabled", "yield_stats"]
