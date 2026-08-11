"""Unit tests for applicant.core.entities.job_posting."""

import dataclasses
import pytest

from applicant.core.entities.job_posting import (
    USER_ADDED_SOURCE_KEY,
    JobPosting,
)
from applicant.core.ids import CampaignId, JobPostingId


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Ensure no lru_cache or module-level state leaks between parallel workers."""
    yield


class TestJobPosting:
    @pytest.mark.unit
    def test_create_minimal(self):
        posting = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        assert posting.id == "jp-1"
        assert posting.campaign_id == "camp-1"
        assert posting.title == "Engineer"
        assert posting.company == "Acme"
        assert posting.source_url == "https://acme.com/jobs/1"
        assert posting.location is None
        assert posting.work_mode is None
        assert posting.salary is None
        assert posting.description == ""
        assert posting.source_key is None
        assert posting.easy_apply is False
        assert posting.viability_score is None
        assert posting.rationale == {}

    @pytest.mark.unit
    def test_create_all_fields(self):
        posting = JobPosting(
            id=JobPostingId("jp-2"),
            campaign_id=CampaignId("camp-2"),
            title="Senior Dev",
            company="Globex",
            source_url="https://globex.com/jobs/2",
            location="Remote",
            work_mode="remote",
            salary="$120k",
            description="Build cool stuff.",
            source_key="indeed",
            easy_apply=True,
            viability_score=0.85,
            rationale={"reason": "strong match"},
        )
        assert posting.location == "Remote"
        assert posting.work_mode == "remote"
        assert posting.salary == "$120k"
        assert posting.description == "Build cool stuff."
        assert posting.source_key == "indeed"
        assert posting.easy_apply is True
        assert posting.viability_score == 0.85
        assert posting.rationale == {"reason": "strong match"}

    @pytest.mark.unit
    def test_equality_same_values(self):
        a = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        b = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        assert a == b

    @pytest.mark.unit
    def test_inequality_different_values(self):
        a = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        b = JobPosting(
            id=JobPostingId("jp-2"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        assert a != b

    @pytest.mark.unit
    def test_not_hashable(self):
        posting = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        # frozen dataclass with a mutable dict field is NOT hashable
        with pytest.raises(TypeError, match="unhashable"):
            hash(posting)

    @pytest.mark.unit
    def test_frozen_cannot_change_fields(self):
        posting = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            posting.title = "Manager"

    @pytest.mark.unit
    def test_rationale_is_mutable_dict(self):
        posting = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        # rationale is a dict with default_factory=dict, mutable inside frozen instance
        posting.rationale["key"] = "value"
        assert posting.rationale == {"key": "value"}

    @pytest.mark.unit
    def test_rationale_default_is_not_shared(self):
        a = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        b = JobPosting(
            id=JobPostingId("jp-2"),
            campaign_id=CampaignId("camp-1"),
            title="Designer",
            company="Acme",
            source_url="https://acme.com/jobs/2",
        )
        a.rationale["x"] = 1
        assert b.rationale == {}

    @pytest.mark.unit
    def test_user_added_source_key_constant(self):
        assert USER_ADDED_SOURCE_KEY == "added-by-you"

    @pytest.mark.unit
    def test_repr_contains_class_name(self):
        posting = JobPosting(
            id=JobPostingId("jp-1"),
            campaign_id=CampaignId("camp-1"),
            title="Engineer",
            company="Acme",
            source_url="https://acme.com/jobs/1",
        )
        assert "JobPosting" in repr(posting)
