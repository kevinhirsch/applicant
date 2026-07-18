"""Unit tests for in-memory storage adapter repos.

Covers _CampaignRepo, _AttributeRepo, _PostingRepo, and _ApplicationRepo
from applicant.adapters.storage.in_memory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, patch

import pytest

from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
)
from applicant.core.state_machine import ApplicationState
from applicant.adapters.storage.in_memory import (
    _ApplicationRepo,
    _AttributeRepo,
    _CampaignRepo,
    _PostingRepo,
)


# -- autouse fixture for safe xdist parallel execution ----------------------


@pytest.fixture(autouse=True)
def _reset_repo_state() -> None:
    """Ensure a fresh dict on every test method, regardless of test order."""
    # Each _*Repo class is re-instantiated per test, so there's no
    # cross-test state to clear.  This fixture exists as a safety net for
    # any future module-level globals.
    pass


# -- helpers ----------------------------------------------------------------


@pytest.fixture
def cid() -> CampaignId:
    return CampaignId("campaign-1")


@pytest.fixture
def cid2() -> CampaignId:
    return CampaignId("campaign-2")


@pytest.fixture
def aid() -> AttributeId:
    return AttributeId("attr-1")


@pytest.fixture
def pid() -> JobPostingId:
    return JobPostingId("posting-1")


@pytest.fixture
def appid() -> ApplicationId:
    return ApplicationId("app-1")


@pytest.fixture
def campaign(cid: CampaignId) -> Campaign:
    return Campaign(id=cid, name="Test Campaign")


@pytest.fixture
def attribute(cid: CampaignId, aid: AttributeId) -> Attribute:
    return Attribute(id=aid, campaign_id=cid, name="degree", value="MSc")


@pytest.fixture
def posting(cid: CampaignId, pid: JobPostingId) -> JobPosting:
    return JobPosting(
        id=pid,
        campaign_id=cid,
        title="Software Engineer",
        company="ACME Corp",
        source_url="https://example.com/job/1",
    )


@pytest.fixture
def application(cid: CampaignId, pid: JobPostingId, appid: ApplicationId) -> Application:
    return Application(id=appid, campaign_id=cid, posting_id=pid)


# ===========================================================================
# _CampaignRepo
# ===========================================================================


@pytest.mark.unit
class TestCampaignRepo:
    """_CampaignRepo: add / get / list / delete."""

    def test_add_and_get(self, campaign: Campaign) -> None:
        repo = _CampaignRepo()
        repo.add(campaign)
        got = repo.get(campaign.id)
        assert got is campaign, "add/get should return same object"

    def test_get_returns_none_for_missing(self) -> None:
        repo = _CampaignRepo()
        assert repo.get(CampaignId("nonexistent")) is None

    def test_list_returns_empty(self) -> None:
        repo = _CampaignRepo()
        assert repo.list() == []

    def test_list_returns_all(self, cid: CampaignId) -> None:
        repo = _CampaignRepo()
        c1 = Campaign(id=cid, name="C1")
        c2 = Campaign(id=CampaignId("campaign-2"), name="C2")
        repo.add(c1)
        repo.add(c2)
        result = repo.list()
        assert len(result) == 2
        assert c1 in result
        assert c2 in result

    def test_delete_removes_and_returns_1(self, campaign: Campaign) -> None:
        repo = _CampaignRepo()
        repo.add(campaign)
        deleted = repo.delete(campaign.id)
        assert deleted == 1
        assert repo.get(campaign.id) is None

    def test_delete_missing_returns_0(self) -> None:
        repo = _CampaignRepo()
        assert repo.delete(CampaignId("ghost")) == 0

    def test_delete_then_list_empty(self, campaign: Campaign) -> None:
        repo = _CampaignRepo()
        repo.add(campaign)
        repo.delete(campaign.id)
        assert repo.list() == []

    def test_add_replaces_existing_id(self, cid: CampaignId) -> None:
        repo = _CampaignRepo()
        c1 = Campaign(id=cid, name="Original")
        c2 = Campaign(id=cid, name="Replacement")
        repo.add(c1)
        repo.add(c2)
        assert repo.get(cid).name == "Replacement"
        assert len(repo.list()) == 1


# ===========================================================================
# _AttributeRepo
# ===========================================================================


@pytest.mark.unit
class TestAttributeRepo:
    """_AttributeRepo: add / get / list_for_campaign / delete / delete_for_campaign / prune_recorded_before."""

    def test_add_and_get(self, attribute: Attribute) -> None:
        repo = _AttributeRepo()
        repo.add(attribute)
        got = repo.get(attribute.id)
        assert got is attribute

    def test_add_records_timestamp(self, attribute: Attribute) -> None:
        repo = _AttributeRepo()
        before = datetime.now(UTC)
        repo.add(attribute, recorded_at=before)
        assert repo._ts[str(attribute.id)] == before

    def test_add_default_timestamp(self, attribute: Attribute) -> None:
        repo = _AttributeRepo()
        before = datetime.now(UTC)
        repo.add(attribute)
        after = datetime.now(UTC)
        ts = repo._ts[str(attribute.id)]
        assert before <= ts <= after

    def test_get_returns_none_for_missing(self) -> None:
        repo = _AttributeRepo()
        assert repo.get(AttributeId("ghost")) is None

    def test_list_for_campaign(self, cid: CampaignId, cid2: CampaignId) -> None:
        repo = _AttributeRepo()
        a1 = Attribute(id=AttributeId("a1"), campaign_id=cid, name="n", value="v")
        a2 = Attribute(id=AttributeId("a2"), campaign_id=cid, name="n2", value="v2")
        a3 = Attribute(id=AttributeId("a3"), campaign_id=cid2, name="n3", value="v3")
        repo.add(a1)
        repo.add(a2)
        repo.add(a3)
        result = repo.list_for_campaign(cid)
        assert len(result) == 2
        assert a1 in result
        assert a2 in result
        assert a3 not in result

    def test_list_for_campaign_empty(self, cid: CampaignId) -> None:
        repo = _AttributeRepo()
        assert repo.list_for_campaign(cid) == []

    def test_delete_removes_attribute(self, attribute: Attribute, aid: AttributeId) -> None:
        repo = _AttributeRepo()
        repo.add(attribute)
        repo.delete(aid)
        assert repo.get(aid) is None

    def test_delete_removes_timestamp(self, attribute: Attribute, aid: AttributeId) -> None:
        repo = _AttributeRepo()
        repo.add(attribute)
        repo.delete(aid)
        assert aid not in repo._ts

    def test_delete_missing_is_noop(self) -> None:
        repo = _AttributeRepo()
        repo.delete(AttributeId("ghost"))  # should not raise

    def test_delete_for_campaign(self, cid: CampaignId, cid2: CampaignId) -> None:
        repo = _AttributeRepo()
        a1 = Attribute(id=AttributeId("a1"), campaign_id=cid, name="n", value="v")
        a2 = Attribute(id=AttributeId("a2"), campaign_id=cid2, name="n2", value="v2")
        repo.add(a1)
        repo.add(a2)
        count = repo.delete_for_campaign(cid)
        assert count == 1
        assert repo.get(a1.id) is None
        assert repo.get(a2.id) is not None

    def test_delete_for_campaign_removes_timestamps(self, cid: CampaignId) -> None:
        repo = _AttributeRepo()
        a1 = Attribute(id=AttributeId("a1"), campaign_id=cid, name="n", value="v")
        repo.add(a1)
        repo.delete_for_campaign(cid)
        assert AttributeId("a1") not in repo._ts

    def test_delete_for_campaign_no_match_returns_0(self, cid: CampaignId) -> None:
        repo = _AttributeRepo()
        assert repo.delete_for_campaign(cid) == 0

    def test_prune_recorded_before(self, attribute: Attribute) -> None:
        repo = _AttributeRepo()
        repo.add(attribute, recorded_at=datetime(2024, 1, 1, tzinfo=UTC))
        count = repo.prune_recorded_before(datetime(2024, 6, 1, tzinfo=UTC))
        assert count == 1
        assert repo.get(attribute.id) is None

    def test_prune_keeps_recent(self, attribute: Attribute) -> None:
        repo = _AttributeRepo()
        repo.add(attribute, recorded_at=datetime(2024, 12, 1, tzinfo=UTC))
        count = repo.prune_recorded_before(datetime(2024, 6, 1, tzinfo=UTC))
        assert count == 0
        assert repo.get(attribute.id) is not None

    def test_prune_partial_removal(self, cid: CampaignId) -> None:
        repo = _AttributeRepo()
        a1 = Attribute(id=AttributeId("a1"), campaign_id=cid, name="n", value="v")
        a2 = Attribute(id=AttributeId("a2"), campaign_id=cid, name="n2", value="v2")
        repo.add(a1, recorded_at=datetime(2024, 1, 1, tzinfo=UTC))
        repo.add(a2, recorded_at=datetime(2025, 1, 1, tzinfo=UTC))
        count = repo.prune_recorded_before(datetime(2024, 6, 1, tzinfo=UTC))
        assert count == 1
        assert repo.get(a1.id) is None
        assert repo.get(a2.id) is not None

    def test_prune_empty_repo(self) -> None:
        repo = _AttributeRepo()
        assert repo.prune_recorded_before(datetime.now(UTC)) == 0


# ===========================================================================
# _PostingRepo
# ===========================================================================


@pytest.mark.unit
class TestPostingRepo:
    """_PostingRepo: add / get / list_for_campaign / list_unscored_for_campaign / count_for_campaign / delete_for_campaign."""

    def test_add_and_get(self, posting: JobPosting) -> None:
        repo = _PostingRepo()
        repo.add(posting)
        assert repo.get(posting.id) is posting

    def test_get_returns_none_for_missing(self) -> None:
        repo = _PostingRepo()
        assert repo.get(JobPostingId("ghost")) is None

    def test_list_for_campaign(self, cid: CampaignId, cid2: CampaignId, pid: JobPostingId) -> None:
        repo = _PostingRepo()
        p1 = JobPosting(id=pid, campaign_id=cid, title="T1", company="C1", source_url="https://e.com/1")
        p2 = JobPosting(id=JobPostingId("p2"), campaign_id=cid, title="T2", company="C2", source_url="https://e.com/2")
        p3 = JobPosting(id=JobPostingId("p3"), campaign_id=cid2, title="T3", company="C3", source_url="https://e.com/3")
        repo.add(p1)
        repo.add(p2)
        repo.add(p3)
        result = repo.list_for_campaign(cid)
        assert len(result) == 2
        assert p1 in result
        assert p2 in result
        assert p3 not in result

    def test_list_for_campaign_sorted(self, cid: CampaignId) -> None:
        repo = _PostingRepo()
        p_b = JobPosting(id=JobPostingId("p-b"), campaign_id=cid, title="B", company="C", source_url="https://e.com/b")
        p_a = JobPosting(id=JobPostingId("p-a"), campaign_id=cid, title="A", company="C", source_url="https://e.com/a")
        repo.add(p_b)
        repo.add(p_a)
        result = repo.list_for_campaign(cid)
        assert [p.id for p in result] == [JobPostingId("p-a"), JobPostingId("p-b")]

    def test_list_unscored_for_campaign(self, cid: CampaignId) -> None:
        repo = _PostingRepo()
        p1 = JobPosting(id=JobPostingId("p1"), campaign_id=cid, title="T1", company="C", source_url="https://e.com/1")
        p2 = JobPosting(id=JobPostingId("p2"), campaign_id=cid, title="T2", company="C", source_url="https://e.com/2", viability_score=0.5)
        repo.add(p1)
        repo.add(p2)
        result = repo.list_unscored_for_campaign(cid)
        assert result == [p1]

    def test_list_unscored_empty_when_all_scored(self, cid: CampaignId) -> None:
        repo = _PostingRepo()
        p1 = JobPosting(id=JobPostingId("p1"), campaign_id=cid, title="T1", company="C", source_url="https://e.com/1", viability_score=0.9)
        repo.add(p1)
        assert repo.list_unscored_for_campaign(cid) == []

    def test_count_for_campaign(self, cid: CampaignId, cid2: CampaignId) -> None:
        repo = _PostingRepo()
        p1 = JobPosting(id=JobPostingId("p1"), campaign_id=cid, title="T", company="C", source_url="https://e.com/1")
        p2 = JobPosting(id=JobPostingId("p2"), campaign_id=cid, title="T", company="C", source_url="https://e.com/2")
        p3 = JobPosting(id=JobPostingId("p3"), campaign_id=cid2, title="T", company="C", source_url="https://e.com/3")
        repo.add(p1)
        repo.add(p2)
        repo.add(p3)
        assert repo.count_for_campaign(cid) == 2
        assert repo.count_for_campaign(cid2) == 1

    def test_count_for_campaign_empty(self, cid: CampaignId) -> None:
        repo = _PostingRepo()
        assert repo.count_for_campaign(cid) == 0

    def test_delete_for_campaign(self, cid: CampaignId, cid2: CampaignId) -> None:
        repo = _PostingRepo()
        p1 = JobPosting(id=JobPostingId("p1"), campaign_id=cid, title="T", company="C", source_url="https://e.com/1")
        p2 = JobPosting(id=JobPostingId("p2"), campaign_id=cid2, title="T", company="C", source_url="https://e.com/2")
        repo.add(p1)
        repo.add(p2)
        count = repo.delete_for_campaign(cid)
        assert count == 1
        assert repo.get(p1.id) is None
        assert repo.get(p2.id) is not None

    def test_delete_for_campaign_no_match_returns_0(self, cid: CampaignId) -> None:
        repo = _PostingRepo()
        assert repo.delete_for_campaign(cid) == 0


# ===========================================================================
# _ApplicationRepo
# ===========================================================================


@pytest.mark.unit
class TestApplicationRepo:
    """_ApplicationRepo: add / get / update / list_for_campaign / get_by_posting / list_by_status / ids_for_campaign / delete_for_campaign."""

    def test_add_and_get(self, application: Application) -> None:
        repo = _ApplicationRepo()
        repo.add(application)
        assert repo.get(application.id) is application

    def test_get_returns_none_for_missing(self) -> None:
        repo = _ApplicationRepo()
        assert repo.get(ApplicationId("ghost")) is None

    def test_update_replaces_entity(self, application: Application, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        repo.add(application)
        updated = Application(id=application.id, campaign_id=cid, posting_id=JobPostingId("p-new"))
        repo.update(updated)
        assert repo.get(application.id).posting_id == JobPostingId("p-new")

    def test_update_no_status_change_does_not_emit_event(self, application: Application) -> None:
        repo = _ApplicationRepo()
        repo.add(application)
        same = Application(
            id=application.id,
            campaign_id=application.campaign_id,
            posting_id=application.posting_id,
            status=ApplicationState.DISCOVERED,
        )
        with patch("applicant.adapters.storage.in_memory.event_bus.emit") as mock_emit:
            repo.update(same)
        mock_emit.assert_not_called()

    def test_update_status_change_emits_application_state_changed(self, application: Application) -> None:
        repo = _ApplicationRepo()
        repo.add(application)
        changed = Application(
            id=application.id,
            campaign_id=application.campaign_id,
            posting_id=application.posting_id,
            status=ApplicationState.SCORED,
        )
        with patch("applicant.adapters.storage.in_memory.event_bus.emit") as mock_emit:
            repo.update(changed)
        mock_emit.assert_called_once()
        args, _ = mock_emit.call_args
        event = args[0]
        assert event.application_id == application.id
        assert event.from_state == ApplicationState.DISCOVERED.value
        assert event.to_state == ApplicationState.SCORED.value

    def test_update_status_change_multiple_times(self, application: Application) -> None:
        repo = _ApplicationRepo()
        repo.add(application)
        s1 = Application(id=application.id, campaign_id=application.campaign_id, posting_id=application.posting_id, status=ApplicationState.SCORED)
        s2 = Application(id=application.id, campaign_id=application.campaign_id, posting_id=application.posting_id, status=ApplicationState.APPROVED)
        with patch("applicant.adapters.storage.in_memory.event_bus.emit") as mock_emit:
            repo.update(s1)
            repo.update(s2)
        assert mock_emit.call_count == 2

    def test_update_for_new_entity_no_old_to_compare(self, cid: CampaignId, pid: JobPostingId, appid: ApplicationId) -> None:
        repo = _ApplicationRepo()
        app = Application(id=appid, campaign_id=cid, posting_id=pid, status=ApplicationState.SCORED)
        with patch("applicant.adapters.storage.in_memory.event_bus.emit") as mock_emit:
            repo.update(app)
        mock_emit.assert_not_called()

    def test_list_for_campaign(self, cid: CampaignId, cid2: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid)
        a2 = Application(id=ApplicationId("a2"), campaign_id=cid, posting_id=pid)
        a3 = Application(id=ApplicationId("a3"), campaign_id=cid2, posting_id=pid)
        repo.add(a1)
        repo.add(a2)
        repo.add(a3)
        result = repo.list_for_campaign(cid)
        assert len(result) == 2
        assert a1 in result
        assert a2 in result
        assert a3 not in result

    def test_list_for_campaign_empty(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.list_for_campaign(cid) == []

    def test_get_by_posting(self, cid: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid)
        repo.add(a1)
        result = repo.get_by_posting(cid, pid)
        assert result is a1

    def test_get_by_posting_wrong_campaign(self, cid: CampaignId, cid2: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid)
        repo.add(a1)
        assert repo.get_by_posting(cid2, pid) is None

    def test_get_by_posting_no_match(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.get_by_posting(cid, JobPostingId("ghost")) is None

    def test_list_by_status(self, cid: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid, status=ApplicationState.DISCOVERED)
        a2 = Application(id=ApplicationId("a2"), campaign_id=cid, posting_id=pid, status=ApplicationState.SCORED)
        a3 = Application(id=ApplicationId("a3"), campaign_id=cid, posting_id=pid, status=ApplicationState.DISCOVERED)
        repo.add(a1)
        repo.add(a2)
        repo.add(a3)
        result = repo.list_by_status(cid, (ApplicationState.DISCOVERED,))
        assert len(result) == 2
        assert a1 in result
        assert a3 in result
        assert a2 not in result

    def test_list_by_status_empty_tuple_returns_empty(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.list_by_status(cid, ()) == []

    def test_list_by_status_multiple_statuses(self, cid: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid, status=ApplicationState.DISCOVERED)
        a2 = Application(id=ApplicationId("a2"), campaign_id=cid, posting_id=pid, status=ApplicationState.SCORED)
        a3 = Application(id=ApplicationId("a3"), campaign_id=cid, posting_id=pid, status=ApplicationState.APPROVED)
        repo.add(a1)
        repo.add(a2)
        repo.add(a3)
        result = repo.list_by_status(cid, (ApplicationState.DISCOVERED, ApplicationState.APPROVED))
        assert len(result) == 2
        assert a1 in result
        assert a3 in result
        assert a2 not in result

    def test_list_by_status_no_match(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.list_by_status(cid, (ApplicationState.REJECTED,)) == []

    def test_ids_for_campaign(self, cid: CampaignId, cid2: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid)
        a2 = Application(id=ApplicationId("a2"), campaign_id=cid, posting_id=pid)
        a3 = Application(id=ApplicationId("a3"), campaign_id=cid2, posting_id=pid)
        repo.add(a1)
        repo.add(a2)
        repo.add(a3)
        result = repo.ids_for_campaign(cid)
        assert result == {"a1", "a2"}

    def test_ids_for_campaign_empty(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.ids_for_campaign(cid) == set()

    def test_delete_for_campaign(self, cid: CampaignId, cid2: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a1 = Application(id=ApplicationId("a1"), campaign_id=cid, posting_id=pid)
        a2 = Application(id=ApplicationId("a2"), campaign_id=cid2, posting_id=pid)
        repo.add(a1)
        repo.add(a2)
        count = repo.delete_for_campaign(cid)
        assert count == 1
        assert repo.get(a1.id) is None
        assert repo.get(a2.id) is not None

    def test_delete_for_campaign_no_match_returns_0(self, cid: CampaignId) -> None:
        repo = _ApplicationRepo()
        assert repo.delete_for_campaign(cid) == 0

    def test_list_for_campaign_sorted(self, cid: CampaignId, pid: JobPostingId) -> None:
        repo = _ApplicationRepo()
        a_b = Application(id=ApplicationId("app-b"), campaign_id=cid, posting_id=pid)
        a_a = Application(id=ApplicationId("app-a"), campaign_id=cid, posting_id=pid)
        repo.add(a_b)
        repo.add(a_a)
        result = repo.list_for_campaign(cid)
        assert [a.id for a in result] == [ApplicationId("app-a"), ApplicationId("app-b")]
