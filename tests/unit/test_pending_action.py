"""Unit tests for PendingAction entity (FR-UI-3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.core.entities.pending_action import PendingAction
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId


@pytest.fixture(autouse=True)
def _parallel_safe_reset():
    """No mutable module-level state to clear; fixture exists for xdist safety."""
    pass


@pytest.mark.unit
class TestPendingActionConstruction:
    """Construction and default value behaviour."""

    def test_required_fields(self):
        obj = PendingAction(
            id=PendingActionId("pa-1"),
            campaign_id=CampaignId("cam-1"),
            kind="digest_approval",
            title="Approve weekly digest",
        )
        assert obj.id == "pa-1"
        assert obj.campaign_id == "cam-1"
        assert obj.kind == "digest_approval"
        assert obj.title == "Approve weekly digest"

    def test_default_application_id_is_none(self):
        obj = PendingAction(
            id=PendingActionId("pa-2"),
            campaign_id=CampaignId("cam-2"),
            kind="material_review",
            title="Review materials",
        )
        assert obj.application_id is None

    def test_explicit_application_id(self):
        obj = PendingAction(
            id=PendingActionId("pa-3"),
            campaign_id=CampaignId("cam-3"),
            kind="final_approval",
            title="Final sign-off",
            application_id=ApplicationId("app-1"),
        )
        assert obj.application_id == "app-1"

    def test_default_payload_is_empty_dict(self):
        obj = PendingAction(
            id=PendingActionId("pa-4"),
            campaign_id=CampaignId("cam-4"),
            kind="missing_attr",
            title="Missing attribute",
        )
        assert obj.payload == {}
        assert isinstance(obj.payload, dict)

    def test_default_factory_returns_separate_dict_per_instance(self):
        obj1 = PendingAction(
            id=PendingActionId("pa-5"),
            campaign_id=CampaignId("cam-5"),
            kind="digest_approval",
            title="A",
        )
        obj2 = PendingAction(
            id=PendingActionId("pa-6"),
            campaign_id=CampaignId("cam-6"),
            kind="digest_approval",
            title="B",
        )
        assert obj1.payload is not obj2.payload

    def test_explicit_payload(self):
        data = {"key": "value"}
        obj = PendingAction(
            id=PendingActionId("pa-7"),
            campaign_id=CampaignId("cam-7"),
            kind="digest_approval",
            title="With payload",
            payload=data,
        )
        assert obj.payload == {"key": "value"}
        assert obj.payload is data

    def test_default_resolved_is_false(self):
        obj = PendingAction(
            id=PendingActionId("pa-8"),
            campaign_id=CampaignId("cam-8"),
            kind="digest_approval",
            title="Unresolved",
        )
        assert obj.resolved is False

    def test_explicit_resolved_true(self):
        obj = PendingAction(
            id=PendingActionId("pa-9"),
            campaign_id=CampaignId("cam-9"),
            kind="digest_approval",
            title="Resolved",
            resolved=True,
        )
        assert obj.resolved is True

    def test_created_at_defaults_to_now_utc(self):
        before = datetime.now(UTC).replace(microsecond=0)
        obj = PendingAction(
            id=PendingActionId("pa-10"),
            campaign_id=CampaignId("cam-10"),
            kind="digest_approval",
            title="Time check",
        )
        after = datetime.now(UTC).replace(microsecond=0)
        assert obj.created_at.tzinfo is not None
        assert before <= obj.created_at.replace(microsecond=0) <= after


@pytest.mark.unit
class TestPendingActionImmutability:
    """Frozen dataclass should reject field assignment."""

    def test_cannot_assign_to_frozen_field(self):
        obj = PendingAction(
            id=PendingActionId("pa-20"),
            campaign_id=CampaignId("cam-20"),
            kind="digest_approval",
            title="Frozen",
        )
        with pytest.raises(AttributeError, match="cannot assign to field"):
            obj.kind = "changed"


@pytest.mark.unit
class TestPendingActionEquality:
    """Equality and inequality."""

    def test_equal_when_fields_match(self):
        ts = datetime.now(UTC)
        obj1 = PendingAction(
            id=PendingActionId("pa-30"),
            campaign_id=CampaignId("cam-30"),
            kind="digest_approval",
            title="Equal",
            created_at=ts,
        )
        obj2 = PendingAction(
            id=PendingActionId("pa-30"),
            campaign_id=CampaignId("cam-30"),
            kind="digest_approval",
            title="Equal",
            created_at=ts,
        )
        assert obj1 == obj2

    def test_not_equal_when_id_differs(self):
        obj1 = PendingAction(
            id=PendingActionId("pa-31"),
            campaign_id=CampaignId("cam-31"),
            kind="digest_approval",
            title="Diff",
        )
        obj2 = PendingAction(
            id=PendingActionId("pa-32"),
            campaign_id=CampaignId("cam-31"),
            kind="digest_approval",
            title="Diff",
        )
        assert obj1 != obj2

    def test_not_equal_when_title_differs(self):
        obj1 = PendingAction(
            id=PendingActionId("pa-33"),
            campaign_id=CampaignId("cam-33"),
            kind="digest_approval",
            title="One",
        )
        obj2 = PendingAction(
            id=PendingActionId("pa-33"),
            campaign_id=CampaignId("cam-33"),
            kind="digest_approval",
            title="Two",
        )
        assert obj1 != obj2


@pytest.mark.unit
class TestPendingActionRepr:
    """repr() introspection."""

    def test_repr_contains_fields(self):
        obj = PendingAction(
            id=PendingActionId("pa-40"),
            campaign_id=CampaignId("cam-40"),
            kind="digest_approval",
            title="Repr test",
        )
        r = repr(obj)
        assert "PendingAction" in r
        assert "pa-40" in r
        assert "cam-40" in r
        assert "digest_approval" in r
        assert "Repr test" in r


@pytest.mark.unit
class TestPendingActionHashability:
    """Frozen dataclass with mutable dict field is not hashable."""

    def test_hash_raises_type_error(self):
        obj = PendingAction(
            id=PendingActionId("pa-50"),
            campaign_id=CampaignId("cam-50"),
            kind="digest_approval",
            title="Hash test",
        )
        with pytest.raises(TypeError, match="unhashable"):
            hash(obj)


@pytest.mark.unit
class TestPendingActionDataclassFields:
    """dataclass field introspection."""

    def test_all_fields_present(self):
        from dataclasses import fields

        field_names = [f.name for f in fields(PendingAction)]
        assert field_names == [
            "id",
            "campaign_id",
            "kind",
            "title",
            "application_id",
            "payload",
            "resolved",
            "created_at",
        ]
