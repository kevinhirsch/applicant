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
    ``container.py`` threads the configured ``discovery_rss_feeds`` Settings field in
    here the same way it injects ``proxies`` -- the adapter never reaches up into the
    app/config layer itself (hexagonal layering, NFR-ARCH-1); a ``None``/omitted value
    simply means "no operator feeds", exactly like an empty ``proxies`` tuple.
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
        configured_feeds = rss_feeds or ()
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
