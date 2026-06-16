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
    FakeSearxngClient,
    LiveJobSpyClient,
    LiveSearxngClient,
)
from applicant.adapters.discovery.jobspy_searxng import (
    JobSpySearxngDiscovery,
    JobSpySource,
    ProxyConfig,
    SampleSource,
    SearxngSource,
)

#: The easy boards python-jobspy supports (FR-DISC-2 wave-one master aggregator).
JOBSPY_SITES = ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter")


def build_default_discovery(
    *,
    live: bool = False,
    searxng_url: str = "",
    proxies: tuple[str, ...] = (),
    include_sample: bool = True,
) -> JobSpySearxngDiscovery:
    """Build the default master-aggregator discovery adapter.

    The ``SampleSource`` is included by default so the offline lane always has at
    least one yielding source; in a real ``live`` deployment it is harmless (clearly
    marked example.test URLs) but may be toggled off via the registry.
    """
    proxy = ProxyConfig(proxies=proxies, enabled=bool(proxies))

    if live:
        jobspy_client = LiveJobSpyClient()
        searxng_client = LiveSearxngClient(searxng_url) if searxng_url else None
    else:
        jobspy_client = FakeJobSpyClient()
        searxng_client = FakeSearxngClient()

    sources = []
    if include_sample:
        sources.append(SampleSource())
    for site in JOBSPY_SITES:
        sources.append(JobSpySource(site=site, client=jobspy_client, proxy=proxy))
    if searxng_client is not None:
        sources.append(SearxngSource(client=searxng_client, proxy=proxy))

    return JobSpySearxngDiscovery(sources=sources, proxy=proxy)
