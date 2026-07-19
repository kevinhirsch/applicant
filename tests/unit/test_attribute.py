"""Unit tests for Attribute and AttributeStore entities (FR-ATTR-*).

Covers equality, immutability, hashability, matches(), and store upsert/find.
"""

from __future__ import annotations

import pytest

from applicant.core.entities.attribute import Attribute, AttributeStore
from applicant.core.ids import AttributeId, CampaignId


@pytest.fixture(autouse=True)
def _no_state_leak():
    """No module-level state to clear; present for parallel xdist safety."""
    pass


class TestAttribute:
    """Attribute entity tests (FR-ATTR-*)."""

    def test_construction_with_defaults(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        assert attr.id == "a1"
        assert attr.campaign_id == "c1"
        assert attr.name == "years_experience"
        assert attr.value == "5"
        assert attr.aliases == ()
        assert attr.is_integral is False
        assert attr.is_sensitive is False

    def test_construction_with_all_fields(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
            aliases=("yoe", "exp"),
            is_integral=True,
            is_sensitive=True,
        )
        assert attr.aliases == (
            "yoe",
            "exp",
        )
        assert attr.is_integral is True
        assert attr.is_sensitive is True

    def test_immutability(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        with pytest.raises(AttributeError):
            attr.name = "new_name"  # type: ignore[misc]

    def test_equality(self):
        a1 = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        a2 = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        a3 = Attribute(
            id=AttributeId("a2"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        assert a1 == a2
        assert a1 != a3

    def test_hashable(self):
        """Frozen dataclass with tuple fields — is hashable."""
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        s = {attr}
        assert attr in s

    def test_matches_name(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        assert attr.matches("years_experience") is True
        assert attr.matches("Years_Experience") is True
        assert attr.matches("  years_experience  ") is True
        assert attr.matches("experience") is False

    def test_matches_alias(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
            aliases=("yoe", "exp"),
        )
        assert attr.matches("yoe") is True
        assert attr.matches("YOE") is True
        assert attr.matches("exp") is True
        assert attr.matches("EXP") is True
        assert attr.matches("  yoe  ") is True
        assert attr.matches("other") is False

    def test_matches_no_aliases(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        assert attr.matches("other") is False


class TestAttributeStore:
    """AttributeStore entity tests (FR-ATTR-1)."""

    def test_construction(self):
        store = AttributeStore(campaign_id=CampaignId("c1"))
        assert store.campaign_id == "c1"
        assert store.attributes == ()

    def test_find_by_name(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        store = AttributeStore(
            campaign_id=CampaignId("c1"), attributes=(attr,)
        )
        assert store.find("years_experience") is attr
        assert store.find("nonexistent") is None

    def test_find_by_alias(self):
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
            aliases=("yoe",),
        )
        store = AttributeStore(
            campaign_id=CampaignId("c1"), attributes=(attr,)
        )
        assert store.find("yoe") is attr

    def test_upsert_new(self):
        store = AttributeStore(campaign_id=CampaignId("c1"))
        attr = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        new_store = store.upsert(attr)
        assert new_store is not store
        assert new_store.attributes == (attr,)

    def test_upsert_replace_by_id(self):
        attr_old = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        attr_new = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="10",
        )
        store = AttributeStore(
            campaign_id=CampaignId("c1"), attributes=(attr_old,)
        )
        new_store = store.upsert(attr_new)
        assert new_store is not store
        assert len(new_store.attributes) == 1
        assert new_store.attributes[0].value == "10"

    def test_upsert_preserves_other_attributes(self):
        a1 = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="5",
        )
        a2 = Attribute(
            id=AttributeId("a2"),
            campaign_id=CampaignId("c1"),
            name="degree",
            value="BS",
        )
        store = AttributeStore(
            campaign_id=CampaignId("c1"), attributes=(a1, a2)
        )
        a1_updated = Attribute(
            id=AttributeId("a1"),
            campaign_id=CampaignId("c1"),
            name="years_experience",
            value="10",
        )
        new_store = store.upsert(a1_updated)
        assert len(new_store.attributes) == 2
        # a2 is still there
        assert new_store.find("degree") is a2
        # a1 is updated
        found = new_store.find("years_experience")
        assert found is not None
        assert found.value == "10"

    def test_immutability(self):
        store = AttributeStore(campaign_id=CampaignId("c1"))
        with pytest.raises(AttributeError):
            store.campaign_id = "c2"  # type: ignore[misc]

    def test_hashable(self):
        store = AttributeStore(campaign_id=CampaignId("c1"))
        s = {store}
        assert store in s

    def test_equality(self):
        s1 = AttributeStore(campaign_id=CampaignId("c1"))
        s2 = AttributeStore(campaign_id=CampaignId("c1"))
        s3 = AttributeStore(campaign_id=CampaignId("c2"))
        assert s1 == s2
        assert s1 != s3

