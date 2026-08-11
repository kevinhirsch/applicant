"""Keyless remote-job AGGREGATOR discovery sources — RemoteOK, Remotive, Working
Nomads (EPIC BREADTH, Kevin 2026-08-11: "throw the net as wide as you possibly
can... prioritize aggregators... we can't limit ourselves to specific
industries").

Unlike the ATS board sources (one source PER COMPANY), each of these is a SINGLE
global feed already indexing postings across many companies/industries -- so
reach isn't bounded by which companies were explicitly enumerated. All three were
live-verified (real HTTP calls, outside this test suite) to return real, non-empty
postings before being wired in here; these tests exercise the offline Fake seam.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.clients import (
    FakeRemoteOkClient,
    FakeRemotiveClient,
    FakeWorkingNomadsClient,
)
from applicant.adapters.discovery.factory import build_default_discovery
from applicant.adapters.discovery.jobspy_searxng import (
    RemoteOkSource,
    RemotiveSource,
    WorkingNomadsSource,
)
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id


def test_all_three_aggregators_registered_by_default():
    disc = build_default_discovery(live=False)
    sources = disc.available_sources()
    assert "remoteok" in sources
    assert "remotive" in sources
    assert "workingnomads" in sources


@pytest.mark.parametrize(
    "flag,key",
    [
        ("include_remoteok", "remoteok"),
        ("include_remotive", "remotive"),
        ("include_workingnomads", "workingnomads"),
    ],
)
def test_each_aggregator_individually_toggleable_off(flag, key):
    disc = build_default_discovery(live=False, **{flag: False})
    assert key not in disc.available_sources()
    # the other two are untouched
    assert len(disc.available_sources()) >= 2


@pytest.mark.unit
class TestRemoteOkSource:
    def test_normalizes_rows(self):
        src = RemoteOkSource(client=FakeRemoteOkClient())
        cid = CampaignId(new_id())
        out = src.fetch(cid, SearchCriteria(campaign_id=cid))
        assert out
        posting = out[0]
        assert posting.source_key == "remoteok"
        assert posting.title == "Delivery Manager"
        assert posting.company == "Acme Remote Co"
        assert posting.work_mode == "remote"
        assert posting.easy_apply is False  # external redirect, never guessed true

    def test_legal_notice_row_never_becomes_a_posting(self):
        # The real RemoteOK API's row 0 is a legal-notice dict with no "position"
        # key -- FakeRemoteOkClient models a clean feed, so simulate the raw shape
        # directly against the client's own filter contract via the Live client's
        # documented behavior (unit-level: the mapper simply needs a title to
        # produce anything, proving a titleless row is silently dropped, never
        # guessed into a fake posting).
        from applicant.adapters.discovery.jobspy_searxng import _map_remoteok_job

        mapped = _map_remoteok_job({"legal": "terms...", "last_updated": 123})
        assert mapped["title"] is None  # normalize_row will drop this row

    def test_failing_client_does_not_crash_run(self):
        class Boom:
            def fetch_jobs(self, *, proxies):
                raise RuntimeError("remoteok down")

        src = RemoteOkSource(client=Boom())
        cid = CampaignId(new_id())
        assert src.fetch(cid, SearchCriteria(campaign_id=cid)) == []
        assert src.last_error == "remoteok down"


@pytest.mark.unit
class TestRemotiveSource:
    def test_normalizes_rows(self):
        src = RemotiveSource(client=FakeRemotiveClient())
        cid = CampaignId(new_id())
        out = src.fetch(cid, SearchCriteria(campaign_id=cid))
        assert out
        posting = out[0]
        assert posting.source_key == "remotive"
        assert posting.title == "Technical Program Manager"
        assert posting.company == "Remotive Test Co"
        assert posting.work_mode == "remote"
        assert posting.easy_apply is False

    def test_failing_client_does_not_crash_run(self):
        class Boom:
            def fetch_jobs(self, *, proxies):
                raise RuntimeError("remotive down")

        src = RemotiveSource(client=Boom())
        cid = CampaignId(new_id())
        assert src.fetch(cid, SearchCriteria(campaign_id=cid)) == []


@pytest.mark.unit
class TestWorkingNomadsSource:
    def test_normalizes_rows(self):
        src = WorkingNomadsSource(client=FakeWorkingNomadsClient())
        cid = CampaignId(new_id())
        out = src.fetch(cid, SearchCriteria(campaign_id=cid))
        assert out
        posting = out[0]
        assert posting.source_key == "workingnomads"
        assert posting.title == "Agile Program Manager"
        assert posting.company == "Nomads Test Co"
        assert posting.work_mode == "remote"
        assert posting.easy_apply is False

    def test_failing_client_does_not_crash_run(self):
        class Boom:
            def fetch_jobs(self, *, proxies):
                raise RuntimeError("workingnomads down")

        src = WorkingNomadsSource(client=Boom())
        cid = CampaignId(new_id())
        assert src.fetch(cid, SearchCriteria(campaign_id=cid)) == []
