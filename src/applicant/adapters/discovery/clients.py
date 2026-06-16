"""Real + fake network-boundary clients for discovery (FR-DISC-2/4/6).

This is the **only** module that touches the network for discovery. The live clients
(``LiveJobSpyClient``, ``LiveSearxngClient``) call python-jobspy / a SearXNG instance;
they are NEVER used in the default test lane. The fake clients (``FakeJobSpyClient``,
``FakeSearxngClient``) return canned rows so the live ``JobSpySource`` / ``SearxngSource``
code paths are exercised fully offline (FR-DISC-4 hermeticity).

The proxy hook (FR-DISC-6) is threaded through as a plain ``proxies`` list — no proxy is
committed; ``None`` means direct egress.
"""

from __future__ import annotations

from applicant.observability.logging import get_logger

log = get_logger(__name__)


# --- LIVE clients (network boundary — integration-only) --------------------
class LiveJobSpyClient:
    """Real python-jobspy board scraper (FR-DISC-2/4).

    Imported lazily so the dependency is only needed when a live scrape runs; the
    default lane uses ``FakeJobSpyClient`` and never reaches here.
    """

    def scrape(
        self,
        *,
        site: str,
        search_term: str,
        location: str | None,
        results_wanted: int,
        proxies: list[str] | None,
    ) -> list[dict]:
        from jobspy import scrape_jobs  # lazy: real network dependency

        df = scrape_jobs(
            site_name=[site],
            search_term=search_term or None,
            location=location,
            results_wanted=results_wanted,
            proxies=proxies,
        )
        if df is None or len(df) == 0:
            return []
        # python-jobspy returns a pandas DataFrame; to_dict("records") -> list[dict].
        return df.to_dict("records")


class LiveSearxngClient:
    """Real SearXNG metasearch client over JSON output (FR-DISC-4).

    Hits ``{base_url}/search?format=json``; maps result rows into the normalize shape.
    """

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def search(self, *, query: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "categories": "general"},
            )
            resp.raise_for_status()
            data = resp.json()
        rows: list[dict] = []
        for r in data.get("results", []):
            rows.append(
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "description": r.get("content"),
                    "company": r.get("engine"),
                }
            )
        return rows


# --- FAKE clients (offline; default lane) ----------------------------------
class FakeJobSpyClient:
    """Offline stand-in for python-jobspy — exercises ``JobSpySource`` with no network."""

    def __init__(self, rows_by_site: dict[str, list[dict]] | None = None) -> None:
        self._rows_by_site = rows_by_site or self._default_rows()

    @staticmethod
    def _default_rows() -> dict[str, list[dict]]:
        return {
            "indeed": [
                {
                    "title": "Senior Backend Engineer",
                    "company": "Acme Corp",
                    "location": "Remote, US",
                    "is_remote": True,
                    "min_amount": "$180k",
                    "max_amount": "$210k",
                    "interval": "year",
                    "description": "Python, FastAPI, Postgres.",
                    "job_url": "https://indeed.test/jobs/acme-senior-backend",
                },
            ],
            "linkedin": [
                {
                    "title": "Staff Software Engineer",
                    "company": "Globex",
                    "location": "Austin, TX",
                    "work_mode": "hybrid",
                    "description": "Distributed systems.",
                    "job_url": "https://linkedin.test/jobs/globex-staff",
                },
            ],
        }

    def scrape(
        self,
        *,
        site: str,
        search_term: str,
        location: str | None,
        results_wanted: int,
        proxies: list[str] | None,
    ) -> list[dict]:
        return list(self._rows_by_site.get(site, []))[:results_wanted]


class FakeSearxngClient:
    """Offline stand-in for SearXNG — exercises ``SearxngSource`` with no network."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows if rows is not None else self._default_rows()

    @staticmethod
    def _default_rows() -> list[dict]:
        return [
            {
                "title": "Backend Engineer (Remote)",
                "company": "duckduckgo",
                "url": "https://searxng.test/jobs/remote-backend",
                "description": "Remote Python backend role found via metasearch.",
            },
        ]

    def search(self, *, query: str, proxies: list[str] | None) -> list[dict]:
        return list(self._rows)
