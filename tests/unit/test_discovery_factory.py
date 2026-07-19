import pytest

from applicant.adapters.discovery.factory import (
    CUSTOM_RSS_KEY_PREFIX,
    JOBSPY_SITES,
    RSS_FEEDS,
    _parse_feed_list,
    build_default_discovery,
)
from applicant.adapters.discovery.jobspy_searxng import SampleSource, JobSpySearxngDiscovery


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
