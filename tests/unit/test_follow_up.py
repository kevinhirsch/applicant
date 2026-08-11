"""Unit tests for the FollowUp entity (frozen dataclass + enums)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dataclasses import FrozenInstanceError

from applicant.core.entities.follow_up import FollowUp, FollowUpStatus, FollowUpTemplate
from applicant.core.ids import ApplicationId, CampaignId, FollowUpId


@pytest.fixture(autouse=True)
def _no_state_leak() -> None:
    """Prevent xdist parallel state leakage — marker-only, no side effects."""
    return


class TestFollowUp:
    """Tests for the frozen FollowUp dataclass."""

    @pytest.mark.unit
    def test_create_with_all_fields(self) -> None:
        """Creating a FollowUp with all explicit fields sets every attribute."""
        now = datetime.now(UTC)
        follow_up = FollowUp(
            id=FollowUpId("fu-001"),
            campaign_id=CampaignId("cmp-001"),
            application_id=ApplicationId("app-001"),
            template=FollowUpTemplate.CHECK_IN,
            status=FollowUpStatus.SENT,
            subject="How are things going?",
            body="Just checking in on your application.",
            scheduled_at=now,
            sent_at=now,
            created_at=now,
        )
        assert follow_up.id == "fu-001"
        assert follow_up.campaign_id == "cmp-001"
        assert follow_up.application_id == "app-001"
        assert follow_up.template == FollowUpTemplate.CHECK_IN
        assert follow_up.status == FollowUpStatus.SENT
        assert follow_up.subject == "How are things going?"
        assert follow_up.body == "Just checking in on your application."
        assert follow_up.scheduled_at == now
        assert follow_up.sent_at == now
        assert follow_up.created_at == now

    @pytest.mark.unit
    def test_create_with_defaults(self) -> None:
        """Omitted optional fields get their default values."""
        follow_up = FollowUp(
            id=FollowUpId("fu-002"),
            campaign_id=CampaignId("cmp-002"),
            application_id=ApplicationId("app-002"),
            template=FollowUpTemplate.THANK_YOU,
        )
        assert follow_up.status == FollowUpStatus.SCHEDULED
        assert follow_up.subject == ""
        assert follow_up.body == ""
        assert follow_up.scheduled_at is None
        assert follow_up.sent_at is None
        assert isinstance(follow_up.created_at, datetime)

    @pytest.mark.unit
    def test_frozen_dataclass_raises(self) -> None:
        """Attempting to mutate a FollowUp raises FrozenInstanceError."""
        follow_up = FollowUp(
            id=FollowUpId("fu-003"),
            campaign_id=CampaignId("cmp-003"),
            application_id=ApplicationId("app-003"),
            template=FollowUpTemplate.REJECTION_FOLLOW_UP,
        )
        with pytest.raises(FrozenInstanceError):
            follow_up.status = FollowUpStatus.SENT  # type: ignore[misc]

    @pytest.mark.unit
    def test_follow_up_template_enum_values(self) -> None:
        """FollowUpTemplate members have the expected string values."""
        assert FollowUpTemplate.THANK_YOU.value == "thank_you"
        assert FollowUpTemplate.CHECK_IN.value == "check_in"
        assert FollowUpTemplate.REJECTION_FOLLOW_UP.value == "rejection_follow_up"

    @pytest.mark.unit
    def test_follow_up_status_enum_values(self) -> None:
        """FollowUpStatus members have the expected string values."""
        assert FollowUpStatus.SCHEDULED.value == "SCHEDULED"
        assert FollowUpStatus.SENT.value == "SENT"
        assert FollowUpStatus.FAILED.value == "FAILED"
        assert FollowUpStatus.CANCELLED.value == "CANCELLED"

    @pytest.mark.unit
    def test_equality_same_values(self) -> None:
        """Two FollowUp instances with identical fields are equal."""
        now = datetime(2026, 7, 18, tzinfo=UTC)
        a = FollowUp(
            id=FollowUpId("fu-010"),
            campaign_id=CampaignId("cmp-010"),
            application_id=ApplicationId("app-010"),
            template=FollowUpTemplate.CHECK_IN,
            created_at=now,
        )
        b = FollowUp(
            id=FollowUpId("fu-010"),
            campaign_id=CampaignId("cmp-010"),
            application_id=ApplicationId("app-010"),
            template=FollowUpTemplate.CHECK_IN,
            created_at=now,
        )
        assert a == b
        assert not (a != b)

    @pytest.mark.unit
    def test_inequality_different_fields(self) -> None:
        """Changing any field makes two FollowUp instances unequal."""
        base = FollowUp(
            id=FollowUpId("fu-011"),
            campaign_id=CampaignId("cmp-011"),
            application_id=ApplicationId("app-011"),
            template=FollowUpTemplate.THANK_YOU,
        )
        # Different id
        other_id = FollowUp(
            id=FollowUpId("fu-999"),
            campaign_id=CampaignId("cmp-011"),
            application_id=ApplicationId("app-011"),
            template=FollowUpTemplate.THANK_YOU,
        )
        assert base != other_id
        # Different campaign_id
        other_campaign = FollowUp(
            id=FollowUpId("fu-011"),
            campaign_id=CampaignId("cmp-999"),
            application_id=ApplicationId("app-011"),
            template=FollowUpTemplate.THANK_YOU,
        )
        assert base != other_campaign
        # Different template
        other_template = FollowUp(
            id=FollowUpId("fu-011"),
            campaign_id=CampaignId("cmp-011"),
            application_id=ApplicationId("app-011"),
            template=FollowUpTemplate.CHECK_IN,
        )
        assert base != other_template

    @pytest.mark.unit
    def test_hashable(self) -> None:
        """FollowUp instances can be used in sets and as dict keys."""
        now = datetime(2026, 7, 18, tzinfo=UTC)
        a = FollowUp(
            id=FollowUpId("fu-020"),
            campaign_id=CampaignId("cmp-020"),
            application_id=ApplicationId("app-020"),
            template=FollowUpTemplate.CHECK_IN,
            created_at=now,
        )
        b = FollowUp(
            id=FollowUpId("fu-020"),
            campaign_id=CampaignId("cmp-020"),
            application_id=ApplicationId("app-020"),
            template=FollowUpTemplate.CHECK_IN,
            created_at=now,
        )
        s = {a}
        # b is equal to a so it should resolve to the same hash bucket
        assert b in s
        # Verify we can use it as a dict key
        d: dict[FollowUp, str] = {a: "hello"}
        assert d[a] == "hello"
        assert d[b] == "hello"

    @pytest.mark.unit
    def test_repr_contains_fields(self) -> None:
        """The repr string includes all dataclass field names."""
        follow_up = FollowUp(
            id=FollowUpId("fu-030"),
            campaign_id=CampaignId("cmp-030"),
            application_id=ApplicationId("app-030"),
            template=FollowUpTemplate.REJECTION_FOLLOW_UP,
        )
        r = repr(follow_up)
        assert "FollowUp(" in r
        assert "id=" in r
        assert "campaign_id=" in r
        assert "application_id=" in r
        assert "template=" in r
        assert "status=" in r
        assert "subject=" in r
        assert "body=" in r
        assert "scheduled_at=" in r
        assert "sent_at=" in r
        assert "created_at=" in r

    @pytest.mark.unit
    def test_scheduled_at_sent_at_optional(self) -> None:
        """scheduled_at and sent_at default to None and can be left unset."""
        follow_up = FollowUp(
            id=FollowUpId("fu-040"),
            campaign_id=CampaignId("cmp-040"),
            application_id=ApplicationId("app-040"),
            template=FollowUpTemplate.THANK_YOU,
        )
        assert follow_up.scheduled_at is None
        assert follow_up.sent_at is None

    @pytest.mark.unit
    def test_subject_body_defaults(self) -> None:
        """subject and body default to empty strings."""
        follow_up = FollowUp(
            id=FollowUpId("fu-050"),
            campaign_id=CampaignId("cmp-050"),
            application_id=ApplicationId("app-050"),
            template=FollowUpTemplate.CHECK_IN,
        )
        assert follow_up.subject == ""
        assert follow_up.body == ""

