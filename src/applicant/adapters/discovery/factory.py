"""Default discovery wiring (FR-DISC-2/4/6).

Builds the master-aggregator ``JobSpySearxngDiscovery`` with the full easy-board
registry. The clients are chosen by config:

- ``live=False`` (DEFAULT, and ALWAYS in the test lane): every source is wired to the
  **fake** offline clients, so discovery runs with zero network.
- ``live=True`` (real deployment, opt-in via ``DISCOVERY_LIVE``): sources use the live
  python-jobspy / SearXNG clients behind the network boundary.

Either way the registry shape (source keys, toggles) is identical, so persisted
``discovery_sources`` toggles apply the same regardless of mode (FR-DISC-2).
"""

from __future__ import annotations

from applicant.adapters.discovery.clients import (
    FakeJobSpyClient,
    FakeRssClient,
    FakeSearxngClient,
    LiveJobSpyClient,
    LiveRssClient,
    LiveSearxngClient,
)
from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySearxngDiscovery,
    JobSpySource,
    ProxyConfig,
    RssSource,
    SampleSource,
    SearxngSource,
)

#: The easy boards python-jobspy supports (FR-DISC-2 wave-one master aggregator).
JOBSPY_SITES = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter")

#: Default RSS/feed sources (FR-DISC-2 extensible source SHAPE, NFR-EXT-1). Key ->
#: feed URL; toggleable per campaign exactly like every other source.
RSS_FEEDS: dict[str, str] = {
    "rss:hn-hiring": "https://hnrss.org/jobs",
}

#: Source-key prefix for an operator-configured custom feed (dark-engine audit
#: item 80, B7) so it can never collide with a hardcoded ``RSS_FEEDS`` key.
CUSTOM_RSS_KEY_PREFIX = "rss:custom"


def _parse_feed_list(value: str) -> tuple[str, ...]:
    """Split a comma-separated feed-URL string (``DISCOVERY_RSS_FEEDS`` shape)
    into a tuple, exactly like ``container.py`` parses ``discovery_proxies``."""
    return tuple(p.strip() for p in (value or "").split(",") if p.strip())


def _configured_rss_feeds_from_settings() -> tuple[str, ...]:
    """Fall back to the persisted/env ``discovery_rss_feeds`` Settings field.

    Every other discovery knob (``proxies``, ``searxng_url``, ``live``) is threaded
    into :func:`build_default_discovery` by ``container.py`` at boot, reading the
    SAME cached ``Settings`` singleton once. ``container.py`` is out of scope for
    this change (a sibling agent owns it concurrently in this session -- see the
    CLAUDE.md working-agreement), so rather than leave a configured feed
    unreachable, this factory reads that identical cached singleton
    (``get_settings()``) directly whenever a caller does not explicitly pass
    ``rss_feeds`` -- the production/no-arg call path container.py already uses.
    Tests (and any future caller) that want a hermetic override, mirroring how
    ``proxies`` is injected, can pass ``rss_feeds=(...)`` explicitly instead.
    """
    from applicant.app.config import get_settings

    return _parse_feed_list(get_settings().discovery_rss_feeds)


def build_default_discovery(
    *,
    live: bool = False,
    searxng_url: str = "",
    proxies: tuple[str, ...] = (),
    include_sample: bool = True,
    include_rss: bool = True,
    rss_feeds: tuple[str, ...] | None = None,
) -> JobSpySearxngDiscovery:
    """Build the default master-aggregator discovery adapter.

    The ``SampleSource`` is included by default so the offline lane always has at
    least one yielding source; in a real ``live`` deployment it is harmless (clearly
    marked example.test URLs) but may be toggled off via the registry.

    ``rss_feeds`` (item 80, B7): an explicit tuple of operator-added job-board feed
    URLs, registered ALONGSIDE the hardcoded ``RSS_FEEDS`` (never replacing them) so
    an empty/unset value reproduces today's hardcoded-only behavior byte-identical.
    When omitted (``None``, the default -- the shape every existing caller,
    including ``container.py``, already uses) this reads the configured
    ``DISCOVERY_RSS_FEEDS`` setting itself; see ``_configured_rss_feeds_from_settings``.
    """
    proxy = ProxyConfig(proxies=proxies, enabled=bool(proxies))

    if live:
        jobspy_client = LiveJobSpyClient()
        searxng_client = LiveSearxngClient(searxng_url) if searxng_url else None
        rss_client = LiveRssClient()
    else:
        jobspy_client = FakeJobSpyClient()
        searxng_client = FakeSearxngClient()
        rss_client = FakeRssClient()

    sources = []
    if include_sample:
        sources.append(SampleSource())
    for site in JOBSPY_SITES:
        sources.append(JobSpySource(site=site, client=jobspy_client, proxy=proxy))
    if searxng_client is not None:
        sources.append(SearxngSource(client=searxng_client, proxy=proxy))
    if include_rss:
        for key, feed_url in RSS_FEEDS.items():
            sources.append(
                RssSource(client=rss_client, feed_url=feed_url, proxy=proxy, key=key)
            )
        configured_feeds = (
            rss_feeds if rss_feeds is not None else _configured_rss_feeds_from_settings()
        )
        for idx, feed_url in enumerate(configured_feeds, start=1):
            sources.append(
                RssSource(
                    client=rss_client,
                    feed_url=feed_url,
                    proxy=proxy,
                    key=f"{CUSTOM_RSS_KEY_PREFIX}-{idx}",
                )
            )

    return JobSpySearxngDiscovery(sources=sources, proxy=proxy)
