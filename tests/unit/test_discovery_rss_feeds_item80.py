"""Custom job-board RSS feeds (dark-engine audit item 80, B7).

Before this change ``src/applicant/adapters/discovery/factory.py`` had a hardcoded
``RSS_FEEDS`` dict (only ``rss:hn-hiring`` -> hnrss.org/jobs) with no way for an
operator to add their own job-board feed. This mirrors the EXACT pattern item 101
(``discovery_proxies``) already established for a comma-separated operator-supplied
list: a ``DISCOVERY_RSS_FEEDS`` config field, the same ``AutomationPrefsIn``
persistence/validation plumbing, and -- the reachability bar (CLAUDE.md principle
#2) -- the configured feed must actually reach ``build_default_discovery`` and
produce a real, searchable ``RssSource``, not just sit in storage.

Each assertion here was hand-verified to go RED when the corresponding piece of the
wiring is reverted (file-copy backup, never ``git stash`` -- this worktree is shared
with concurrent sibling agents), then GREEN again after restoring.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.factory import (
    RSS_FEEDS,
    build_default_discovery,
)
from applicant.app.config import get_settings
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """``get_settings`` is ``@lru_cache``-d (one instance per process); clear it
    before AND after so an env-var mutation in one test never leaks into the
    next (mirrors ``tests/conftest.py``'s own ``get_settings.cache_clear()``
    idiom around ``DATABASE_URL``/``CHECKPOINT_DIR``)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_empty_setting_reproduces_todays_hardcoded_only_behavior_byte_identical():
    """An unconfigured ``discovery_rss_feeds`` (the default, "") must NOT change
    the source registry at all -- only the hardcoded ``RSS_FEEDS`` entries exist,
    exactly like before this change."""
    disc = build_default_discovery(live=False)
    rss_keys = [k for k in disc.available_sources() if k.startswith("rss:")]
    assert rss_keys == sorted(RSS_FEEDS)


def test_a_configured_feed_url_reaches_build_default_discovery_via_explicit_arg():
    """The explicit ``rss_feeds`` kwarg (mirrors how ``proxies`` is injected) adds
    a NEW ``RssSource`` alongside the hardcoded default -- proving the merge is
    additive, not a replacement (an empty setting must stay byte-identical)."""
    disc = build_default_discovery(
        live=False, rss_feeds=("https://boards.example.com/careers.rss",)
    )
    sources = disc.available_sources()
    assert "rss:hn-hiring" in sources  # hardcoded default still present
    assert "rss:custom-1" in sources  # the operator-added feed registered too


def test_a_configured_feed_actually_produces_discovered_postings():
    """Reachability proof (CLAUDE.md principle #2): a configured custom feed
    isn't just registered as a source key -- running ``search`` against it (via
    the SAME offline ``FakeRssClient`` every other RSS source uses) actually
    yields postings tagged with the custom source key, exactly as a real
    hnrss.org-shaped posting would be."""
    disc = build_default_discovery(
        live=False, rss_feeds=("https://boards.example.com/careers.rss",)
    )
    criteria = SearchCriteria(campaign_id=CampaignId(new_id()))
    postings = disc.search(
        CampaignId(new_id()), criteria, sources=["rss:custom-1"]
    )
    assert postings, "a configured custom RSS feed must yield discovered postings"
    assert all(p.source_key == "rss:custom-1" for p in postings)


def test_multiple_configured_feeds_each_get_a_distinct_source_key():
    disc = build_default_discovery(
        live=False,
        rss_feeds=(
            "https://boards.example.com/careers.rss",
            "https://other.example.com/jobs.atom",
        ),
    )
    sources = disc.available_sources()
    assert "rss:custom-1" in sources
    assert "rss:custom-2" in sources


def test_include_rss_false_disables_configured_feeds_too():
    """``include_rss=False`` is the master RSS-source-shape toggle -- it must
    switch off BOTH the hardcoded default and any configured custom feeds, not
    just the hardcoded one."""
    disc = build_default_discovery(
        live=False,
        include_rss=False,
        rss_feeds=("https://boards.example.com/careers.rss",),
    )
    rss_keys = [k for k in disc.available_sources() if k.startswith("rss:")]
    assert rss_keys == []


def test_the_container_threads_the_configured_feed_into_discovery(monkeypatch):
    """Reachability through the PROPER layer: ``container.py`` reads the configured
    ``DISCOVERY_RSS_FEEDS`` setting and injects it into ``build_default_discovery``
    (exactly as it does for ``proxies``), so a boot-configured feed reaches the live
    discovery adapter. The adapter itself never imports ``app.config`` — that would
    break the hexagonal layering contract (NFR-ARCH-1), so the wiring lives here."""
    from applicant.app.config import Settings
    from applicant.app.container import build_container

    monkeypatch.setenv("DISCOVERY_RSS_FEEDS", "https://boards.example.com/careers.rss")
    get_settings.cache_clear()
    container = build_container(Settings())
    assert "rss:custom-1" in container.discovery.available_sources()


def test_settings_default_discovery_rss_feeds_is_empty_string():
    get_settings.cache_clear()
    assert get_settings().discovery_rss_feeds == ""
