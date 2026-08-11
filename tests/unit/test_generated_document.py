import pytest

from applicant.core.entities.generated_document import (
    DocumentType,
    GeneratedDocument,
    LearnedProvenance,
)
from applicant.core.ids import ApplicationId, CampaignId, GeneratedDocumentId


@pytest.fixture(autouse=True)
def _no_cache():
    pass


@pytest.mark.unit
class TestDocumentType:
    """DocumentType enum members and is_attachment property."""

    def test_members_exist(self):
        assert DocumentType.RESUME == "resume"
        assert DocumentType.COVER_LETTER == "cover_letter"
        assert DocumentType.SCREENING_ANSWER == "screening_answer"
        assert DocumentType.PORTFOLIO == "portfolio"
        assert DocumentType.ATTACHMENT == "attachment"

    def test_is_attachment_exhaustive(self):
        expected = {
            DocumentType.RESUME: False,
            DocumentType.COVER_LETTER: False,
            DocumentType.SCREENING_ANSWER: False,
            DocumentType.PORTFOLIO: True,
            DocumentType.ATTACHMENT: True,
        }
        for member, expected_value in expected.items():
            assert member.is_attachment is expected_value, (
                f"{member!r}.is_attachment expected {expected_value}"
            )

    def test_is_attachment_true_for_portfolio(self):
        assert DocumentType.PORTFOLIO.is_attachment is True

    def test_is_attachment_true_for_attachment(self):
        assert DocumentType.ATTACHMENT.is_attachment is True

    def test_is_attachment_false_for_resume(self):
        assert DocumentType.RESUME.is_attachment is False

    def test_is_attachment_false_for_cover_letter(self):
        assert DocumentType.COVER_LETTER.is_attachment is False

    def test_is_attachment_false_for_screening_answer(self):
        assert DocumentType.SCREENING_ANSWER.is_attachment is False


@pytest.mark.unit
class TestGeneratedDocumentConstruction:
    """GeneratedDocument construction and field defaults."""

    def test_minimal_construction(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-1"),
            campaign_id=CampaignId("camp-1"),
            application_id=ApplicationId("app-1"),
            type=DocumentType.RESUME,
        )
        assert doc.id == "doc-1"
        assert doc.campaign_id == "camp-1"
        assert doc.application_id == "app-1"
        assert doc.type == DocumentType.RESUME
        assert doc.content is None
        assert doc.storage_path is None
        assert doc.approved is False
        assert doc.provenance == ()

    def test_full_construction(self):
        prov = LearnedProvenance(kind="memory", label="Preferred style")
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-2"),
            campaign_id=CampaignId("camp-2"),
            application_id=ApplicationId("app-2"),
            type=DocumentType.COVER_LETTER,
            content="Dear Sir,",
            storage_path="/docs/cover.odt",
            approved=True,
            provenance=(prov,),
        )
        assert doc.id == "doc-2"
        assert doc.campaign_id == "camp-2"
        assert doc.application_id == "app-2"
        assert doc.type == DocumentType.COVER_LETTER
        assert doc.content == "Dear Sir,"
        assert doc.storage_path == "/docs/cover.odt"
        assert doc.approved is True
        assert doc.provenance == (prov,)

    def test_default_approved_is_false(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-3"),
            campaign_id=CampaignId("camp-3"),
            application_id=ApplicationId("app-3"),
            type=DocumentType.RESUME,
        )
        assert doc.approved is False

    def test_content_defaults_to_none(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-4"),
            campaign_id=CampaignId("camp-4"),
            application_id=ApplicationId("app-4"),
            type=DocumentType.RESUME,
        )
        assert doc.content is None

    def test_storage_path_defaults_to_none(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-5"),
            campaign_id=CampaignId("camp-5"),
            application_id=ApplicationId("app-5"),
            type=DocumentType.RESUME,
        )
        assert doc.storage_path is None

    def test_provenance_defaults_to_empty_tuple(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-6"),
            campaign_id=CampaignId("camp-6"),
            application_id=ApplicationId("app-6"),
            type=DocumentType.RESUME,
        )
        assert doc.provenance == ()


@pytest.mark.unit
class TestGeneratedDocumentRepr:
    """repr() contains field values."""

    def test_repr_contains_id(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-7"),
            campaign_id=CampaignId("camp-7"),
            application_id=ApplicationId("app-7"),
            type=DocumentType.PORTFOLIO,
        )
        assert "doc-7" in repr(doc)

    def test_repr_contains_type_value(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-8"),
            campaign_id=CampaignId("camp-8"),
            application_id=ApplicationId("app-8"),
            type=DocumentType.ATTACHMENT,
        )
        r = repr(doc)
        assert "attachment" in r


@pytest.mark.unit
class TestGeneratedDocumentEquality:
    """Equality based on all fields."""

    def test_equal_when_fields_match(self):
        doc1 = GeneratedDocument(
            id=GeneratedDocumentId("doc-9"),
            campaign_id=CampaignId("camp-9"),
            application_id=ApplicationId("app-9"),
            type=DocumentType.RESUME,
        )
        doc2 = GeneratedDocument(
            id=GeneratedDocumentId("doc-9"),
            campaign_id=CampaignId("camp-9"),
            application_id=ApplicationId("app-9"),
            type=DocumentType.RESUME,
        )
        assert doc1 == doc2

    def test_not_equal_when_id_differs(self):
        doc1 = GeneratedDocument(
            id=GeneratedDocumentId("doc-10"),
            campaign_id=CampaignId("camp-10"),
            application_id=ApplicationId("app-10"),
            type=DocumentType.RESUME,
        )
        doc2 = GeneratedDocument(
            id=GeneratedDocumentId("doc-11"),
            campaign_id=CampaignId("camp-10"),
            application_id=ApplicationId("app-10"),
            type=DocumentType.RESUME,
        )
        assert doc1 != doc2

    def test_not_equal_when_type_differs(self):
        doc1 = GeneratedDocument(
            id=GeneratedDocumentId("doc-12"),
            campaign_id=CampaignId("camp-12"),
            application_id=ApplicationId("app-12"),
            type=DocumentType.RESUME,
        )
        doc2 = GeneratedDocument(
            id=GeneratedDocumentId("doc-12"),
            campaign_id=CampaignId("camp-12"),
            application_id=ApplicationId("app-12"),
            type=DocumentType.COVER_LETTER,
        )
        assert doc1 != doc2


@pytest.mark.unit
class TestGeneratedDocumentFrozen:
    """GeneratedDocument is a frozen dataclass."""

    def test_cannot_modify_id(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-13"),
            campaign_id=CampaignId("camp-13"),
            application_id=ApplicationId("app-13"),
            type=DocumentType.RESUME,
        )
        with pytest.raises(AttributeError):
            doc.id = GeneratedDocumentId("doc-14")

    def test_cannot_modify_type(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-15"),
            campaign_id=CampaignId("camp-15"),
            application_id=ApplicationId("app-15"),
            type=DocumentType.RESUME,
        )
        with pytest.raises(AttributeError):
            doc.type = DocumentType.COVER_LETTER

    def test_cannot_modify_approved(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-16"),
            campaign_id=CampaignId("camp-16"),
            application_id=ApplicationId("app-16"),
            type=DocumentType.RESUME,
        )
        with pytest.raises(AttributeError):
            doc.approved = True


@pytest.mark.unit
class TestGeneratedDocumentHashability:
    """GeneratedDocument is hashable — all fields are immutable types."""

    def test_hash(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-17"),
            campaign_id=CampaignId("camp-17"),
            application_id=ApplicationId("app-17"),
            type=DocumentType.RESUME,
        )
        h = hash(doc)
        assert isinstance(h, int)

    def test_usable_in_set(self):
        doc = GeneratedDocument(
            id=GeneratedDocumentId("doc-18"),
            campaign_id=CampaignId("camp-18"),
            application_id=ApplicationId("app-18"),
            type=DocumentType.RESUME,
        )
        s = {doc}
        assert doc in s
