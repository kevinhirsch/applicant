"""Discovery contract against the JobSpySearxngDiscovery adapter (FR-DISC-1..4).

Architecture §6: every adapter ships a contract test. This proves the master
aggregator honors the DiscoveryPort behavioral contract — pluggable toggleable
sources, normalized postings, dedup — fully offline via the sample source.
§10 anchor: "Master aggregator in wave one".
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.jobspy_searxng import JobSpySearxngDiscovery, SampleSource
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.discovery import DiscoveryPort


@pytest.mark.contract
class TestJobSpySearxngDiscoveryContract:
    @pytest.fixture
    def adapter(self) -> JobSpySearxngDiscovery:
        return JobSpySearxngDiscovery()  # defaults to the offline SampleSource

    @pytest.fixture
    def campaign_id(self) -> CampaignId:
        return CampaignId(new_id())

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, DiscoveryPort)

    def test_search_returns_normalized_postings(self, adapter, campaign_id):
        crit = SearchCriteria(campaign_id=campaign_id, titles=("engineer",))
        results = adapter.search(campaign_id, crit)
        assert results, "offline sample source must yield postings"
        for p in results:
            assert isinstance(p, JobPosting)
            assert p.campaign_id == campaign_id  # campaign-scoped (FR-DISC-3)
            assert p.title and p.company and p.source_url
            assert p.source_key  # provenance for source-yield learning (FR-DISC-5)

    def test_available_and_enabled_sources(self, adapter):
        assert "sample" in adapter.available_sources()
        assert "sample" in adapter.enabled_sources()

    def test_disabling_a_source_excludes_it(self, adapter, campaign_id):
        adapter.set_source_enabled("sample", False)
        assert adapter.search(campaign_id, SearchCriteria(campaign_id=campaign_id)) == []
        assert "sample" not in adapter.enabled_sources()

    def test_unknown_source_toggle_raises(self, adapter):
        with pytest.raises(KeyError):
            adapter.set_source_enabled("does-not-exist", True)

    def test_criteria_filter_is_applied(self, adapter, campaign_id):
        crit = SearchCriteria(campaign_id=campaign_id, titles=("office manager",))
        results = adapter.search(campaign_id, crit)
        assert all("engineer" not in p.title.lower() for p in results)

    def test_dedup_across_sources_by_url(self, campaign_id):
        # Two registered sources returning the same posting URL collapse to one.
        a = SampleSource(key="a")
        b = SampleSource(key="b")
        agg = JobSpySearxngDiscovery(sources=[a, b])
        results = agg.search(campaign_id, SearchCriteria(campaign_id=campaign_id))
        urls = [p.source_url for p in results]
        assert len(urls) == len(set(urls)), "aggregator must dedup by source_url"

    def test_apply_toggles_ignores_unknown_keys(self, adapter, campaign_id):
        # Persisted toggles for an un-registered source must not crash (FR-DISC-2).
        adapter.apply_toggles({"sample": True, "not-registered": False})
        assert adapter.is_source_enabled("sample") is True


@pytest.mark.contract
class TestLiveSourcesOffline:
    """The LIVE JobSpy/SearXNG source code paths, exercised fully offline (FR-DISC-2/4).

    Uses the fake network clients so the real ``JobSpySource``/``SearxngSource`` +
    normalization run with NO network — the hermetic default lane.
    """

    @pytest.fixture
    def campaign_id(self) -> CampaignId:
        return CampaignId(new_id())

    def test_default_factory_aggregator_is_offline_and_yields(self, campaign_id):
        from applicant.adapters.discovery.factory import (
            JOBSPY_SITES,
            build_default_discovery,
        )

        agg = build_default_discovery(live=False)
        # Every easy board is a separately-toggleable registered source (FR-DISC-2).
        for site in JOBSPY_SITES:
            assert f"jobspy:{site}" in agg.available_sources()
        assert "searxng" in agg.available_sources()
        crit = SearchCriteria(campaign_id=campaign_id, titles=("engineer",))
        results = agg.search(campaign_id, crit)
        assert results
        for p in results:
            assert isinstance(p, JobPosting)
            assert p.title and p.source_url and p.source_key

    def test_jobspy_source_normalizes_rows(self, campaign_id):
        from applicant.adapters.discovery.clients import FakeJobSpyClient
        from applicant.adapters.discovery.jobspy_searxng import JobSpySource

        src = JobSpySource(site="indeed", client=FakeJobSpyClient())
        out = src.fetch(campaign_id, SearchCriteria(campaign_id=campaign_id))
        assert out and out[0].source_key == "jobspy:indeed"
        assert out[0].work_mode == "remote"  # is_remote True -> normalized
        assert out[0].salary  # min/max amount folded into a salary string

    def test_failing_client_does_not_crash_run(self, campaign_id):
        from applicant.adapters.discovery.jobspy_searxng import JobSpySource

        class Boom:
            def scrape(self, **kw):
                raise RuntimeError("board down")

        src = JobSpySource(site="indeed", client=Boom())
        assert src.fetch(campaign_id, SearchCriteria(campaign_id=campaign_id)) == []

    def test_proxy_hook_threads_through(self, campaign_id):
        # FR-DISC-6: a configured proxy is passed to the client; default is none.
        from applicant.adapters.discovery.jobspy_searxng import JobSpySource, ProxyConfig

        seen = {}

        class Recorder:
            def scrape(self, *, site, search_term, location, results_wanted, proxies):
                seen["proxies"] = proxies
                return []

        JobSpySource(
            site="indeed", client=Recorder(), proxy=ProxyConfig(proxies=("http://p",), enabled=True)
        ).fetch(campaign_id, SearchCriteria(campaign_id=campaign_id))
        assert seen["proxies"] == ["http://p"]
