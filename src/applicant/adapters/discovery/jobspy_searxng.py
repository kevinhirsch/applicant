"""JobSpy + SearXNG discovery adapter (FR-DISC-1..6).

A **master aggregator** over the easy boards (python-jobspy:
LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter) plus a **SearXNG metasearch** source,
behind a **pluggable, user-toggleable source registry** (FR-DISC-1/2). Every source is
structured/metasearch scraping that incurs **zero LLM tokens** (FR-DISC-4,
NFR-TOKEN-1). Postings are normalized to the core ``JobPosting`` shape — title, company,
location, work mode, salary, source URL, full description (FR-DISC-3).

Hermeticity (CRITICAL): the real network calls live behind a clearly-marked seam —
``JobSpyClient`` / ``SearxngClient`` — injected into the source. The DEFAULT registry
ships the offline ``SampleSource`` plus the live sources wired to **fake clients**, so
the adapter, its contract test, and the app boot run fully offline with **no network**.
Production wires the real clients (see ``build_default_discovery``); any real-network
test is integration-gated.

Extensibility (NFR-EXT-1): a new board is a new ``Source`` (or a new client behind
``JobSpySource``) registered by key — no core changes. The **proxy hook** (FR-DISC-6) is
a ``ProxyConfig`` seam threaded into every network client without committing to a proxy.
"""

from __future__ import annotations

import inspect
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from applicant.adapters.discovery.clients import GreenhouseClient, LeverClient
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.core.stealth_policy import StealthConfig, is_block_error
from applicant.observability.logging import get_logger

log = get_logger(__name__)


# --- per-board rate limiter (FR-LEARN-6, #195) ----------------------------


@dataclass
class _Bucket:
    tokens: int
    refill_at: float


class PerBoardRateLimiter:
    """Sliding-window token bucket per source key (#195).

    Each source (job board) gets its own bucket: max_calls tokens refilled every
    period_seconds. A source that exceeds its rate is skipped for the remainder
    of the window so a single flaky/aggressive board never hogs the discovery run.
    Separate from the campaign-level/capacity-service LLM rate limiter.
    """

    def __init__(
        self,
        max_calls: int = 5,
        period_seconds: float = 60.0,
        *,
        config_provider: Callable[[], tuple[int, float]] | None = None,
    ) -> None:
        self._max_calls = max_calls
        self._period = period_seconds
        # EPIC STEALTH (live re-read, gap-close): an optional callable re-resolving
        # ``(max_calls, period_seconds)`` from the live Settings > Stealth posture —
        # mirrors ``JobSpySource``'s ``stealth_provider``/``PatchrightBrowser``'s
        # ``egress_provider`` — so a saved ``request_rate_per_min`` governs the NEXT
        # ``admit()`` call without rebuilding the aggregator. ``None`` (every
        # existing caller) keeps the boot-latched limits, byte-identical to before.
        self._config_provider = config_provider
        self._buckets: dict[str, _Bucket] = {}

    def _current_limits(self) -> tuple[int, float]:
        """The ``(max_calls, period_seconds)`` in effect RIGHT NOW.

        A provider failure (or no provider) degrades to the boot-latched limits so
        a transient store read never breaks a scheduled discovery run.
        """
        if self._config_provider is not None:
            try:
                max_calls, period_seconds = self._config_provider()
            except Exception:  # pragma: no cover - defensive: never break a run
                max_calls, period_seconds = None, None
            if max_calls and period_seconds:
                return int(max_calls), float(period_seconds)
        return self._max_calls, self._period

    def admit(self, key: str) -> bool:
        max_calls, period = self._current_limits()
        now = _time.monotonic()
        b = self._buckets.get(key)
        if b is None:
            self._buckets[key] = _Bucket(tokens=max_calls - 1, refill_at=now + period)
            return True
        if now >= b.refill_at:
            self._buckets[key] = _Bucket(tokens=max_calls - 1, refill_at=now + period)
            return True
        if b.tokens > 0:
            self._buckets[key] = _Bucket(tokens=b.tokens - 1, refill_at=b.refill_at)
            return True
        return False

    def reset(self, key: str) -> None:
        self._buckets.pop(key, None)

    def remaining(self, key: str) -> int:
        max_calls, period = self._current_limits()
        now = _time.monotonic()
        b = self._buckets.get(key)
        if b is None:
            return max_calls
        if now >= b.refill_at:
            return max_calls
        return b.tokens


# --- per-source circuit breaker (discovery resilience) ---------------------


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    opened_at: float | None = None


class SourceCircuitBreaker:
    """Per-source circuit breaker guarding against a hard-blocked board.

    A source like Glassdoor/ZipRecruiter that 403s on EVERY tick wastes a full
    scrape attempt every single discovery run forever — the per-board rate
    limiter (``PerBoardRateLimiter``) only throttles *call frequency*, it does
    not notice a source is *reliably failing*. This breaker tracks consecutive
    REAL-failure outcomes per source key (``record``) — the caller passes
    ``ok=True`` for both ``SOURCE_OK`` and a genuinely empty ``SOURCE_EMPTY``
    run (a quiet/low-volume board is not a failure), so only actual errors
    count toward opening. Once a source hits
    ``failure_threshold`` consecutive failures, the breaker "opens" and
    ``allow()`` returns ``False`` for ``cooldown_seconds`` — the caller skips
    ``source.fetch()`` entirely and records a ``SOURCE_COOLDOWN`` outcome
    instead, exactly like a rate-limit skip.

    After the cooldown window elapses the breaker auto-recovers (half-open):
    the next call is allowed through as a probe. A single ``ok`` outcome
    clears the failure count and closes the breaker; a failed probe re-opens
    it and restarts the cooldown clock, so a still-blocked board keeps being
    skipped rather than hammered every tick.
    """

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 1800.0) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._state: dict[str, _BreakerState] = {}

    def allow(self, key: str) -> bool:
        """Whether ``key`` may attempt a fetch this run (closed or half-open)."""
        st = self._state.get(key)
        if st is None or st.opened_at is None:
            return True
        return (_time.monotonic() - st.opened_at) >= self._cooldown

    def record(self, key: str, *, ok: bool) -> None:
        """Record one outcome for ``key`` — ``ok=False`` counts toward opening."""
        st = self._state.setdefault(key, _BreakerState())
        if ok:
            st.consecutive_failures = 0
            st.opened_at = None
            return
        st.consecutive_failures += 1
        if st.consecutive_failures >= self._threshold:
            st.opened_at = _time.monotonic()

    def is_open(self, key: str) -> bool:
        """Whether ``key`` is CURRENTLY open (tripped and still cooling down)."""
        st = self._state.get(key)
        if st is None or st.opened_at is None:
            return False
        return (_time.monotonic() - st.opened_at) < self._cooldown

    def reset(self, key: str) -> None:
        self._state.pop(key, None)


# --- proxy hook seam (FR-DISC-6) ------------------------------------------
@dataclass(frozen=True)
class ProxyConfig:
    """Pluggable proxy hook for hostile boards (FR-DISC-6).

    Designed but **not committed to a proxy**: the default is no proxy. A real
    deployment supplies rotating residential proxies later; clients thread this through
    without any core change. ``as_list`` yields the shape python-jobspy expects.
    """

    proxies: tuple[str, ...] = ()
    enabled: bool = False

    def as_list(self) -> list[str] | None:
        if not self.enabled or not self.proxies:
            return None
        return list(self.proxies)


# --- network boundary clients ---------------------------------------------
@runtime_checkable
class JobSpyClient(Protocol):
    """Marked network boundary over python-jobspy ``scrape_jobs`` (FR-DISC-2/4)."""

    def scrape(self, *, site: str, search_term: str, location: str | None,
               results_wanted: int, proxies: list[str] | None,
               is_remote: bool = False, country_indeed: str | None = None,
               hours_old: int | None = None) -> list[dict]:
        """Return raw normalized-ish dict rows for one board (zero LLM tokens)."""
        ...


@runtime_checkable
class SearxngClient(Protocol):
    """Marked network boundary over a SearXNG instance (FR-DISC-4 metasearch)."""

    def search(self, *, query: str, proxies: list[str] | None) -> list[dict]:
        """Return raw result dicts from a SearXNG metasearch (zero LLM tokens)."""
        ...


def _normalize_work_mode(raw: object) -> str | None:
    """Map a board's loose remote/hybrid/onsite signal to our vocabulary."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "remote" if raw else None
    text = str(raw).strip().lower()
    if text == "true":  # some boards send is_remote as a stringified bool
        return "remote"
    if text == "false":
        return None
    if not text or text in {"nan", "none"}:
        return None
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if any(k in text for k in ("on-site", "onsite", "in person", "in-person", "office")):
        return "onsite"
    return text[:64]  # work_mode column is VARCHAR(64) — clamp arbitrary board text


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


_TRUTHY_STRINGS = frozenset({"true", "1", "yes", "y"})


def detect_easy_apply(raw: dict) -> bool:
    """Server-side Easy-Apply detection for one raw board row (P1-11).

    Detection ONLY — this never drives automation or logins by itself; it just
    tags the posting so the digest/tracker can show the channel per role. Pure,
    zero-token, and deliberately conservative (H-series honesty: a missing
    signal stays untagged rather than guessed):

    1. An explicit truthy ``easy_apply`` attribute on the row wins — the shape
       python-jobspy uses for its Easy-Apply flag, and the shape any future
       source/client can set directly.
    2. LinkedIn rows: when the detail page was actually fetched (a non-empty
       ``description`` proves that) and it exposed NO external apply URL
       (``job_url_direct`` empty), the apply flow is hosted on LinkedIn itself
       — its built-in quick-apply. A row whose detail was never fetched has an
       empty description and is left untagged, never guessed.
    """
    explicit = raw.get("easy_apply")
    if isinstance(explicit, bool):
        return explicit
    if explicit is not None:
        text = str(explicit).strip().lower()
        if text in _TRUTHY_STRINGS:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    url = _clean(raw.get("job_url") or raw.get("source_url") or raw.get("url")) or ""
    if "linkedin.com/jobs" in url.lower():
        has_detail = bool(_clean(raw.get("description")))
        direct = _clean(raw.get("job_url_direct"))
        if has_detail and "job_url_direct" in raw and direct is None:
            return True
    return False


def _clip(value: str | None, limit: int) -> str | None:
    """Truncate a scraped value to its DB column width.

    Board/metasearch rows are external/untrusted and routinely exceed the bounded
    ``job_postings`` VARCHAR columns (e.g. a >512-char title). The in-memory test
    store has no length limit, so this overflow only surfaces on a real Postgres as
    ``StringDataRightTruncation`` — clamp at ingest so it can never reach the DB.
    """
    if value is None:
        return None
    return value[:limit]


def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _parse_posted_date(v):
    """Best-effort parse of a board 'date_posted' -> tz-aware datetime, else None."""
    if v is None:
        return None
    import datetime as _dt
    try:
        if isinstance(v, _dt.datetime):
            return v if v.tzinfo else v.replace(tzinfo=_dt.timezone.utc)
        if isinstance(v, _dt.date):
            return _dt.datetime(v.year, v.month, v.day, tzinfo=_dt.timezone.utc)
        s = str(v).strip()
        if not s or s.lower() in ("nan", "nat", "none", "null"):
            return None
        s = s.replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(s[:19] if ("T" in s or " " in s) else s)
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
    except Exception:
        return None


def normalize_row(
    raw: dict, campaign_id: CampaignId, source_key: str
) -> JobPosting | None:
    """Normalize a raw board/metasearch row to a ``JobPosting`` (FR-DISC-3).

    Pure, zero-token. Returns ``None`` when the row lacks the minimum viable shape
    (a title and a source URL), so junk never reaches the digest.
    """
    title = _clean(raw.get("title"))
    url = _clean(raw.get("job_url") or raw.get("source_url") or raw.get("url"))
    if not title or not url:
        return None
    company = _clean(raw.get("company") or raw.get("company_name")) or ""
    salary = (
        _clean(raw.get("salary"))
        or _format_salary(raw.get("min_amount"), raw.get("max_amount"), raw.get("interval"))
    )
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=campaign_id,
        # Clamp bounded VARCHAR columns to their widths; source_url/description are
        # TEXT (unbounded) so they pass through. (FR-DISC-3; real-DB overflow guard.)
        title=_clip(title, 512),
        company=_clip(company, 512) or "",
        source_url=url,
        location=_clip(_clean(raw.get("location")), 512),
        work_mode=_normalize_work_mode(raw.get("work_mode") or raw.get("is_remote")),
        salary=_clip(salary, 128),
        description=_clean(raw.get("description")) or "",
        source_key=source_key,
        easy_apply=detect_easy_apply(raw),
        first_seen=_now_utc(),
        date_posted=_parse_posted_date(raw.get("date_posted") or raw.get("date")),
    )


def _format_salary(lo: object, hi: object, interval: object) -> str | None:
    lo_c, hi_c = _clean(lo), _clean(hi)
    if not lo_c and not hi_c:
        return None
    unit = f"/{_clean(interval)}" if _clean(interval) else ""
    if lo_c and hi_c:
        return f"{lo_c}-{hi_c}{unit}"
    return f"{lo_c or hi_c}{unit}"


def _matches(criteria: SearchCriteria, title: str, work_mode: str | None) -> bool:
    """Cheap, deterministic, zero-token relevance filter (FR-DISC-3 normalize step)."""
    title_low = title.lower()
    if criteria.titles and not any(t.lower() in title_low for t in criteria.titles):
        if not any(k.lower() in title_low for k in criteria.keywords):
            return False
    if criteria.work_modes and work_mode is not None:
        if work_mode.lower() not in {w.lower() for w in criteria.work_modes}:
            return False
    return True


def _search_term(criteria: SearchCriteria) -> str:
    """Build a board search term from criteria (titles + keywords)."""
    parts = list(criteria.titles) + list(criteria.keywords)
    return " ".join(parts) if parts else (criteria.human_readable or "")


# --- live sources (network boundary injected) ------------------------------
class JobSpySource:
    """One easy board via python-jobspy, behind the ``JobSpyClient`` seam (FR-DISC-2).

    LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter are each a separate registered
    instance (``key="jobspy:indeed"`` etc.) so the user can toggle them individually.
    """

    def __init__(
        self,
        *,
        site: str,
        client: JobSpyClient,
        proxy: ProxyConfig | None = None,
        results_wanted: int = 100,
        escalation_proxy: ProxyConfig | None = None,
        escalation_max_retries: int = 1,
        stealth_provider: Callable[[], StealthConfig | None] | None = None,
        sessid_provider: Callable[[], str | None] | None = None,
        flow_sessid: str | None = None,
    ) -> None:
        self.site = site
        self.key = f"jobspy:{site}"
        self._client = client
        self._proxy = proxy or ProxyConfig()
        self._results_wanted = results_wanted
        # EPIC STEALTH (ST-2): the residential pool to retry through on block-detect
        # (400/403/429/503). ``None`` => no escalation (byte-identical to before).
        self._escalation_proxy = escalation_proxy
        # How many residential retries to attempt on a bot-block before giving up
        # (``discovery_block_max_retries``). >1 is meaningful when the residential
        # exit rotates its IP per attempt (non-sticky). ge 1 when escalation fires.
        self._escalation_max_retries = max(1, escalation_max_retries)
        #: Set True on the fetch when a block-detect escalation actually fired, so a
        #: caller/test can observe that the residential exit was used.
        self.used_escalation = False
        # EPIC STEALTH (live re-read, gap-close): ``proxy``/``escalation_proxy``/
        # ``escalation_max_retries`` above are the value resolved ONCE at aggregator-
        # build time (``factory.build_default_discovery``) — a Settings > Stealth
        # save (per_source_proxy_policy / residential_enabled /
        # residential_sticky_sessid / block_detect_threshold / block_detect_statuses)
        # otherwise needs a restart before it governs this source. An optional
        # ``stealth_provider`` mirrors ``PatchrightBrowser``'s ``egress_provider``: when
        # wired, ``fetch()``/``_maybe_escalate`` re-resolve the effective
        # ``StealthConfig`` (and, via ``sessid_provider``, the live sticky sessid) on
        # EVERY call instead of trusting the frozen constructor args. ``None`` (every
        # existing caller) keeps this byte-identical to before this fix.
        self._stealth_provider = stealth_provider
        self._sessid_provider = sessid_provider
        self._flow_sessid = flow_sessid

    def _current_stealth(self) -> StealthConfig | None:
        """The stealth policy in effect RIGHT NOW (live when a provider is wired).

        Mirrors ``PatchrightBrowser._current_egress``. A provider failure (or no
        provider at all) returns ``None`` so callers fall back to the boot-latched
        ``ProxyConfig``/retry count/default block classifier — a transient store
        read must never break a scheduled discovery run.
        """
        if self._stealth_provider is None:
            return None
        try:
            return self._stealth_provider()
        except Exception:  # pragma: no cover - defensive: never break a fetch
            return None

    def _current_sessid(self) -> str | None:
        """The sticky-session id in effect RIGHT NOW.

        An operator-pinned ``residential_sticky_sessid`` saved AFTER boot wins
        immediately; an empty/failed live read falls back to the STATIC per-boot
        ``flow_sessid`` so a whole discovery run still shares one residential
        identity even when nothing is pinned (rather than a fresh random id per
        fetch, which would defeat sticky-session conservation).
        """
        if self._sessid_provider is not None:
            try:
                live = self._sessid_provider()
            except Exception:  # pragma: no cover - defensive: never break a fetch
                live = None
            if live:
                return live
        return self._flow_sessid

    def _current_proxy(self) -> ProxyConfig:
        """The baseline egress ``ProxyConfig`` for this source RIGHT NOW."""
        stealth = self._current_stealth()
        if stealth is None:
            return self._proxy
        urls = stealth.proxy_urls_for(self.key, sessid=self._current_sessid())
        return ProxyConfig(proxies=tuple(urls), enabled=bool(urls))

    def _current_escalation(self) -> tuple[ProxyConfig | None, int]:
        """The (escalation-pool ``ProxyConfig`` or ``None``, max retries) RIGHT NOW."""
        stealth = self._current_stealth()
        if stealth is None:
            return self._escalation_proxy, self._escalation_max_retries
        sessid = self._current_sessid()
        pool = stealth.escalation_pool(sessid)
        retries = max(1, stealth.block_max_retries)
        if not pool:
            return None, retries
        baseline = stealth.proxy_urls_for(self.key, sessid=sessid)
        if tuple(pool) == tuple(baseline):
            # Already residential at baseline -- nothing to escalate to.
            return None, retries
        return ProxyConfig(proxies=tuple(pool), enabled=True), retries

    def _current_is_block_error(self, exc: Exception) -> bool:
        """Classify ``exc`` as a bot-block using the LIVE ``block_detect_statuses``."""
        stealth = self._current_stealth()
        if stealth is not None:
            return stealth.is_block_error(exc)
        return is_block_error(exc)

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        location = criteria.locations[0] if criteria.locations else None
        # US-remote scoping (FR-DISC): "Remote"/unset is not a jobspy PLACE; default to
        # the US and request remote-only ONLY when the caller didn't state a region --
        # an explicit non-US location (UK/Germany/etc.) must reach ITS OWN country/board,
        # never be silently forced into US-remote-only.
        us_remote_default = not location or location.strip().lower() in (
            "remote", "anywhere", "us remote",
        )
        if us_remote_default:
            location = "United States"
        # H2 (no silent underdelivery): a swallowed fetch failure must stay
        # observable — the aggregator reads ``last_error`` after each fetch so a
        # failed board is reported as *failed*, never as merely empty.
        self.last_error: str | None = None
        scrape_kwargs: dict = dict(
            site=self.site,
            search_term=_search_term(criteria),
            location=location,
            results_wanted=self._results_wanted,
            # Live re-read (gap-close): resolves the LIVE stealth policy when a
            # provider is wired, else the boot-latched ``self._proxy`` (unchanged).
            proxies=self._current_proxy().as_list(),
        )
        # cf25c17be's freshness window applies to every fetch; US-remote scoping only
        # applies when we defaulted the location ourselves.
        extra_kwargs: dict = {"hours_old": 336}  # ~2 weeks: keep the pool FRESH
        if us_remote_default:
            extra_kwargs["is_remote"] = True
            extra_kwargs["country_indeed"] = "usa"
        # These jobspy-specific extras are OPTIONAL on the JobSpyClient Protocol --
        # only pass the ones the injected client's scrape() actually declares, so a
        # lightweight/legacy test double without a **kwargs catch-all is never handed
        # an unexpected keyword argument (which would otherwise misreport a healthy
        # board as SOURCE_ERROR instead of SOURCE_OK).
        try:
            sig_params = inspect.signature(self._client.scrape).parameters
        except (TypeError, ValueError):
            sig_params = {}
        accepts_all_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in sig_params.values()
        )
        for key, value in extra_kwargs.items():
            if accepts_all_kwargs or key in sig_params:
                scrape_kwargs[key] = value
        self.used_escalation = False
        try:
            rows = self._client.scrape(**scrape_kwargs)
        except Exception as exc:  # a flaky board must never crash the whole run
            # EPIC STEALTH (ST-2): on a bot-BLOCK (400/403/429/503) retry ONCE
            # through the residential escalation pool, if configured and not already
            # in use -- so a datacenter/home-IP block on a block-prone board
            # (Glassdoor 400 / ZipRecruiter 403) recovers via the residential exit
            # instead of just reporting SOURCE_ERROR. A non-block error (or no
            # escalation pool) falls through to the existing swallow-and-report path.
            escalated = self._maybe_escalate(exc, scrape_kwargs)
            if escalated is not None:
                rows = escalated
            else:
                log.warning("discovery_source_failed", source=self.key, error=str(exc))
                self.last_error = str(exc)
                return []
        out: list[JobPosting] = []
        for raw in rows:
            posting = normalize_row(raw, campaign_id, self.key)
            if posting is None:
                continue
            if not _matches(criteria, posting.title, posting.work_mode):
                continue
            out.append(posting)
        return out

    def _maybe_escalate(self, exc: Exception, scrape_kwargs: dict) -> list[dict] | None:
        """Retry the scrape through the residential pool on a bot-block (ST-2).

        Returns the retried rows on a successful escalation, or ``None`` to signal
        "not escalated" (no pool, a non-block error, or the escalation itself
        failed) so the caller runs its normal swallow-and-report path. A failed
        escalation records ``last_error`` from the RETRY (the residential attempt
        is the meaningful outcome once we've decided the direct exit is blocked).

        Live re-read (gap-close): the escalation pool, the retry budget AND the
        block-detect classification (``block_detect_statuses``) all resolve from
        the LIVE stealth policy when a provider is wired, so a Settings > Stealth
        save governs the very next block-detect decision without a restart.
        """
        escalation_proxy, escalation_max_retries = self._current_escalation()
        if escalation_proxy is None or not self._current_is_block_error(exc):
            return None
        escalation_list = escalation_proxy.as_list()
        if not escalation_list:
            return None
        retry_kwargs = dict(scrape_kwargs, proxies=escalation_list)
        last_retry_error: Exception | None = None
        for attempt in range(escalation_max_retries):
            try:
                rows = self._client.scrape(**retry_kwargs)
            except Exception as retry_exc:  # residential exit also failed
                last_retry_error = retry_exc
                # Only keep retrying while it's still a block (a hard non-block
                # failure won't be cured by another residential attempt).
                if not self._current_is_block_error(retry_exc):
                    break
                continue
            self.used_escalation = True
            log.info(
                "discovery_escalated_to_residential",
                source=self.key,
                reason=str(exc),
                attempt=attempt + 1,
            )
            return rows
        # Every residential attempt failed -> return None so the caller records the
        # original block as last_error and reports SOURCE_ERROR; log for observability.
        log.warning(
            "discovery_escalation_failed",
            source=self.key,
            error=str(last_retry_error),
            attempts=escalation_max_retries,
        )
        return None


class SearxngSource:
    """SearXNG metasearch source behind the ``SearxngClient`` seam (FR-DISC-4)."""

    def __init__(
        self,
        *,
        client: SearxngClient,
        proxy: ProxyConfig | None = None,
        key: str = "searxng",
    ) -> None:
        self.key = key
        self._client = client
        self._proxy = proxy or ProxyConfig()

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        query = f"{_search_term(criteria)} jobs".strip()
        self.last_error: str | None = None  # H2: see ``JobSpySource.fetch``.
        try:
            rows = self._client.search(query=query, proxies=self._proxy.as_list())
        except Exception as exc:
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
            self.last_error = str(exc)
            return []
        out: list[JobPosting] = []
        for raw in rows:
            posting = normalize_row(raw, campaign_id, self.key)
            if posting is None:
                continue
            if not _matches(criteria, posting.title, posting.work_mode):
                continue
            out.append(posting)
        return out


@runtime_checkable
class RssClient(Protocol):
    """Marked network boundary over an RSS/Atom job feed (FR-DISC-2/4)."""

    def fetch_items(self, *, feed_url: str, proxies: list[str] | None) -> list[dict]:
        """Return raw item dicts from one RSS feed (zero LLM tokens)."""
        ...


class RssSource:
    """An RSS/feed-based discovery source (e.g. HN "Who is hiring", company careers).

    A THIRD discovery source SHAPE proving the abstraction is extensible
    (NFR-EXT-1): a new board/feed is just a new ``Source`` registered by key — NO
    core change. The real HTTP/feed parse lives behind the ``RssClient`` seam, so the
    default lane uses ``FakeRssClient`` and runs fully offline (FR-DISC-4). Toggleable
    per-campaign exactly like every other source (FR-DISC-2).
    """

    def __init__(
        self,
        *,
        client: RssClient,
        feed_url: str,
        proxy: ProxyConfig | None = None,
        key: str = "rss",
    ) -> None:
        self.key = key
        self._client = client
        self._feed_url = feed_url
        self._proxy = proxy or ProxyConfig()

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        self.last_error: str | None = None  # H2: see ``JobSpySource.fetch``.
        try:
            rows = self._client.fetch_items(
                feed_url=self._feed_url, proxies=self._proxy.as_list()
            )
        except Exception as exc:  # a flaky feed must never crash the whole run
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
            self.last_error = str(exc)
            return []
        out: list[JobPosting] = []
        for raw in rows:
            posting = normalize_row(raw, campaign_id, self.key)
            if posting is None:
                continue
            if not _matches(criteria, posting.title, posting.work_mode):
                continue
            out.append(posting)
        return out



class GreenhouseSource:
    """Keyless Greenhouse board discovery source (NFR-EXT-1).

    Fetches every live job from one Greenhouse board token via the
    ``GreenhouseClient`` seam and normalizes rows to ``JobPosting``. Criteria are
    used ONLY for the post-fetch ``_matches`` filter, never to build the request
    (fixed per-company endpoint, exactly like ``RssSource``).
    """

    def __init__(
        self,
        *,
        client: GreenhouseClient,
        token: str,
        key: str = "greenhouse",
    ) -> None:
        self.key = key
        self._client = client
        self._token = token

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        self.last_error: str | None = None  # H2: see ``JobSpySource.fetch``.
        try:
            rows = self._client.fetch_jobs(token=self._token, proxies=None)
        except Exception as exc:  # a flaky board must never crash the whole run
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
            self.last_error = str(exc)
            return []
        out: list[JobPosting] = []
        for raw in rows:
            mapped = _map_greenhouse_job(raw, self._token)
            posting = normalize_row(mapped, campaign_id, self.key)
            if posting is None:
                continue
            if not _matches(criteria, posting.title, posting.work_mode):
                continue
            out.append(posting)
        return out


def _map_greenhouse_job(raw: dict, token: str) -> dict:
    """Flatten a Greenhouse API job dict to the ``normalize_row`` shape.

    ``normalize_row`` does ``str(raw.get("location"))`` with no dict-unwrapping, so
    the nested Greenhouse location object is resolved to its ``name`` here. The board
    payload has no company field, so the configured board token is used as the
    company/display name. Salary/easy-apply are left absent (False default).
    """
    location = raw.get("location") or {}
    return {
        "title": raw.get("title"),
        "company": token,
        "job_url": raw.get("absolute_url"),
        "location": location.get("name") if isinstance(location, dict) else location,
        "description": raw.get("content", ""),
        "date_posted": raw.get("updated_at"),
    }


class LeverSource:
    """Keyless Lever company posting discovery source (NFR-EXT-1).

    Fetches every live posting for one Lever company via the ``LeverClient`` seam
    and normalizes rows to ``JobPosting``. Criteria are used ONLY for the post-fetch
    ``_matches`` filter, never to build the request (fixed company endpoint).
    """

    def __init__(
        self,
        *,
        client: LeverClient,
        company: str,
        key: str = "lever",
    ) -> None:
        self.key = key
        self._client = client
        self._company = company

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        self.last_error: str | None = None  # H2: see ``JobSpySource.fetch``.
        try:
            rows = self._client.fetch_postings(company=self._company, proxies=None)
        except Exception as exc:  # a flaky board must never crash the whole run
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
            self.last_error = str(exc)
            return []
        out: list[JobPosting] = []
        for raw in rows:
            mapped = _map_lever_posting(raw, self._company)
            posting = normalize_row(mapped, campaign_id, self.key)
            if posting is None:
                continue
            if not _matches(criteria, posting.title, posting.work_mode):
                continue
            out.append(posting)
        return out


def _map_lever_posting(raw: dict, company: str) -> dict:
    """Flatten a Lever API posting dict to the ``normalize_row`` shape.

    Lever ``createdAt`` is epoch MILLISECONDS; ``_parse_posted_date`` accepts
    ISO/datetime but not bare ints, so convert to a tz-aware UTC datetime before
    ``normalize_row``. The posting payload has no company field, so the configured
    company slug is used as the company/display name.
    """
    created_ms = raw.get("createdAt")
    date_posted = None
    if isinstance(created_ms, (int, float)) and not isinstance(created_ms, bool):
        try:
            import datetime as _dt

            date_posted = _dt.datetime.fromtimestamp(created_ms / 1000.0, tz=_dt.timezone.utc)
        except Exception:
            date_posted = None
    if date_posted is None and created_ms is not None:
        date_posted = created_ms
    categories = raw.get("categories") or {}
    return {
        "title": raw.get("text"),
        "company": company,
        "job_url": raw.get("hostedUrl") or raw.get("applyUrl"),
        "location": categories.get("location") if isinstance(categories, dict) else categories,
        "work_mode": raw.get("workplaceType"),
        "description": raw.get("descriptionPlain") or raw.get("description", ""),
        "date_posted": date_posted,
    }


@runtime_checkable
class Source(Protocol):
    """A single pluggable discovery source (board / metasearch)."""

    key: str

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        """Return normalized postings for ``criteria`` (zero LLM tokens)."""
        ...


class SampleSource:
    """Offline fake source so discovery runs without network (clearly marked).

    Returns a small, deterministic set of postings filtered against the criteria.
    Real boards (JobSpy, SearXNG) implement the same protocol and replace this in
    production wiring; tests stay offline.
    """

    def __init__(self, key: str = "sample", postings: list[dict] | None = None) -> None:
        self.key = key
        self._raw = postings if postings is not None else self._default_raw()

    @staticmethod
    def _default_raw() -> list[dict]:
        return [
            {
                "title": "Senior Backend Engineer",
                "company": "Acme Corp",
                "location": "Remote (US)",
                "work_mode": "remote",
                "salary": "$180k-$210k",
                "description": "Python, FastAPI, Postgres. Build durable backends.",
                "source_url": "https://example.test/jobs/acme-senior-backend",
            },
            {
                "title": "Staff Software Engineer",
                "company": "Globex",
                "location": "Austin, TX",
                "work_mode": "hybrid",
                "salary": "$200k+",
                "description": "Distributed systems, Go and Python.",
                "source_url": "https://example.test/jobs/globex-staff",
            },
            {
                "title": "Office Manager",
                "company": "Initech",
                "location": "On-site",
                "work_mode": "onsite",
                "salary": None,
                "description": "Administrative role; not engineering.",
                "source_url": "https://example.test/jobs/initech-office",
            },
        ]

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        out: list[JobPosting] = []
        for raw in self._raw:
            if not _matches(criteria, raw["title"], raw.get("work_mode")):
                continue
            out.append(
                JobPosting(
                    id=JobPostingId(new_id()),
                    campaign_id=campaign_id,
                    title=raw["title"],
                    company=raw["company"],
                    source_url=raw["source_url"],
                    location=raw.get("location"),
                    work_mode=raw.get("work_mode"),
                    salary=raw.get("salary"),
                    description=raw.get("description", ""),
                    source_key=self.key,
                    easy_apply=detect_easy_apply(raw),
                )
            )
        return out


@dataclass
class _RegistrySnapshot:
    enabled: dict[str, bool] = field(default_factory=dict)


class JobSpySearxngDiscovery:
    """DiscoveryPort adapter: master aggregator over a pluggable source registry.

    Sources are registered by key and individually enabled/disabled per the user's
    toggles (FR-DISC-2). ``search`` aggregates across all *enabled* sources, then
    normalizes/dedups by ``source_url`` (FR-DISC-3). Per-source counts feed
    source-yield learning (FR-DISC-5) via ``DiscoveryService``.
    """

    def __init__(
        self,
        *,
        sources: list[Source] | None = None,
        proxy: ProxyConfig | None = None,
        proxy_url: str | None = None,
        rate_limiter: PerBoardRateLimiter | None = None,
        circuit_breaker: SourceCircuitBreaker | None = None,
    ) -> None:
        # proxy / proxy_url is the FR-DISC-6 proxy hook (off by default).
        if proxy is None and proxy_url:
            proxy = ProxyConfig(proxies=(proxy_url,), enabled=True)
        self._proxy = proxy or ProxyConfig()
        self._rate_limiter = rate_limiter or PerBoardRateLimiter()
        # Discovery resilience: skip a source that has failed N runs in a row
        # (e.g. a 403-blocked board) instead of re-attempting it every tick.
        self._circuit_breaker = circuit_breaker or SourceCircuitBreaker()
        self._sources: dict[str, Source] = {}
        self._enabled: dict[str, bool] = {}
        # H2 (no silent underdelivery): per-source outcome of the most recent
        # ``search`` call — ``{"source_key", "status", "found", "error"}`` per
        # source queried (statuses from ``core.rules.underdelivery``). Read by
        # ``DiscoveryService`` right after ``search`` returns so an empty,
        # failed, or rate-limit-skipped source is reportable at the item level
        # instead of vanishing into a flat aggregated list.
        self.last_source_outcomes: list[dict] = []
        for src in sources or [SampleSource()]:
            self.register_source(src)

    # --- registry (FR-DISC-1/2) -------------------------------------------
    def register_source(self, source: Source, *, enabled: bool = True) -> None:
        self._sources[source.key] = source
        self._enabled.setdefault(source.key, enabled)

    def unregister_source(self, key: str) -> None:
        if key not in self._sources:
            raise KeyError(f"unknown discovery source: {key}")
        self._sources.pop(key, None)
        self._enabled.pop(key, None)

    def set_source_enabled(self, key: str, enabled: bool) -> None:
        if key not in self._sources:
            raise KeyError(f"unknown discovery source: {key}")
        self._enabled[key] = enabled

    def is_source_enabled(self, key: str) -> bool:
        return self._enabled.get(key, False)

    def available_sources(self) -> list[str]:
        return sorted(self._sources)

    def enabled_sources(self) -> list[str]:
        return sorted(k for k, on in self._enabled.items() if on)

    def apply_toggles(self, toggles: dict[str, bool]) -> None:
        """Apply persisted per-source enable/disable toggles (FR-DISC-2).

        Unknown keys are ignored (a persisted source may not be registered in this
        process), so loading stale ``discovery_sources`` rows never crashes a run.
        """
        for key, on in toggles.items():
            if key in self._sources:
                self._enabled[key] = bool(on)

    # --- aggregation (FR-DISC-3) ------------------------------------------
    def search(
        self,
        campaign_id: CampaignId,
        criteria: SearchCriteria,
        *,
        sources: list[str] | None = None,
    ) -> list[JobPosting]:
        """Aggregate + normalize + dedup across enabled sources (zero LLM tokens).

        ``sources`` (optional) is an ordered, pre-allocated subset of source keys to
        query this run — used by ``DiscoveryService`` to apply learned source-yield
        ranking + the exploration budget (FR-DISC-5/FR-LEARN-6). Any key passed must
        still be enabled; absent it, every enabled source is queried (legacy path).
        """
        from applicant.core.rules.underdelivery import (
            SOURCE_COOLDOWN,
            SOURCE_EMPTY,
            SOURCE_ERROR,
            SOURCE_OK,
            SOURCE_RATE_LIMITED,
        )

        if sources is None:
            keys = self.enabled_sources()
        else:
            enabled = set(self.enabled_sources())
            keys = [k for k in sources if k in enabled]
        seen: set[str] = set()
        aggregated: list[JobPosting] = []
        # H2: record what each queried source actually delivered — reset per
        # call so a stale prior run can never masquerade as this one's outcome.
        outcomes: list[dict] = []
        self.last_source_outcomes = outcomes
        for key in keys:
            # Per-board rate limiter (#195): skip a source that has exceeded its
            # rate-limit window so one aggressive board never hogs the run.
            if not self._rate_limiter.admit(key):
                log.info("rate_limit_skip", source=key)
                outcomes.append(
                    {
                        "source_key": key,
                        "status": SOURCE_RATE_LIMITED,
                        "found": 0,
                        "error": None,
                    }
                )
                continue
            # Circuit breaker (discovery resilience): a source that has failed
            # ``failure_threshold`` runs in a row (e.g. a 403-blocked board) is
            # skipped for a cooldown window instead of wasting another attempt
            # every single tick. Auto-recovers once the cooldown elapses.
            if not self._circuit_breaker.allow(key):
                log.info("circuit_breaker_skip", source=key)
                outcomes.append(
                    {
                        "source_key": key,
                        "status": SOURCE_COOLDOWN,
                        "found": 0,
                        "error": None,
                    }
                )
                continue
            source = self._sources[key]
            found = 0
            for posting in source.fetch(campaign_id, criteria):
                found += 1
                if posting.source_url in seen:
                    continue
                seen.add(posting.source_url)
                aggregated.append(posting)
            # A source that swallowed a fetch failure (returning []) reports it
            # via ``last_error`` — distinguish "failed" from genuinely "empty".
            error = getattr(source, "last_error", None)
            status = SOURCE_ERROR if error else (SOURCE_OK if found else SOURCE_EMPTY)
            # Breaker counts only REAL failures (SOURCE_ERROR) toward opening —
            # a genuinely empty run (SOURCE_EMPTY) is not a failure, it's a
            # quiet/low-volume source, so it resets the streak just like OK.
            self._circuit_breaker.record(key, ok=(status in (SOURCE_OK, SOURCE_EMPTY)))
            outcomes.append(
                {
                    "source_key": key,
                    "status": status,
                    "found": found,
                    "error": str(error) if error else None,
                }
            )
        return aggregated
