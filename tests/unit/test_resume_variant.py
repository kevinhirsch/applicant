import pytest

from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant, VariantSubmission
from applicant.core.ids import CampaignId, JobPostingId, ResumeVariantId


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Autouse fixture for parallel (xdist) safety."""
    yield


@pytest.mark.unit
class TestResumeFitScoringDefaults:
    """ResumeFitScoring dataclass uses correct defaults."""

    def test_minimal_construction(self):
        variant_id = ResumeVariantId("var-1")
        posting_id = JobPostingId("post-1")
        scoring = ResumeFitScoring(variant_id=variant_id, posting_id=posting_id, coverage=0.85)
        assert scoring.variant_id == variant_id
        assert scoring.posting_id == posting_id
        assert scoring.coverage == 0.85
        assert scoring.missing_terms == ()


@pytest.mark.unit
class TestResumeFitScoringAllFields:
    """ResumeFitScoring accepts all fields."""

    def test_full_construction(self):
        variant_id = ResumeVariantId("var-1")
        posting_id = JobPostingId("post-1")
        scoring = ResumeFitScoring(
            variant_id=variant_id,
            posting_id=posting_id,
            coverage=0.45,
            missing_terms=("python", "aws"),
        )
        assert scoring.variant_id == variant_id
        assert scoring.posting_id == posting_id
        assert scoring.coverage == 0.45
        assert scoring.missing_terms == ("python", "aws")


@pytest.mark.unit
class TestResumeFitScoringFrozen:
    """ResumeFitScoring is a frozen dataclass."""

    def test_cannot_modify_variant_id(self):
        scoring = ResumeFitScoring(variant_id=ResumeVariantId("var-1"), posting_id=JobPostingId("post-1"), coverage=0.5)
        with pytest.raises(AttributeError):
            scoring.variant_id = ResumeVariantId("var-2")

    def test_cannot_modify_posting_id(self):
        scoring = ResumeFitScoring(variant_id=ResumeVariantId("var-1"), posting_id=JobPostingId("post-1"), coverage=0.5)
        with pytest.raises(AttributeError):
            scoring.posting_id = JobPostingId("post-2")

    def test_cannot_modify_coverage(self):
        scoring = ResumeFitScoring(variant_id=ResumeVariantId("var-1"), posting_id=JobPostingId("post-1"), coverage=0.5)
        with pytest.raises(AttributeError):
            scoring.coverage = 0.9

    def test_cannot_modify_missing_terms(self):
        scoring = ResumeFitScoring(variant_id=ResumeVariantId("var-1"), posting_id=JobPostingId("post-1"), coverage=0.5)
        with pytest.raises(AttributeError):
            scoring.missing_terms = ("new",)


@pytest.mark.unit
class TestVariantSubmissionDefaults:
    """VariantSubmission dataclass uses correct defaults."""

    def test_minimal_construction(self):
        posting_id = JobPostingId("post-1")
        submission = VariantSubmission(posting_id=posting_id)
        assert submission.posting_id == posting_id
        assert submission.converted is False


@pytest.mark.unit
class TestVariantSubmissionAllFields:
    """VariantSubmission accepts all fields including optional ones."""

    def test_full_construction(self):
        posting_id = JobPostingId("post-1")
        submission = VariantSubmission(posting_id=posting_id, converted=True)
        assert submission.posting_id == posting_id
        assert submission.converted is True


@pytest.mark.unit
class TestVariantSubmissionFrozen:
    """VariantSubmission is a frozen dataclass."""

    def test_cannot_modify_posting_id(self):
        submission = VariantSubmission(posting_id=JobPostingId("post-1"))
        with pytest.raises(AttributeError):
            submission.posting_id = JobPostingId("post-2")

    def test_cannot_modify_converted(self):
        submission = VariantSubmission(posting_id=JobPostingId("post-1"))
        with pytest.raises(AttributeError):
            submission.converted = True


@pytest.mark.unit
class TestResumeVariantDefaults:
    """ResumeVariant dataclass uses correct defaults."""

    def test_minimal_construction(self):
        variant_id = ResumeVariantId("var-1")
        campaign_id = CampaignId("camp-1")
        variant = ResumeVariant(id=variant_id, campaign_id=campaign_id, storage_path="/tmp/resume.tex")
        assert variant.id == variant_id
        assert variant.campaign_id == campaign_id
        assert variant.storage_path == "/tmp/resume.tex"
        assert variant.parent_id is None
        assert variant.targeted_jd_signature is None
        assert variant.approved is False
        assert variant.fit_scores == {}
        assert variant.submissions == ()


@pytest.mark.unit
class TestResumeVariantAllFields:
    """ResumeVariant accepts all fields including optional ones."""

    def test_full_construction(self):
        variant_id = ResumeVariantId("var-1")
        campaign_id = CampaignId("camp-1")
        parent_id = ResumeVariantId("var-0")
        fit_scoring = ResumeFitScoring(variant_id=variant_id, posting_id=JobPostingId("post-1"), coverage=0.85)
        submission = VariantSubmission(posting_id=JobPostingId("post-1"), converted=True)
        variant = ResumeVariant(
            id=variant_id,
            campaign_id=campaign_id,
            storage_path="/tmp/resume.tex",
            parent_id=parent_id,
            targeted_jd_signature="jd-sig-abc",
            approved=True,
            fit_scores={"post-1": fit_scoring},
            submissions=(submission,),
        )
        assert variant.parent_id == parent_id
        assert variant.targeted_jd_signature == "jd-sig-abc"
        assert variant.approved is True
        assert variant.fit_scores == {"post-1": fit_scoring}
        assert variant.submissions == (submission,)


@pytest.mark.unit
class TestResumeVariantFrozen:
    """ResumeVariant is a frozen dataclass."""

    def test_cannot_modify_id(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        with pytest.raises(AttributeError):
            variant.id = ResumeVariantId("var-2")

    def test_cannot_modify_campaign_id(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        with pytest.raises(AttributeError):
            variant.campaign_id = CampaignId("camp-2")

    def test_cannot_modify_storage_path(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        with pytest.raises(AttributeError):
            variant.storage_path = "/tmp/new.tex"


@pytest.mark.unit
class TestResumeVariantIsRoot:
    """ResumeVariant.is_root property."""

    def test_root_when_parent_id_is_none(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        assert variant.is_root is True

    def test_not_root_when_parent_id_is_set(self):
        variant = ResumeVariant(
            id=ResumeVariantId("var-2"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            parent_id=ResumeVariantId("var-1"),
        )
        assert variant.is_root is False


@pytest.mark.unit
class TestResumeVariantSubmittedPostingId:
    """ResumeVariant.submitted_posting_id property."""

    def test_empty_when_no_submissions(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        assert variant.submitted_posting_id == ()

    def test_returns_posting_ids_newest_first(self):
        submission_1 = VariantSubmission(posting_id=JobPostingId("post-1"), converted=True)
        submission_2 = VariantSubmission(posting_id=JobPostingId("post-2"), converted=False)
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=(submission_1, submission_2),
        )
        assert variant.submitted_posting_id == (JobPostingId("post-1"), JobPostingId("post-2"))


@pytest.mark.unit
class TestResumeVariantConversionRate:
    """ResumeVariant.conversion_rate property."""

    def test_zero_when_no_submissions(self):
        variant = ResumeVariant(id=ResumeVariantId("var-1"), campaign_id=CampaignId("camp-1"), storage_path="/tmp/r.tex")
        assert variant.conversion_rate == 0.0

    def test_one_when_all_converted(self):
        submissions = (
            VariantSubmission(posting_id=JobPostingId("post-1"), converted=True),
            VariantSubmission(posting_id=JobPostingId("post-2"), converted=True),
        )
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=submissions,
        )
        assert variant.conversion_rate == 1.0

    def test_zero_when_none_converted(self):
        submissions = (
            VariantSubmission(posting_id=JobPostingId("post-1"), converted=False),
            VariantSubmission(posting_id=JobPostingId("post-2"), converted=False),
        )
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=submissions,
        )
        assert variant.conversion_rate == 0.0

    def test_mixed_conversions(self):
        submissions = (
            VariantSubmission(posting_id=JobPostingId("post-1"), converted=True),
            VariantSubmission(posting_id=JobPostingId("post-2"), converted=False),
            VariantSubmission(posting_id=JobPostingId("post-3"), converted=True),
            VariantSubmission(posting_id=JobPostingId("post-4"), converted=False),
        )
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=submissions,
        )
        assert variant.conversion_rate == 0.5

    def test_single_submission_converted(self):
        submissions = (
            VariantSubmission(posting_id=JobPostingId("post-1"), converted=True),
        )
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=submissions,
        )
        assert variant.conversion_rate == 1.0

    def test_single_submission_not_converted(self):
        submissions = (
            VariantSubmission(posting_id=JobPostingId("post-1"), converted=False),
        )
        variant = ResumeVariant(
            id=ResumeVariantId("var-1"),
            campaign_id=CampaignId("camp-1"),
            storage_path="/tmp/r.tex",
            submissions=submissions,
        )
        assert variant.conversion_rate == 0.0
