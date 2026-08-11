import pytest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from applicant.core.entities.portfolio_attachment import (
    AttachmentType,
    PortfolioAttachment,
)
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    PortfolioAttachmentId,
)


@pytest.fixture(autouse=True)
def _clear_state():
    """Clear any module-level state for parallel xdist safety.

    PortfolioAttachment has no module-level caches or mutable state,
    but this fixture ensures safety when running with pytest-xdist.
    """
    # PortfolioAttachment uses no lru_cache or globals; this is a no-op guard.
    yield


class TestAttachmentType:
    """Tests for the AttachmentType enum."""

    def test_members(self):
        assert AttachmentType.PORTFOLIO.value == "portfolio"
        assert AttachmentType.WRITING_SAMPLE.value == "writing_sample"
        assert AttachmentType.CERTIFICATION.value == "certification"
        assert AttachmentType.TRANSCRIPT.value == "transcript"
        assert AttachmentType.RECOMMENDATION.value == "recommendation"
        assert AttachmentType.OTHER.value == "other"

    def test_enum_inherits_str(self):
        """AttachmentType inherits from str, so values are directly comparable."""
        assert isinstance(AttachmentType.PORTFOLIO, str)
        assert AttachmentType.PORTFOLIO == "portfolio"
        assert AttachmentType.WRITING_SAMPLE == "writing_sample"
        assert AttachmentType.CERTIFICATION == "certification"
        assert AttachmentType.TRANSCRIPT == "transcript"
        assert AttachmentType.RECOMMENDATION == "recommendation"
        assert AttachmentType.OTHER == "other"


class TestPortfolioAttachment:
    """Tests for the PortfolioAttachment frozen dataclass."""

    def test_defaults(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-001"),
            campaign_id=CampaignId("camp-001"),
        )
        assert attach.id == "att-001"
        assert attach.campaign_id == "camp-001"
        assert attach.application_id is None
        assert attach.attachment_type == AttachmentType.OTHER
        assert attach.file_name == ""
        assert attach.storage_path == ""
        assert attach.display_name == ""
        assert attach.description == ""
        assert attach.metadata == {}
        assert isinstance(attach.created_at, datetime)

    def test_all_fields(self):
        now = datetime.now(UTC)
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-002"),
            campaign_id=CampaignId("camp-002"),
            application_id=ApplicationId("app-002"),
            attachment_type=AttachmentType.CERTIFICATION,
            file_name="cert.pdf",
            storage_path="/uploads/cert.pdf",
            display_name="My Certificate",
            description="An important certification",
            metadata={"size": 1024},
            created_at=now,
        )
        assert attach.id == "att-002"
        assert attach.campaign_id == "camp-002"
        assert attach.application_id == "app-002"
        assert attach.attachment_type == AttachmentType.CERTIFICATION
        assert attach.file_name == "cert.pdf"
        assert attach.storage_path == "/uploads/cert.pdf"
        assert attach.display_name == "My Certificate"
        assert attach.description == "An important certification"
        assert attach.metadata == {"size": 1024}
        assert attach.created_at == now

    def test_none_application_id(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-003"),
            campaign_id=CampaignId("camp-003"),
            application_id=None,
        )
        assert attach.application_id is None

    def test_frozen_immutable(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-004"),
            campaign_id=CampaignId("camp-004"),
        )
        with pytest.raises(FrozenInstanceError):
            attach.file_name = "should-not-work"

    def test_frozen_immutable_all_fields(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-005"),
            campaign_id=CampaignId("camp-005"),
            application_id=ApplicationId("app-005"),
            attachment_type=AttachmentType.TRANSCRIPT,
            file_name="transcript.pdf",
        )
        with pytest.raises(FrozenInstanceError):
            attach.id = PortfolioAttachmentId("changed")
        with pytest.raises(FrozenInstanceError):
            attach.campaign_id = CampaignId("changed")
        with pytest.raises(FrozenInstanceError):
            attach.application_id = ApplicationId("changed")
        with pytest.raises(FrozenInstanceError):
            attach.attachment_type = AttachmentType.PORTFOLIO
        with pytest.raises(FrozenInstanceError):
            attach.file_name = "changed"
        with pytest.raises(FrozenInstanceError):
            attach.storage_path = "changed"
        with pytest.raises(FrozenInstanceError):
            attach.display_name = "changed"
        with pytest.raises(FrozenInstanceError):
            attach.description = "changed"
        with pytest.raises(FrozenInstanceError):
            attach.metadata = {"new": True}
        with pytest.raises(FrozenInstanceError):
            attach.created_at = datetime.now(UTC)

    def test_created_at_defaults_to_utc(self):
        before = datetime.now(UTC)
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-006"),
            campaign_id=CampaignId("camp-006"),
        )
        after = datetime.now(UTC)
        assert before <= attach.created_at <= after
        assert attach.created_at.tzinfo is not None

    def test_created_at_utc_tz(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-007"),
            campaign_id=CampaignId("camp-007"),
        )
        assert attach.created_at.tzinfo == UTC

    def test_metadata_default_is_empty_dict(self):
        attach1 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-008"),
            campaign_id=CampaignId("camp-008"),
        )
        attach2 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-009"),
            campaign_id=CampaignId("camp-009"),
        )
        # Each instance should have its own dict, not share a reference
        assert attach1.metadata is not attach2.metadata
        attach1.metadata["key"] = "val"
        assert "key" not in attach2.metadata

    def test_equality(self):
        now = datetime.now(UTC)
        attach1 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-010"),
            campaign_id=CampaignId("camp-010"),
            created_at=now,
        )
        attach2 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-010"),
            campaign_id=CampaignId("camp-010"),
            created_at=now,
        )
        assert attach1 == attach2

    def test_inequality(self):
        now = datetime.now(UTC)
        attach1 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-011"),
            campaign_id=CampaignId("camp-011"),
            created_at=now,
        )
        attach2 = PortfolioAttachment(
            id=PortfolioAttachmentId("att-012"),
            campaign_id=CampaignId("camp-012"),
            created_at=now,
        )
        assert attach1 != attach2

    def test_repr(self):
        attach = PortfolioAttachment(
            id=PortfolioAttachmentId("att-013"),
            campaign_id=CampaignId("camp-013"),
        )
        rep = repr(attach)
        assert "PortfolioAttachment" in rep
        assert "att-013" in rep
        assert "camp-013" in rep
