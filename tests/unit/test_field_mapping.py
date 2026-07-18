import pytest
from dataclasses import FrozenInstanceError

from applicant.core.entities.field_mapping import FieldMapping
from applicant.core.ids import FieldMappingId, CampaignId, AttributeId


class TestFieldMapping:
    """Tests for the FieldMapping frozen dataclass."""

    # --- construction ---

    def test_create_minimal(self):
        m = FieldMapping(FieldMappingId("fm-1"), "workday", "#first_name")
        assert m.id == "fm-1"
        assert m.site_key == "workday"
        assert m.field_selector == "#first_name"
        assert m.campaign_id is None
        assert m.attribute_id is None
        assert m.metadata == {}

    def test_create_full(self):
        m = FieldMapping(
            FieldMappingId("fm-2"),
            "greenhouse",
            "input[name=last_name]",
            campaign_id=CampaignId("camp-1"),
            attribute_id=AttributeId("attr-1"),
            metadata={"source": "auto-detect"},
        )
        assert m.id == "fm-2"
        assert m.site_key == "greenhouse"
        assert m.field_selector == "input[name=last_name]"
        assert m.campaign_id == "camp-1"
        assert m.attribute_id == "attr-1"
        assert m.metadata == {"source": "auto-detect"}

    def test_create_with_attribute_only(self):
        m = FieldMapping(
            FieldMappingId("fm-3"),
            "lever",
            "#email",
            attribute_id=AttributeId("attr-2"),
        )
        assert m.attribute_id == "attr-2"
        assert m.campaign_id is None
        assert m.metadata == {}

    def test_create_with_metadata(self):
        m = FieldMapping(
            FieldMappingId("fm-4"),
            "workday",
            "#phone",
            metadata={"confidence": 0.95, "verified": True},
        )
        assert m.metadata == {"confidence": 0.95, "verified": True}

    # --- is_shared property ---

    def test_is_shared_when_campaign_id_is_none(self):
        m = FieldMapping(FieldMappingId("fm-5"), "workday", "#field")
        assert m.is_shared is True

    def test_is_not_shared_when_campaign_id_is_set(self):
        m = FieldMapping(
            FieldMappingId("fm-6"),
            "greenhouse",
            "#field",
            campaign_id=CampaignId("camp-1"),
        )
        assert m.is_shared is False

    # --- immutability ---

    def test_cannot_mutate_id(self):
        m = FieldMapping(FieldMappingId("fm-7"), "workday", "#field")
        with pytest.raises(FrozenInstanceError):
            m.id = "other"  # type: ignore[misc]

    def test_cannot_mutate_site_key(self):
        m = FieldMapping(FieldMappingId("fm-8"), "workday", "#field")
        with pytest.raises(FrozenInstanceError):
            m.site_key = "greenhouse"  # type: ignore[misc]

    def test_cannot_mutate_campaign_id(self):
        m = FieldMapping(FieldMappingId("fm-9"), "workday", "#field")
        with pytest.raises(FrozenInstanceError):
            m.campaign_id = CampaignId("camp-1")  # type: ignore[misc]

    # --- equality ---

    def test_equality(self):
        m1 = FieldMapping(FieldMappingId("fm-10"), "workday", "#first_name")
        m2 = FieldMapping(FieldMappingId("fm-10"), "workday", "#first_name")
        assert m1 == m2

    def test_inequality_different_id(self):
        m1 = FieldMapping(FieldMappingId("fm-11"), "workday", "#first_name")
        m2 = FieldMapping(FieldMappingId("fm-12"), "workday", "#first_name")
        assert m1 != m2

    def test_inequality_different_site_key(self):
        m1 = FieldMapping(FieldMappingId("fm-13"), "workday", "#first_name")
        m2 = FieldMapping(FieldMappingId("fm-13"), "greenhouse", "#first_name")
        assert m1 != m2

    def test_repr(self):
        m = FieldMapping(FieldMappingId("fm-14"), "workday", "#first_name")
        r = repr(m)
        assert "FieldMapping" in r
        assert "fm-14" in r
        assert "workday" in r
