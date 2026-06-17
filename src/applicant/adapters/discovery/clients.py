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

import json

from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Explicit default per-request timeout (seconds) for the live discovery clients.
#: Every outbound httpx call MUST be bounded — an unbounded request to a hung
#: SearXNG instance or a stalled RSS endpoint would otherwise wedge a discovery
#: run indefinitely. Per-instance ``timeout=`` overrides this default.
_DEFAULT_HTTP_TIMEOUT = 15.0


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

    OPERATOR NOTE: SearXNG disables the JSON output format by default and answers
    ``?format=json`` with an HTML 403 page (or 403 status). The instance's
    ``settings.yml`` MUST enable it and set a ``secret_key``::

        search:
          formats: [html, json]
        server:
          secret_key: "<random>"

    The compose/settings file is owned by another lane; this client only detects
    the misconfiguration, logs a clear remediation hint, and returns ``[]`` instead
    of silently yielding nothing or crashing on a JSON-decode error.
    """

    def __init__(self, base_url: str, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung instance can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def search(self, *, query: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "categories": "general"},
            )
        # SearXNG returns 403 (and/or an HTML body) when the json format is not
        # enabled. Detect both the status and a non-JSON content-type, surface a
        # clear, actionable error in the log, and return [] rather than crash.
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 403 or "application/json" not in content_type.lower():
            log.warning(
                "searxng_json_disabled",
                status=resp.status_code,
                content_type=content_type,
                base_url=self._base_url,
                hint=(
                    "SearXNG must enable the JSON output format and set a secret_key "
                    "in settings.yml (search.formats: [html, json]); ?format=json is "
                    "disabled by default and returns 403/HTML."
                ),
            )
            return []
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning(
                "searxng_non_json_response",
                base_url=self._base_url,
                error=str(exc),
                hint="Enable search.formats: [html, json] + secret_key in settings.yml.",
            )
            return []
        if not isinstance(data, dict):
            return []
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

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a stalled feed endpoint can't wedge discovery.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

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
            title = desc = None
            link = None
            link_fallback = None
            for child in item:
                ctag = child.tag.rsplit("}", 1)[-1]
                if ctag == "title":
                    title = (child.text or "").strip()
                elif ctag == "link":
                    # RSS puts the URL in the element text; Atom uses <link href=...>
                    # with a ``rel`` (alternate/self/enclosure). Prefer the
                    # ``rel="alternate"`` href (the human-facing page); fall back to
                    # a rel-less link, then to the element text (RSS).
                    rel = (child.get("rel") or "").strip().lower()
                    href = (child.get("href") or "").strip()
                    candidate = href or (child.text or "").strip()
                    if not candidate:
                        continue
                    if rel == "alternate":
                        link = candidate
                    elif rel in ("", "alternate") or not rel:
                        # rel-less RSS/Atom link: a reasonable fallback.
                        if link_fallback is None:
                            link_fallback = candidate
                    elif link_fallback is None:
                        link_fallback = candidate
                elif ctag in {"description", "summary", "content"}:
                    desc = (child.text or "").strip()
            rows.append({"title": title, "url": link or link_fallback, "description": desc})
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
