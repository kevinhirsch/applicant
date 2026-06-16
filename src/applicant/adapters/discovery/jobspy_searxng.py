"""JobSpy + SearXNG discovery adapter (FR-DISC-1..6).

# STAGE B — owned by Phase 1.

A **master aggregator** over easy boards (JobSpy) plus a **pluggable, user-toggleable
source registry** (FR-DISC-1/2) and SearXNG exploratory discovery (FR-DISC-4). Each
registered source is structured/metasearch scraping that incurs **zero LLM tokens**
(FR-DISC-4, NFR-TOKEN-1). Postings are normalized to the core ``JobPosting`` shape
(FR-DISC-3).

Network calls to real boards are deliberately **stubbed**: a clearly-marked offline
``SampleSource`` ships sample postings so the adapter (and its contract test) run fully
offline. Real JobSpy / SearXNG sources register the same ``Source`` protocol; the proxy
hook (FR-DISC-6) is a constructor seam left for Phase 2+.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, JobPostingId, new_id


@runtime_checkable
class Source(Protocol):
    """A single pluggable discovery source (board / metasearch)."""

    key: str

    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        """Return normalized postings for ``criteria`` (zero LLM tokens)."""
        ...


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


class SampleSource:
    """Offline fake source so discovery runs without network (clearly marked).

    Returns a small, deterministic set of postings filtered against the criteria.
    Real boards (LinkedIn/Indeed via JobSpy, SearXNG) implement the same protocol and
    replace this in production wiring; tests stay offline.
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


class JobSpySearxngDiscovery:
    """DiscoveryPort adapter: master aggregator over a pluggable source registry.

    Sources are registered by key and individually enabled/disabled per the user's
    toggles (FR-DISC-2). ``search`` aggregates across all *enabled* sources, then
    normalizes/dedups by ``source_url`` (FR-DISC-3).
    """

    def __init__(
        self,
        *,
        sources: list[Source] | None = None,
        proxy_url: str | None = None,
        offline: bool = True,
    ) -> None:
        # proxy_url is the FR-DISC-6 proxy hook (unused in Stage B offline mode).
        self._proxy_url = proxy_url
        self._offline = offline
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
