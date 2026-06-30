"""Tests for cross-entity comparison engine (#297)."""

from __future__ import annotations

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.compare_service import CompareService
from applicant.core.entities.application import Application
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId
from applicant.core.state_machine import ApplicationState


def _make_app(cid: str, aid: str, status: ApplicationState = ApplicationState.APPROVED) -> Application:
    return Application(
        id=ApplicationId(aid),
        campaign_id=CampaignId(cid),
        posting_id=JobPostingId(f"posting-{aid}"),
        status=status,
    )


def _make_posting(pid: str, title: str = "Engineer", company: str = "Acme", location: str = "Remote") -> JobPosting:
    return JobPosting(
        id=JobPostingId(pid),
        campaign_id=CampaignId("c-1"),
        title=title,
        company=company,
        source_url="https://example.com/job",
        location=location,
    )


class TestCompareApplications:
    def test_compare_two_apps(self):
        storage = InMemoryStorage()
        storage.applications.add(_make_app("c-1", "a-1"))
        storage.applications.add(_make_app("c-1", "a-2"))
        svc = CompareService(storage)
        result = svc.compare_applications(["a-1", "a-2"])
        assert len(result.entity_ids) == 2
        assert len(result.dimensions) >= 1

    def test_compare_less_than_two_returns_summary(self):
        storage = InMemoryStorage()
        storage.applications.add(_make_app("c-1", "a-1"))
        svc = CompareService(storage)
        result = svc.compare_applications(["a-1"])
        assert "Need at least 2" in (result.summary or "")

    def test_dimensions_include_status(self):
        storage = InMemoryStorage()
        storage.applications.add(_make_app("c-1", "a-1"))
        storage.applications.add(_make_app("c-1", "a-2"))
        svc = CompareService(storage)
        result = svc.compare_applications(["a-1", "a-2"])
        keys = [d.key for d in result.dimensions]
        assert "status" in keys

    def test_compare_status_diff(self):
        storage = InMemoryStorage()
        a1 = _make_app("c-1", "a-1", status=ApplicationState.APPROVED)
        a2 = _make_app("c-1", "a-2", status=ApplicationState.FINISHED_BY_ENGINE)
        storage.applications.add(a1)
        storage.applications.add(a2)
        svc = CompareService(storage)
        result = svc.compare_applications(["a-1", "a-2"])
        status_dim = [d for d in result.dimensions if d.key == "status"][0]
        assert len(set(status_dim.values.values())) == 2  # two different statuses


class TestComparePostings:
    def test_compare_two_postings(self):
        storage = InMemoryStorage()
        storage.postings.add(_make_posting("p-1", title="Engineer", company="Acme"))
        storage.postings.add(_make_posting("p-2", title="Manager", company="Beta"))
        svc = CompareService(storage)
        result = svc.compare_postings(["p-1", "p-2"])
        assert len(result.entity_ids) == 2

    def test_dimensions_include_title_company_location(self):
        storage = InMemoryStorage()
        storage.postings.add(_make_posting("p-1", title="Engineer", company="Acme", location="NYC"))
        storage.postings.add(_make_posting("p-2", title="Manager", company="Beta", location="SF"))
        svc = CompareService(storage)
        result = svc.compare_postings(["p-1", "p-2"])
        keys = [d.key for d in result.dimensions]
        assert "title" in keys
        assert "company" in keys
        assert "location" in keys

    def test_compare_empty_postings(self):
        storage = InMemoryStorage()
        svc = CompareService(storage)
        result = svc.compare_postings([])
        assert result.summary is not None
