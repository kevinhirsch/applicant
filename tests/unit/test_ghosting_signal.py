from datetime import UTC, datetime

import pytest

from applicant.core.entities.ghosting_signal import GhostingSignal
from applicant.core.ids import ApplicationId, CampaignId


class TestGhostingSignalDefaults:
    """Tests for GhostingSignal default field values."""

    def test_minimal_construction(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        assert sig.campaign_id == CampaignId("camp-1")
        assert sig.application_id == ApplicationId("app-1")

    def test_default_sla_days(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        assert sig.sla_days == 14

    def test_default_submission_age_days(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        assert sig.submission_age_days == 0

    def test_default_detail_is_empty_dict(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        assert sig.detail == {}
        assert isinstance(sig.detail, dict)

    def test_default_detected_at_is_aware_datetime(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        assert isinstance(sig.detected_at, datetime)
        assert sig.detected_at.tzinfo is not None


class TestGhostingSignalCustomValues:
    """Tests for GhostingSignal with custom field values."""

    def test_custom_sla_days(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
            sla_days=7,
        )
        assert sig.sla_days == 7

    def test_custom_submission_age_days(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
            submission_age_days=30,
        )
        assert sig.submission_age_days == 30

    def test_custom_detail(self):
        detail = {"reason": "no_response", "days": 5}
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
            detail=detail,
        )
        assert sig.detail == detail

    def test_custom_detected_at(self):
        dt = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
            detected_at=dt,
        )
        assert sig.detected_at == dt


class TestGhostingSignalFrozen:
    """Tests for GhostingSignal immutability."""

    def test_cannot_modify_campaign_id(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        with pytest.raises(AttributeError):
            sig.campaign_id = CampaignId("camp-2")

    def test_cannot_modify_sla_days(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        with pytest.raises(AttributeError):
            sig.sla_days = 7

    def test_cannot_modify_detail(self):
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
        )
        with pytest.raises(AttributeError):
            sig.detail = {"key": "value"}

    def test_all_fields_custom(self):
        dt = datetime(2025, 6, 1, 9, 30, 0, tzinfo=UTC)
        sig = GhostingSignal(
            campaign_id=CampaignId("camp-2"),
            application_id=ApplicationId("app-2"),
            sla_days=21,
            submission_age_days=10,
            detected_at=dt,
            detail={"note": "custom"},
        )
        assert sig.campaign_id == CampaignId("camp-2")
        assert sig.application_id == ApplicationId("app-2")
        assert sig.sla_days == 21
        assert sig.submission_age_days == 10
        assert sig.detected_at == dt
        assert sig.detail == {"note": "custom"}
