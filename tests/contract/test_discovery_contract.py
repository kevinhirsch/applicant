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
