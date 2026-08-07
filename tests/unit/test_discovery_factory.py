import pytest

from applicant.adapters.discovery.factory import (
    CUSTOM_RSS_KEY_PREFIX,
    JOBSPY_SITES,
    RSS_FEEDS,
    _parse_feed_list,
    build_default_discovery,
)
from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySearxngDiscovery,
    SampleSource,
    SourceCircuitBreaker,
)
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id
from applicant.core.rules.underdelivery import SOURCE_COOLDOWN, SOURCE_OK


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """No lru_cache in factory.py, but autouse fixture for xdist parallel safety."""
    pass


@pytest.mark.unit
class TestDiscoveryFactory:
    """Tests for the discovery factory module (FR-DISC-2/4/6)."""

    def test_build_offline_returns_fake_clients(self):
        """build_default_discovery with live=False creates JobSpySearxngDiscovery with fake clients."""
        discovery = build_default_discovery(live=False)
        assert isinstance(discovery, JobSpySearxngDiscovery)
        sources = list(discovery._sources.values())
        assert len(sources) > 0
        for src in sources:
            if isinstance(src, SampleSource):
                continue
            client = getattr(src, "client", None)
            if client is not None:
                assert "Fake" in type(client).__name__, f"Expected Fake client, got {type(client).__name__}"

    def test_build_live_with_searxng_url_returns_live_clients(self):
        """build_default_discovery with live=True and searxng_url returns Live clients."""
        discovery = build_default_discovery(live=True, searxng_url="http://searxng:8080")
        assert isinstance(discovery, JobSpySearxngDiscovery)
        sources = list(discovery._sources.values())
        assert len(sources) > 0
        for src in sources:
            if isinstance(src, SampleSource):
                continue
            client = getattr(src, "client", None)
            if client is not None:
                assert "Live" in type(client).__name__, f"Expected Live client, got {type(client).__name__}"

    def test_parse_feed_list_splits_comma_separated(self):
        """_parse_feed_list splits a comma-separated string into a tuple."""
        result = _parse_feed_list("https://a.com/feed, https://b.com/rss")
        assert result == ("https://a.com/feed", "https://b.com/rss")

    def test_parse_feed_list_empty_string(self):
        """_parse_feed_list returns empty tuple for empty/None input."""
        assert _parse_feed_list("") == ()

    def test_parse_feed_list_single_value(self):
        """_parse_feed_list returns a single-element tuple."""
        assert _parse_feed_list("https://example.com/feed") == ("https://example.com/feed",)

    def test_parse_feed_list_removes_trailing_whitespace(self):
        """_parse_feed_list strips whitespace from each entry."""
        result = _parse_feed_list("  a  , b , c  ")
        assert result == ("a", "b", "c")

    def test_parse_feed_list_filters_empty_segments(self):
        """_parse_feed_list filters out empty strings from split results."""
        result = _parse_feed_list("a,,,b")
        assert result == ("a", "b")

    def test_rss_feeds_contains_expected_keys(self):
        """RSS_FEEDS dict contains the expected source keys."""
        assert "rss:hn-hiring" in RSS_FEEDS
        assert RSS_FEEDS["rss:hn-hiring"] == "https://hnrss.org/jobs"

    def test_custom_rss_key_prefix_correct(self):
        """CUSTOM_RSS_KEY_PREFIX is the expected prefix string."""
        assert CUSTOM_RSS_KEY_PREFIX == "rss:custom"

    def test_build_without_sample_excludes_sample_source(self):
        """build_default_discovery with include_sample=False excludes SampleSource."""
        discovery = build_default_discovery(include_sample=False)
        assert isinstance(discovery, JobSpySearxngDiscovery)
        assert "sample" not in discovery._sources

    def test_jobspy_sites_contains_expected_sites(self):
        """JOBSPY_SITES contains the expected site names."""
        expected = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter")
        assert JOBSPY_SITES == expected

    def test_build_live_without_searxng_url_searxng_not_included(self):
        """build_default_discovery with live=True but no searxng_url excludes SearxngSource."""
        discovery = build_default_discovery(live=True, searxng_url="")
        assert isinstance(discovery, JobSpySearxngDiscovery)
        assert "searxng" not in discovery._sources

    def test_build_with_rss_feeds_custom_feed_gets_custom_key(self):
        """build_default_discovery with custom rss_feeds adds them with custom prefix keys."""
        custom_feeds = ("https://custom.example.com/feed",)
        discovery = build_default_discovery(rss_feeds=custom_feeds)
        assert isinstance(discovery, JobSpySearxngDiscovery)
        custom_keys = [k for k in discovery._sources if k.startswith(CUSTOM_RSS_KEY_PREFIX)]
        assert len(custom_keys) == 1
        assert custom_keys[0] == f"{CUSTOM_RSS_KEY_PREFIX}-1"


    def test_build_with_greenhouse_and_lever_selects_fake_clients_when_offline(self):
        """live=False (default) wires the new ATS sources to the Fake clients too."""
        discovery = build_default_discovery(
            live=False, greenhouse_boards=("acme",), lever_companies=("widgets",)
        )
        gh_source = discovery._sources["greenhouse:acme"]
        lv_source = discovery._sources["lever:widgets"]
        assert type(gh_source._client).__name__ == "FakeGreenhouseClient"
        assert type(lv_source._client).__name__ == "FakeLeverClient"

    def test_build_with_greenhouse_and_lever_selects_live_clients_when_live(self):
        """live=True wires the new ATS sources to the real network clients."""
        discovery = build_default_discovery(
            live=True, greenhouse_boards=("acme",), lever_companies=("widgets",)
        )
        gh_source = discovery._sources["greenhouse:acme"]
        lv_source = discovery._sources["lever:widgets"]
        assert type(gh_source._client).__name__ == "LiveGreenhouseClient"
        assert type(lv_source._client).__name__ == "LiveLeverClient"


@pytest.mark.unit
class TestSourceCircuitBreaker:
    """Discovery resilience: a source failing N runs in a row (e.g. a
    403-blocked Glassdoor/ZipRecruiter board) is skipped for a cooldown window
    instead of being re-attempted -- and wasting a scrape -- on every single
    discovery tick."""

    class _AlwaysFailingSource:
        key = "flaky"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, campaign_id, criteria):
            self.calls += 1
            self.last_error = "board says no"
            return []

    def test_opens_after_threshold_consecutive_failures_and_skips_fetch(self):
        cid = CampaignId(new_id())
        criteria = SearchCriteria(campaign_id=cid)
        source = self._AlwaysFailingSource()
        breaker = SourceCircuitBreaker(failure_threshold=3, cooldown_seconds=3600)
        disc = JobSpySearxngDiscovery(sources=[source], circuit_breaker=breaker)

        for _ in range(3):
            disc.search(cid, criteria)
        assert source.calls == 3  # each of the first 3 runs actually attempted fetch

        # 4th run: the breaker is now open -- fetch must NOT be attempted again.
        disc.search(cid, criteria)
        assert source.calls == 3
        assert disc.last_source_outcomes == [
            {
                "source_key": "flaky",
                "status": SOURCE_COOLDOWN,
                "found": 0,
                "error": None,
            }
        ]

    def test_a_healthy_source_never_trips_the_breaker(self):
        cid = CampaignId(new_id())
        criteria = SearchCriteria(campaign_id=cid)
        source = SampleSource(key="full")
        breaker = SourceCircuitBreaker(failure_threshold=1, cooldown_seconds=3600)
        disc = JobSpySearxngDiscovery(sources=[source], circuit_breaker=breaker)
        for _ in range(5):
            disc.search(cid, criteria)
        assert disc.last_source_outcomes[0]["status"] == SOURCE_OK

    def test_ok_outcome_resets_the_consecutive_failure_count(self):
        breaker = SourceCircuitBreaker(failure_threshold=2, cooldown_seconds=3600)
        breaker.record("x", ok=False)
        breaker.record("x", ok=True)
        breaker.record("x", ok=False)
        # Only ONE consecutive failure since the "ok" reset the streak.
        assert breaker.allow("x") is True
        assert breaker.is_open("x") is False

    def test_recovers_after_the_cooldown_window_elapses(self):
        import time

        breaker = SourceCircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
        breaker.record("x", ok=False)
        assert breaker.allow("x") is False
        assert breaker.is_open("x") is True
        time.sleep(0.1)
        assert breaker.allow("x") is True
        assert breaker.is_open("x") is False

    def test_reset_clears_state(self):
        breaker = SourceCircuitBreaker(failure_threshold=1, cooldown_seconds=3600)
        breaker.record("x", ok=False)
        assert breaker.allow("x") is False
        breaker.reset("x")
        assert breaker.allow("x") is True
