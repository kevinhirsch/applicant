"""DiscoveryService deepened-behavior unit tests (FR-DISC-2/3/4/5)."""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.factory import build_default_discovery
from applicant.adapters.discovery.jobspy_searxng import JobSpySearxngDiscovery
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def embedding() -> LocalEmbedding:
    return LocalEmbedding()


@pytest.fixture
def campaign(storage) -> Campaign:
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    return c


@pytest.mark.unit
def test_sync_registry_seeds_sources(storage, embedding, campaign):
    svc = DiscoveryService(storage, build_default_discovery(live=False), embedding)
    seeded = svc.sync_registry(campaign.id)
    keys = {s.source_key for s in seeded}
    assert "jobspy:indeed" in keys and "searxng" in keys
    # Persisted to discovery_sources.
    assert storage.discovery_sources.list_for_campaign(campaign.id)


@pytest.mark.unit
def test_rss_source_is_registered_and_yields_offline(storage, embedding, campaign):
    # NFR-EXT-1: a NEW discovery source SHAPE (RSS/HN-jobs) plugs in via the registry
    # with NO core change, toggleable, and offline-faked in the default lane.
    disc = build_default_discovery(live=False)
    assert "rss:hn-hiring" in disc.available_sources()
    svc = DiscoveryService(storage, disc, embedding, LearningService(storage, embedding))
    crit = SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    kept = svc.run_discovery(campaign.id, crit)
    assert any(p.source_key == "rss:hn-hiring" for p in kept)


@pytest.mark.unit
def test_rss_source_is_toggleable(storage, embedding, campaign):
    disc = build_default_discovery(live=False)
    svc = DiscoveryService(storage, disc, embedding)
    svc.sync_registry(campaign.id)
    svc.set_source_enabled(campaign.id, "rss:hn-hiring", False)
    assert disc.is_source_enabled("rss:hn-hiring") is False
    crit = SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    kept = svc.run_discovery(campaign.id, crit)
    assert not any(p.source_key == "rss:hn-hiring" for p in kept)


@pytest.mark.unit
def test_toggle_source_persists_and_excludes(storage, embedding, campaign):
    disc = build_default_discovery(live=False)
    svc = DiscoveryService(storage, disc, embedding)
    svc.sync_registry(campaign.id)
    svc.set_source_enabled(campaign.id, "jobspy:indeed", False)
    assert disc.is_source_enabled("jobspy:indeed") is False
    rec = storage.discovery_sources.get(campaign.id, "jobspy:indeed")
    assert rec is not None and rec.enabled is False


@pytest.mark.unit
def test_run_records_source_yield_to_learning(storage, embedding, campaign):
    learning = LearningService(storage, embedding)
    disc = build_default_discovery(live=False)
    svc = DiscoveryService(storage, disc, embedding, learning)
    crit = SearchCriteria(campaign_id=campaign.id, titles=("engineer",))
    kept = svc.run_discovery(campaign.id, crit)
    assert kept
    # yield_stats persisted per source the run yielded from (FR-DISC-5).
    sources = storage.discovery_sources.list_for_campaign(campaign.id)
    yielded = [s for s in sources if s.yield_stats.get("matches", 0) > 0]
    assert yielded


@pytest.mark.unit
def test_run_dedups_identical_postings(storage, embedding, campaign):
    from applicant.adapters.discovery.jobspy_searxng import SampleSource

    disc = JobSpySearxngDiscovery(sources=[SampleSource(key="a"), SampleSource(key="b")])
    svc = DiscoveryService(storage, disc, embedding)
    kept = svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
    urls = [p.source_url for p in kept]
    assert len(urls) == len(set(urls))


@pytest.mark.unit
def test_scoring_biases_toward_converting_signature(storage, embedding, campaign):
    # FR-LEARN-5: a role matching the converting signature is boosted vs no-learning.
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.ids import JobPostingId

    learning = LearningService(storage, embedding)
    model = learning.load_model(campaign.id)
    model = learning.record_converting_role(model, "python backend engineer fastapi postgres")
    learning.persist_model(model)

    crit = SearchCriteria(campaign_id=campaign.id, keywords=("engineer",))
    posting = JobPosting(
        id=JobPostingId(new_id()), campaign_id=campaign.id, title="Backend Engineer",
        company="A", source_url="u1", description="python fastapi backend postgres services",
    )

    biased = ScoringService(storage, llm=None, embedding=embedding, learning=learning)
    unbiased = ScoringService(storage, llm=None, embedding=embedding, learning=None)
    biased_score = biased.score_posting(posting, crit)
    # A role aligned with the converting signature is lifted, and the lift is disclosed.
    assert biased_score.score > unbiased.score_posting(posting, crit).score
    assert "converting-role signature" in biased_score.rationale
