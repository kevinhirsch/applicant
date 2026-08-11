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

from collections.abc import Callable

from applicant.adapters.discovery.clients import (
    FakeAshbyClient,
    FakeGreenhouseClient,
    FakeJobSpyClient,
    FakeLeverClient,
    FakeRemoteOkClient,
    FakeRemotiveClient,
    FakeRssClient,
    FakeSearxngClient,
    FakeSmartRecruitersClient,
    FakeWorkdayClient,
    FakeWorkingNomadsClient,
    LiveAshbyClient,
    LiveGreenhouseClient,
    LiveJobSpyClient,
    LiveLeverClient,
    LiveRemoteOkClient,
    LiveRemotiveClient,
    LiveRssClient,
    LiveSearxngClient,
    LiveSmartRecruitersClient,
    LiveWorkdayClient,
    LiveWorkingNomadsClient,
)
from applicant.adapters.discovery.jobspy_searxng import (
    AshbySource,
    GreenhouseSource,
    JobSpySearxngDiscovery,
    JobSpySource,
    LeverSource,
    PerBoardRateLimiter,
    ProxyConfig,
    RemoteOkSource,
    RemotiveSource,
    RssSource,
    SampleSource,
    SearxngSource,
    SmartRecruitersSource,
    WorkdaySource,
    WorkingNomadsSource,
)
from applicant.core.stealth_policy import StealthConfig

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

#: Default Greenhouse board tokens (keyless ATS source shape, NFR-EXT-1). Keyed
#: like ``RSS_FEEDS`` (source key -> board token) for future hardcoded defaults.
#: Empty by default so an unset ``DISCOVERY_GREENHOUSE_BOARDS`` reproduces the
#: pre-change registry byte-identical. Operator tokens are threaded in separately.
GREENHOUSE_BOARD_TOKENS: dict[str, str] = {}

#: Default Lever company slugs (keyless ATS source shape, NFR-EXT-1). Keyed like
#: ``RSS_FEEDS`` (source key -> company slug). Empty by default; an unset
#: ``DISCOVERY_LEVER_COMPANIES`` registers zero Lever sources.
LEVER_COMPANIES: dict[str, str] = {}

#: Default Ashby org slugs (keyless ATS source shape, NFR-EXT-1). Keyed like
#: ``GREENHOUSE_BOARD_TOKENS`` (source key -> org slug). Empty by default; an
#: unset ``DISCOVERY_ASHBY_ORGS`` registers zero Ashby sources.
ASHBY_ORGS: dict[str, str] = {}

#: Default SmartRecruiters company identifiers (keyless ATS source shape,
#: NFR-EXT-1). Keyed like ``LEVER_COMPANIES`` (source key -> company id). Empty by
#: default; an unset ``DISCOVERY_SMARTRECRUITERS_COMPANIES`` registers zero
#: SmartRecruiters sources.
SMARTRECRUITERS_COMPANIES: dict[str, str] = {}

#: Default Workday tenant/site boards (keyless ATS source shape, NFR-EXT-1). Keyed
#: like every other ATS registry (source key -> compound
#: ``"host|tenant|site[|Display Name]"`` token, see ``clients.LiveWorkdayClient``).
#: Empty by default; an unset ``DISCOVERY_WORKDAY_BOARDS`` registers zero Workday
#: sources. Workday is the connector that reaches Kevin's PRIMARY target
#: industries (financial services, healthcare, insurance, consulting) -- those
#: enterprises run Workday almost exclusively, not Greenhouse/Lever/Ashby.
WORKDAY_BOARDS: dict[str, str] = {}


def _parse_feed_list(value: str) -> tuple[str, ...]:
    """Split a comma-separated feed-URL string (``DISCOVERY_RSS_FEEDS`` shape)
    into a tuple, exactly like ``container.py`` parses ``discovery_proxies``."""
    return tuple(p.strip() for p in (value or "").split(",") if p.strip())


def _parse_greenhouse_boards(value: str) -> tuple[str, ...]:
    """Split a comma-separated Greenhouse board-token string."""
    return tuple(t.strip() for t in (value or "").split(",") if t.strip())


def _parse_lever_companies(value: str) -> tuple[str, ...]:
    """Split a comma-separated Lever company-slug string."""
    return tuple(c.strip() for c in (value or "").split(",") if c.strip())


def _parse_ashby_orgs(value: str) -> tuple[str, ...]:
    """Split a comma-separated Ashby org-slug string."""
    return tuple(o.strip() for o in (value or "").split(",") if o.strip())


def _parse_smartrecruiters_companies(value: str) -> tuple[str, ...]:
    """Split a comma-separated SmartRecruiters company-id string."""
    return tuple(c.strip() for c in (value or "").split(",") if c.strip())


def _parse_workday_boards(value: str) -> tuple[str, ...]:
    """Split a comma-separated Workday board-token string.

    Each item is itself a pipe-delimited ``"host|tenant|site[|Display Name]"``
    compound token (see ``clients.LiveWorkdayClient``) -- the outer split is by
    comma (one board per item), exactly like every other ATS list here; the pipe
    delimiter never collides with a comma so this stays a plain single-level split.
    """
    return tuple(b.strip() for b in (value or "").split(",") if b.strip())


def build_default_discovery(
    *,
    live: bool = False,
    searxng_url: str = "",
    proxies: tuple[str, ...] = (),
    include_sample: bool = True,
    include_rss: bool = True,
    include_remoteok: bool = True,
    include_remotive: bool = True,
    include_workingnomads: bool = True,
    rss_feeds: tuple[str, ...] | None = None,
    greenhouse_boards: tuple[str, ...] | None = None,
    lever_companies: tuple[str, ...] | None = None,
    ashby_orgs: tuple[str, ...] | None = None,
    smartrecruiters_companies: tuple[str, ...] | None = None,
    workday_boards: tuple[str, ...] | None = None,
    stealth: StealthConfig | None = None,
    stealth_provider: Callable[[], StealthConfig | None] | None = None,
    sessid_provider: Callable[[], str | None] | None = None,
    flow_sessid: str | None = None,
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

    ``greenhouse_boards`` / ``lever_companies`` / ``ashby_orgs`` /
    ``smartrecruiters_companies`` / ``workday_boards``: additive keyless ATS
    sources (NFR-EXT-1). Each configured Greenhouse board token becomes one source
    with key ``greenhouse:{token}``; each Lever company slug -> ``lever:{company}``;
    each Ashby org slug -> ``ashby:{org}``; each SmartRecruiters company id ->
    ``smartrecruiters:{company}``; each Workday board token -> ``workday:{tenant}``
    (Workday's token is the compound ``"host|tenant|site[|Display Name]"`` string
    ``LiveWorkdayClient`` needs -- the registry key uses just the tenant segment so
    it stays short and readable). They are APPENDED to the registry alongside the
    hardcoded defaults -- never replacing them -- so empty/unset values reproduce
    today's registry byte-identical.

    ``include_remoteok`` / ``include_remotive`` / ``include_workingnomads`` (EPIC
    BREADTH, NFR-EXT-1): the keyless remote-job AGGREGATORS -- each ONE global
    feed (not a per-company registry loop like the ATS sources above) that already
    indexes postings across many companies/industries, so reach is not bounded by
    which companies were explicitly enumerated. All default ``True`` (on) since
    they were live-verified to return real postings; set ``False`` to turn one off
    without touching the per-campaign toggle.

    ``stealth`` (EPIC STEALTH, ST-2/ST-5): the resolved per-source proxy policy
    (``core.stealth_policy.StealthConfig``). When supplied, each source's egress is
    resolved SELECTIVELY -- block-prone python-jobspy boards get the residential
    forwarder (and escalate to it on block-detect), keyless ATS / your own SearXNG /
    RSS stay direct -- and the per-board rate limiter is built from its pacing knobs.
    The ``flow_sessid`` decorates the residential proxy with a sticky DataImpulse
    session label so a whole flow shares ONE residential IP. When ``stealth`` is
    ``None`` (the default, and every existing caller/test) the legacy single-proxy
    path is used and behavior is byte-identical to before this epic.

    ``stealth_provider`` (EPIC STEALTH live re-read): a callable that RE-RESOLVES the
    effective ``StealthConfig`` from the persisted Settings > Stealth posture. It is
    threaded into every block-prone ``JobSpySource`` (the boards a stealth save
    actually governs) so ``fetch()``/block-detect escalation re-resolve the LIVE
    policy on EVERY call -- not just once here at aggregator-build time -- and into
    the aggregator's ``PerBoardRateLimiter`` so ``request_rate_per_min`` is likewise
    live. A save GOVERNS the very next fetch WITHOUT rebuilding the aggregator or
    restarting the process. ``None`` (every existing caller/test) keeps the whole
    resolution path byte-identical to before this epic: the STATIC ``stealth``
    (already resolved once, right here, for the values threaded into each source's
    constructor) is all any source ever sees.

    ``sessid_provider``: a callable that RE-RESOLVES the operator-pinned
    ``residential_sticky_sessid`` live (empty ⇒ nothing pinned). Threaded alongside
    ``stealth_provider`` so a newly-pinned (or changed) sticky session id also
    governs the NEXT fetch's residential decoration without a restart; an empty/
    failed live read falls back to the STATIC ``flow_sessid`` below so a whole run
    still shares ONE residential identity even when nothing is pinned.
    """
    proxy = ProxyConfig(proxies=proxies, enabled=bool(proxies))

    def _current_stealth() -> StealthConfig | None:
        # Live posture wins when a provider is wired; else the static config. A
        # provider failure degrades to the static config so a store read never
        # breaks discovery wiring.
        if stealth_provider is not None:
            try:
                live = stealth_provider()
            except Exception:  # pragma: no cover - defensive: never break wiring
                live = None
            if live is not None:
                return live
        return stealth

    def _proxy_for(source_key: str) -> ProxyConfig:
        # Per-source egress resolution (ST-2): the stealth policy decides whether
        # this source uses the residential pool, a VPS proxy, or direct egress.
        # Absent a stealth policy, fall back to the shared legacy proxy so the
        # existing FR-DISC-6 behavior is preserved byte-identical.
        current = _current_stealth()
        if current is None:
            return proxy
        urls = current.proxy_urls_for(source_key, sessid=flow_sessid)
        return ProxyConfig(proxies=tuple(urls), enabled=bool(urls))

    def _escalation_for(source_key: str) -> ProxyConfig | None:
        # On block-detect (400/403/429/503) a block-prone source retries once
        # through the residential pool -- unless it is already using it, in which
        # case there is nothing to escalate to.
        current = _current_stealth()
        if current is None:
            return None
        pool = current.escalation_pool(flow_sessid)
        if not pool:
            return None
        if tuple(pool) == tuple(current.proxy_urls_for(source_key, sessid=flow_sessid)):
            return None
        return ProxyConfig(proxies=tuple(pool), enabled=True)

    if live:
        jobspy_client = LiveJobSpyClient()
        searxng_client = LiveSearxngClient(searxng_url) if searxng_url else None
        rss_client = LiveRssClient()
        greenhouse_client = LiveGreenhouseClient()
        lever_client = LiveLeverClient()
        ashby_client = LiveAshbyClient()
        smartrecruiters_client = LiveSmartRecruitersClient()
        workday_client = LiveWorkdayClient()
        remoteok_client = LiveRemoteOkClient()
        remotive_client = LiveRemotiveClient()
        workingnomads_client = LiveWorkingNomadsClient()
    else:
        jobspy_client = FakeJobSpyClient()
        searxng_client = FakeSearxngClient()
        rss_client = FakeRssClient()
        greenhouse_client = FakeGreenhouseClient()
        lever_client = FakeLeverClient()
        ashby_client = FakeAshbyClient()
        smartrecruiters_client = FakeSmartRecruitersClient()
        workday_client = FakeWorkdayClient()
        remoteok_client = FakeRemoteOkClient()
        remotive_client = FakeRemotiveClient()
        workingnomads_client = FakeWorkingNomadsClient()

    sources = []
    if include_sample:
        sources.append(SampleSource())
    _resolved_stealth = _current_stealth()
    for site in JOBSPY_SITES:
        site_key = f"jobspy:{site}"
        sources.append(
            JobSpySource(
                site=site,
                client=jobspy_client,
                proxy=_proxy_for(site_key),
                escalation_proxy=_escalation_for(site_key),
                escalation_max_retries=(
                    _resolved_stealth.block_max_retries
                    if _resolved_stealth is not None
                    else 1
                ),
                # Live re-read (gap-close): threaded ONLY into the block-prone jobspy
                # boards (the ones a stealth save actually governs, per
                # ``BLOCK_PRONE_SOURCE_PREFIXES``) so a save governs the NEXT fetch
                # without rebuilding this aggregator. ``None`` when the caller wired
                # no ``stealth_provider`` -- byte-identical to before this fix.
                stealth_provider=stealth_provider,
                sessid_provider=sessid_provider,
                flow_sessid=flow_sessid,
            )
        )
    if searxng_client is not None:
        sources.append(
            SearxngSource(client=searxng_client, proxy=_proxy_for("searxng"))
        )
    if include_rss:
        for key, feed_url in RSS_FEEDS.items():
            sources.append(
                RssSource(
                    client=rss_client,
                    feed_url=feed_url,
                    proxy=_proxy_for(key),
                    key=key,
                )
            )
        configured_feeds = rss_feeds or ()
        for idx, feed_url in enumerate(configured_feeds, start=1):
            custom_key = f"{CUSTOM_RSS_KEY_PREFIX}-{idx}"
            sources.append(
                RssSource(
                    client=rss_client,
                    feed_url=feed_url,
                    proxy=_proxy_for(custom_key),
                    key=custom_key,
                )
            )

    # Keyless ATS directory sources (NFR-EXT-1): one Source per configured board
    # token / company slug. Additive -- they never replace the existing registry.
    for key, token in GREENHOUSE_BOARD_TOKENS.items():
        sources.append(GreenhouseSource(client=greenhouse_client, token=token, key=key))
    for token in (greenhouse_boards or ()):
        sources.append(
            GreenhouseSource(
                client=greenhouse_client,
                token=token,
                key=f"greenhouse:{token}",
            )
        )
    for key, company in LEVER_COMPANIES.items():
        sources.append(LeverSource(client=lever_client, company=company, key=key))
    for company in (lever_companies or ()):
        sources.append(
            LeverSource(
                client=lever_client,
                company=company,
                key=f"lever:{company}",
            )
        )
    for key, org in ASHBY_ORGS.items():
        sources.append(AshbySource(client=ashby_client, token=org, key=key))
    for org in (ashby_orgs or ()):
        sources.append(
            AshbySource(client=ashby_client, token=org, key=f"ashby:{org}")
        )
    for key, company in SMARTRECRUITERS_COMPANIES.items():
        sources.append(
            SmartRecruitersSource(client=smartrecruiters_client, company=company, key=key)
        )
    for company in (smartrecruiters_companies or ()):
        sources.append(
            SmartRecruitersSource(
                client=smartrecruiters_client,
                company=company,
                key=f"smartrecruiters:{company}",
            )
        )
    for key, token in WORKDAY_BOARDS.items():
        sources.append(WorkdaySource(client=workday_client, token=token, key=key))
    for token in (workday_boards or ()):
        tenant = token.split("|")[1].strip() if "|" in token else token
        sources.append(
            WorkdaySource(
                client=workday_client,
                token=token,
                key=f"workday:{tenant or token}",
            )
        )

    # EPIC BREADTH: keyless remote-job aggregators (NFR-EXT-1) -- one singleton
    # source each, not a per-company registry loop; see the module-level "include_
    # remoteok/remotive/workingnomads" docstring above.
    if include_remoteok:
        sources.append(RemoteOkSource(client=remoteok_client, key="remoteok"))
    if include_remotive:
        sources.append(RemotiveSource(client=remotive_client, key="remotive"))
    if include_workingnomads:
        sources.append(
            WorkingNomadsSource(client=workingnomads_client, key="workingnomads")
        )

    # EPIC STEALTH (ST-5): human-like per-board pacing conserves residential
    # reputation. Build the aggregator's rate limiter from the stealth pacing
    # knobs when a policy is supplied; otherwise use the aggregator's own default.
    def _rate_config() -> tuple[int, float]:
        # Live re-read (gap-close): re-resolves ``request_rate_per_min`` from the
        # LIVE stealth policy so a save governs the NEXT ``admit()`` call, not just
        # this aggregator-build-time snapshot. Degrades to the snapshot on a
        # provider failure/``None`` result.
        current = _current_stealth()
        if current is None:
            return (_resolved_stealth.rate_max_calls, _resolved_stealth.rate_period_seconds)
        return (current.rate_max_calls, current.rate_period_seconds)

    rate_limiter = None
    if _resolved_stealth is not None:
        rate_limiter = PerBoardRateLimiter(
            max_calls=_resolved_stealth.rate_max_calls,
            period_seconds=_resolved_stealth.rate_period_seconds,
            config_provider=_rate_config if stealth_provider is not None else None,
        )

    return JobSpySearxngDiscovery(
        sources=sources, proxy=proxy, rate_limiter=rate_limiter
    )


def register_persisted_ats_boards(
    aggregator, boards, *, live: bool = False
) -> None:
    """Register persisted user-added ATS boards onto an aggregator, deduped by source_key.

    Env-configured boards (already registered) win: same-key persisted rows are skipped.
    """
    if live:
        greenhouse_client = LiveGreenhouseClient()
        lever_client = LiveLeverClient()
        ashby_client = LiveAshbyClient()
        smartrecruiters_client = LiveSmartRecruitersClient()
        workday_client = LiveWorkdayClient()
    else:
        greenhouse_client = FakeGreenhouseClient()
        lever_client = FakeLeverClient()
        ashby_client = FakeAshbyClient()
        smartrecruiters_client = FakeSmartRecruitersClient()
        workday_client = FakeWorkdayClient()
    for board in boards:
        if board.source_key in aggregator.available_sources():
            continue
        if board.provider == "greenhouse":
            source = GreenhouseSource(
                client=greenhouse_client,
                token=board.token,
                key=board.source_key,
            )
        elif board.provider == "ashby":
            source = AshbySource(
                client=ashby_client,
                token=board.token,
                key=board.source_key,
            )
        elif board.provider == "smartrecruiters":
            source = SmartRecruitersSource(
                client=smartrecruiters_client,
                company=board.token,
                key=board.source_key,
            )
        elif board.provider == "workday":
            source = WorkdaySource(
                client=workday_client,
                token=board.token,
                key=board.source_key,
            )
        else:
            source = LeverSource(
                client=lever_client,
                company=board.token,
                key=board.source_key,
            )
        aggregator.register_source(source, enabled=board.enabled)
