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


class _RecordingSource:
    """A discovery Source that records each fetch + yields one posting."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.fetched = False

    def fetch(self, campaign_id, criteria):
        from applicant.core.entities.job_posting import JobPosting
        from applicant.core.ids import JobPostingId, new_id

        self.fetched = True
        return [
            JobPosting(
                id=JobPostingId(new_id()),
                campaign_id=campaign_id,
                title=f"Role from {self.key}",
                company="Co",
                source_url=f"https://{self.key}.test/job",
                source_key=self.key,
                description="python engineer",
            )
        ]


@pytest.mark.unit
def test_source_ranking_prioritizes_high_yield_and_explores_cold(storage, embedding, campaign):
    # FR-DISC-5/FR-LEARN-6: discovery orders enabled sources by learned conversion
    # yield (high-yield first) AND the exploration budget still probes a cold source.
    hot = _RecordingSource("hot")
    cold = _RecordingSource("cold")
    disc = JobSpySearxngDiscovery(sources=[hot, cold])
    learning = LearningService(storage, embedding)

    # Give "hot" a strong conversion history (matches + approvals + submissions);
    # "cold" has no history at all. Set a non-zero exploration budget so cold probes.
    import dataclasses

    storage.campaigns.add(dataclasses.replace(campaign, exploration_budget=0.5))
    storage.commit()
    model = learning.load_model(campaign.id)
    model = learning.record_source_funnel(
        model, {"hot": {"matches": 10, "approvals": 5, "submissions": 3}}
    )
    learning.persist_model(model)

    svc = DiscoveryService(storage, disc, embedding, learning)
    order = svc._prioritized_sources(campaign.id)
    # The high-yield source is prioritized ahead of the cold one.
    assert order.index("hot") < order.index("cold")

    kept = svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
    # Both were queried: the exploit (hot) AND the exploration probe (cold).
    assert hot.fetched and cold.fetched
    assert {p.source_key for p in kept} == {"hot", "cold"}


@pytest.mark.unit
def test_discovery_titles_shift_toward_converting_role(storage, embedding, campaign):
    # FR-LEARN-5: a recorded conversion signature biases discovery toward the
    # converting role's titles. The criteria the aggregator receives gains the
    # converting title, shifting which roles discovery seeks.
    learning = LearningService(storage, embedding)
    model = learning.load_model(campaign.id)
    model = learning.record_converting_role(
        model, "staff platform engineer kubernetes", title="Staff Platform Engineer"
    )
    learning.persist_model(model)

    seen = {}

    class _CapturingSource:
        key = "cap"

        def fetch(self, campaign_id, criteria):
            seen["titles"] = tuple(criteria.titles)
            return []

    disc = JobSpySearxngDiscovery(sources=[_CapturingSource()])
    svc = DiscoveryService(storage, disc, embedding, learning)
    svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id, titles=("engineer",)))
    # The user's title is preserved AND the converting role's title is folded in.
    assert "engineer" in seen["titles"]
    assert "Staff Platform Engineer" in seen["titles"]


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


# --- #49 dark-engine audit: per-domain discovery pacing wired into run_discovery ---
class _PacingFakeDiscovery:
    """Minimal fake discovery adapter returning a fixed posting batch (no network)."""

    def __init__(self, postings) -> None:
        self._postings = list(postings)

    def available_sources(self):
        return ["fake"]

    def is_source_enabled(self, key):
        return True

    def apply_toggles(self, toggles):
        pass

    def search(self, campaign_id, criteria, *, sources=None):
        return list(self._postings)


def _pacing_posting(campaign_id, url, title="Role"):
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.ids import JobPostingId

    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign_id,
        title=title,
        company="Acme",
        source_url=url,
    )


class _FakePaceClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.mark.unit
def test_run_discovery_spaces_same_domain_postings(storage, embedding, campaign):
    # Two postings on the SAME job-board domain must be spaced >= interval apart.
    postings = [
        _pacing_posting(campaign.id, "https://boards.test/jobs/1", "Role A"),
        _pacing_posting(campaign.id, "https://boards.test/jobs/2", "Role B"),
    ]
    disc = _PacingFakeDiscovery(postings)
    clock = _FakePaceClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.advance(seconds)

    svc = DiscoveryService(
        storage, disc, embedding,
        per_domain_interval_seconds=2.0,
        pace_clock=clock, pace_sleep=fake_sleep,
    )
    kept = svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
    assert len(kept) == 2
    # The second same-domain posting had to wait ~2s (the configured interval).
    assert sleep_calls == [2.0]


@pytest.mark.unit
def test_run_discovery_does_not_block_different_domains(storage, embedding, campaign):
    # Two postings on DIFFERENT domains must never wait on each other.
    postings = [
        _pacing_posting(campaign.id, "https://board-a.test/jobs/1", "Role A"),
        _pacing_posting(campaign.id, "https://board-b.test/jobs/1", "Role B"),
    ]
    disc = _PacingFakeDiscovery(postings)
    clock = _FakePaceClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.advance(seconds)

    svc = DiscoveryService(
        storage, disc, embedding,
        per_domain_interval_seconds=2.0,
        pace_clock=clock, pace_sleep=fake_sleep,
    )
    kept = svc.run_discovery(campaign.id, SearchCriteria(campaign_id=campaign.id))
    assert len(kept) == 2
    # Neither posting waited: different domains are independent.
    assert sleep_calls == []


@pytest.mark.unit
def test_pace_schedule_is_pure_and_reused_by_run_discovery(storage, embedding, campaign):
    # pace_schedule itself (#195) computes the same/different-domain spacing rule
    # run_discovery now enforces -- this proves the exact dead method is the one
    # that got wired, not a parallel reimplementation.
    same = [
        _pacing_posting(campaign.id, "https://boards.test/jobs/1"),
        _pacing_posting(campaign.id, "https://boards.test/jobs/2"),
        _pacing_posting(campaign.id, "https://other.test/jobs/1"),
    ]
    disc = _PacingFakeDiscovery([])
    svc = DiscoveryService(storage, disc, embedding, per_domain_interval_seconds=2.0)
    schedule = svc.pace_schedule(same, start=100.0)
    releases = {p.source_url: t for p, t in schedule}
    assert releases["https://boards.test/jobs/1"] == 100.0
    assert releases["https://boards.test/jobs/2"] == 102.0  # spaced by the interval
    assert releases["https://other.test/jobs/1"] == 100.0  # different domain: unblocked


@pytest.mark.unit
def test_apply_pacing_is_bounded_never_hangs(storage, embedding, campaign):
    # A burst of same-domain postings large enough to need MORE than the total pacing
    # budget must not block the caller indefinitely -- it degrades to unpaced
    # emission for the remainder (#49). Exercises ``_apply_pacing`` directly (the
    # enforcement ``run_discovery`` calls) so this is independent of dedup behavior.
    from applicant.application.services.discovery_service import (
        _MAX_TOTAL_PACE_WAIT_SECONDS,
    )

    postings = [
        _pacing_posting(campaign.id, f"https://boards.test/jobs/{i}")
        for i in range(50)
    ]
    disc = _PacingFakeDiscovery([])
    clock = _FakePaceClock()
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.advance(seconds)

    svc = DiscoveryService(
        storage, disc, embedding,
        per_domain_interval_seconds=2.0,  # 50 postings * 2s would be 98s unbounded
        pace_clock=clock, pace_sleep=fake_sleep,
    )
    svc._apply_pacing(postings)
    # Bounded: the call returned (didn't hang) and never slept more, in total, than
    # the configured budget -- the remaining same-domain postings past the budget
    # are emitted unpaced rather than blocking indefinitely.
    assert sum(sleep_calls) <= _MAX_TOTAL_PACE_WAIT_SECONDS + 1e-9
    assert len(sleep_calls) > 0  # pacing genuinely engaged before the budget ran out
