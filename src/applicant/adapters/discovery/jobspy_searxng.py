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

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.observability.logging import get_logger

log = get_logger(__name__)


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
               results_wanted: int, proxies: list[str] | None) -> list[dict]:
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
    return text


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


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
        title=title,
        company=company,
        source_url=url,
        location=_clean(raw.get("location")),
        work_mode=_normalize_work_mode(raw.get("work_mode") or raw.get("is_remote")),
        salary=salary,
        description=_clean(raw.get("description")) or "",
        source_key=source_key,
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
        results_wanted: int = 25,
    ) -> None:
        self.site = site
        self.key = f"jobspy:{site}"
        self._client = client
        self._proxy = proxy or ProxyConfig()
        self._results_wanted = results_wanted

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        location = criteria.locations[0] if criteria.locations else None
        try:
            rows = self._client.scrape(
                site=self.site,
                search_term=_search_term(criteria),
                location=location,
                results_wanted=self._results_wanted,
                proxies=self._proxy.as_list(),
            )
        except Exception as exc:  # a flaky board must never crash the whole run
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
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
        try:
            rows = self._client.search(query=query, proxies=self._proxy.as_list())
        except Exception as exc:
            log.warning("discovery_source_failed", source=self.key, error=str(exc))
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
    ) -> None:
        # proxy / proxy_url is the FR-DISC-6 proxy hook (off by default).
        if proxy is None and proxy_url:
            proxy = ProxyConfig(proxies=(proxy_url,), enabled=True)
        self._proxy = proxy or ProxyConfig()
        self._sources: dict[str, Source] = {}
        self._enabled: dict[str, bool] = {}
        for src in sources or [SampleSource()]:
            self.register_source(src)

    # --- registry (FR-DISC-1/2) -------------------------------------------
    def register_source(self, source: Source, *, enabled: bool = True) -> None:
        self._sources[source.key] = source
        self._enabled.setdefault(source.key, enabled)

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
    def search(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        """Aggregate + normalize + dedup across enabled sources (zero LLM tokens)."""
        seen: set[str] = set()
        aggregated: list[JobPosting] = []
        for key in self.enabled_sources():
            for posting in self._sources[key].fetch(campaign_id, criteria):
                if posting.source_url in seen:
                    continue
                seen.add(posting.source_url)
                aggregated.append(posting)
        return aggregated
