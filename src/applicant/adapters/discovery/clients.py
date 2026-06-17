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


def _parse_feed_xml(text: str):
    """Parse an untrusted RSS/Atom feed, guarded against entity-expansion DoS.

    SECURITY: the stdlib ``ElementTree`` parser expands internal entities, so a
    crafted feed could mount a billion-laughs DoS. Prefer ``defusedxml`` (which
    refuses entity/DTD expansion) when installed; otherwise fall back to the
    stdlib parser but first reject any feed declaring a DTD / internal entities.
    """
    try:
        from defusedxml.ElementTree import fromstring as _defused_fromstring
    except ImportError:
        _defused_fromstring = None

    if _defused_fromstring is not None:
        return _defused_fromstring(text)

    # Stdlib fallback: it expands entities, so reject any feed declaring a
    # DTD / internal entities before parsing (billion-laughs DoS guard).
    import xml.etree.ElementTree as ET

    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError(
            "Refusing to parse an RSS/Atom feed declaring a DTD/entities "
            "(entity-expansion DoS guard)."
        )
    return ET.fromstring(text)


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


class LiveRssClient:
    """Real RSS/Atom job-feed client (FR-DISC-2/4).

    Fetches an RSS/Atom feed (e.g. an HN "Who is hiring" or company-careers feed)
    and maps each item into the normalize shape. Parsing is stdlib-only
    (``xml.etree``) so no extra dependency is required for the live path.
    """

    def __init__(self, *, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def fetch_items(self, *, feed_url: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(feed_url)
            resp.raise_for_status()
            text = resp.text
        root = _parse_feed_xml(text)
        rows: list[dict] = []
        # Support both RSS (<item>) and Atom (<entry>) shapes minimally.
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag not in {"item", "entry"}:
                continue
            title = link = desc = None
            for child in item:
                ctag = child.tag.rsplit("}", 1)[-1]
                if ctag == "title":
                    title = (child.text or "").strip()
                elif ctag == "link":
                    link = (child.text or child.get("href") or "").strip()
                elif ctag in {"description", "summary", "content"}:
                    desc = (child.text or "").strip()
            rows.append({"title": title, "url": link, "description": desc})
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


class FakeRssClient:
    """Offline stand-in for an RSS job feed — exercises ``RssSource`` with no network."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = items if items is not None else self._default_items()

    @staticmethod
    def _default_items() -> list[dict]:
        return [
            {
                "title": "Senior Software Engineer (Backend)",
                "company": "HN Startup",
                "url": "https://rss.test/jobs/hn-backend",
                "description": "Python, distributed systems. Remote within US.",
                "work_mode": "remote",
            },
            {
                "title": "Platform Engineer",
                "company": "Careers Feed Co",
                "url": "https://rss.test/jobs/platform",
                "description": "Kubernetes, Go, Terraform. Hybrid.",
                "work_mode": "hybrid",
            },
        ]

    def fetch_items(self, *, feed_url: str, proxies: list[str] | None) -> list[dict]:
        return list(self._items)
