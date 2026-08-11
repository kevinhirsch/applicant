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
import logging
from contextlib import contextmanager
from typing import Protocol

from applicant.core.stealth_policy import is_block_error
from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Explicit default per-request timeout (seconds) for the live discovery clients.
#: Every outbound httpx call MUST be bounded — an unbounded request to a hung
#: SearXNG instance or a stalled RSS endpoint would otherwise wedge a discovery
#: run indefinitely. Per-instance ``timeout=`` overrides this default.
_DEFAULT_HTTP_TIMEOUT = 15.0

#: python-jobspy names its per-board loggers ``JobSpy:{Name}`` (see its own
#: ``create_logger``) with ``propagate=False`` -- so its own error logging never
#: reaches ours. Map our lowercase ``site`` key to that exact logger suffix so
#: ``_capture_jobspy_blocked`` can listen on the right logger (403-miscount fix,
#: discovery resilience).
_JOBSPY_LOGGER_NAMES: dict[str, str] = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "glassdoor": "Glassdoor",
    "google": "Google",
    "zip_recruiter": "ZipRecruiter",
}


class _CapturingHandler(logging.Handler):
    """Collect ERROR-level log records that look like a bot-BLOCK (resilience).

    python-jobspy swallows a hard block (Glassdoor 400 / ZipRecruiter 403 / a
    429 rate-limit / a 503) INSIDE its own scraper: it catches the exception,
    logs it via its own named logger, and returns an empty result with no
    exception raised. Left alone, ``LiveJobSpyClient`` would report that as a
    plain empty scrape, and the caller (``JobSpySource``) would miscount a hard
    block as ``SOURCE_EMPTY`` instead of ``SOURCE_ERROR`` -- understating the
    failure to the source-yield learning system AND skipping the residential
    escalation (EPIC STEALTH ST-2). This handler recovers the swallowed signal by
    listening on the board's own logger for the duration of one scrape call. The
    block classification (400/403/429/503 + anti-bot markers) is shared with the
    escalation decision via ``core.stealth_policy.is_block_error``.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record must never break the scrape
            return
        if is_block_error(message):
            self.messages.append(message)


@contextmanager
def _capture_jobspy_blocked(site: str):
    """Temporarily attach a ``_CapturingHandler`` to ``site``'s own jobspy logger.

    Yields the (initially empty) list of captured 403 messages, mutated in place
    as records arrive; unknown site keys yield a plain empty list (no handler
    attached) so an unrecognized/new board never raises spuriously.
    """
    logger_name = _JOBSPY_LOGGER_NAMES.get(site)
    if logger_name is None:
        yield []
        return
    logger = logging.getLogger(f"JobSpy:{logger_name}")
    handler = _CapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)


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
        is_remote: bool = False,
        country_indeed: str | None = None,
        hours_old: int | None = None,
    ) -> list[dict]:
        from jobspy import scrape_jobs  # lazy: real network dependency

        with _capture_jobspy_blocked(site) as blocked_messages:
            df = scrape_jobs(
                site_name=[site],
                search_term=search_term or None,
                location=location,
                results_wanted=results_wanted,
                proxies=proxies,
                is_remote=is_remote,
                country_indeed=country_indeed or "usa",
                hours_old=hours_old,
            )
        if (df is None or len(df) == 0) and blocked_messages:
            # Block-miscount fix: python-jobspy swallowed the block internally and
            # returned nothing with no exception -- raise so the caller
            # (``JobSpySource.fetch``) records this as SOURCE_ERROR (never the
            # SOURCE_EMPTY a genuinely quiet board would report) AND can escalate to
            # the residential proxy on block-detect (EPIC STEALTH ST-2). The
            # captured message carries the actual code (400/403/429/503).
            raise RuntimeError(
                f"{site} blocked the request (bot-block): {blocked_messages[0]}"
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
        is_remote: bool = False,
        country_indeed: str | None = None,
        hours_old: int | None = None,
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


# --- ATS board clients (Greenhouse + Lever; keyless directory feeds) ------
class GreenhouseClient(Protocol):
    """Marked network boundary over the Greenhouse board API (FR-DISC-2/4)."""

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from one Greenhouse board (zero LLM tokens)."""
        ...


class LiveGreenhouseClient:
    """Real Greenhouse board API client (FR-DISC-2/4).

    Fetches ``https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true``
    and returns the raw ``jobs`` list. Like every live discovery client it is
    network-only and never used in the default offline lane.
    """

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung board API can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                params={"content": "true"},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Greenhouse returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Greenhouse jobs response must be a JSON object")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("Greenhouse jobs response missing a jobs list")
        return jobs


class FakeGreenhouseClient:
    """Offline stand-in for the Greenhouse board API — exercises ``GreenhouseSource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "title": "Senior Backend Engineer",
                "location": {"name": "Remote (US)"},
                "absolute_url": "https://boards.greenhouse.test/acme/senior-backend",
                "content": "Python, FastAPI, Postgres.",
                "updated_at": "2024-01-15T10:00:00Z",
            },
            {
                "title": "Staff Platform Engineer",
                "location": {"name": "Austin, TX"},
                "absolute_url": "https://boards.greenhouse.test/acme/staff-platform",
                "content": "Kubernetes, Go.",
                "updated_at": "2024-01-14T09:00:00Z",
            },
        ]

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)


class LeverClient(Protocol):
    """Marked network boundary over the Lever postings API (FR-DISC-2/4)."""

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        """Return raw posting dicts from one Lever company (zero LLM tokens)."""
        ...


class LiveLeverClient:
    """Real Lever postings API client (FR-DISC-2/4).

    Fetches ``https://api.lever.co/v0/postings/{company}?mode=json`` and returns the
    raw postings list. Network-only; the default lane uses ``FakeLeverClient``.
    """

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung postings API can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(
                f"https://api.lever.co/v0/postings/{company}",
                params={"mode": "json"},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Lever returned non-JSON response: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("Lever postings response must be a JSON array")
        return data


class FakeLeverClient:
    """Offline stand-in for the Lever postings API — exercises ``LeverSource``."""

    def __init__(self, postings: list[dict] | None = None) -> None:
        self._postings = postings if postings is not None else self._default_postings()

    @staticmethod
    def _default_postings() -> list[dict]:
        return [
            {
                "text": "Senior Product Engineer",
                "categories": {"location": "San Francisco, CA"},
                "workplaceType": "hybrid",
                "hostedUrl": "https://jobs.lever.co/acme/1",
                "applyUrl": "https://jobs.lever.co/acme/1/apply",
                "descriptionPlain": "Build products with Python and FastAPI.",
                "createdAt": 1700000000000,
            },
            {
                "text": "DevOps Engineer",
                "categories": {"location": "Remote"},
                "workplaceType": "remote",
                "hostedUrl": "https://jobs.lever.co/acme/2",
                "applyUrl": "https://jobs.lever.co/acme/2/apply",
                "descriptionPlain": "Cloud infrastructure.",
                "createdAt": 1700000000000,
            },
        ]

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        return list(self._postings)


# --- ATS board clients (Workday; keyless CXS search API) -------------------
#: One page of Workday's own job-board widget search (verified live, no auth
#: header needed -- the same request the public career-site widget issues).
_WORKDAY_PAGE_SIZE = 20
#: Bounded page count per fetch (NFR-EXT-1: real coverage, never unbounded). A
#: large enterprise board (e.g. CVS Health, ~19k postings) has far more than this
#: could ever fetch; this connector deliberately trades completeness for a small,
#: predictable number of requests per discovery tick -- exactly the same tradeoff
#: ``LiveSmartRecruitersClient`` documents for its single-page fetch.
_WORKDAY_MAX_PAGES = 5


class WorkdayClient(Protocol):
    """Marked network boundary over a Workday CXS job-search API (NFR-EXT-1)."""

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from one Workday tenant/site board."""
        ...


class LiveWorkdayClient:
    """Real Workday CXS (careers-experience-service) job-search API client.

    Fetches ``POST https://{host}/wday/cxs/{tenant}/{site}/jobs`` -- the exact
    keyless/public request Workday's own embeddable career-site widget issues, no
    API key or session needed (verified live against Wells Fargo, Capital One,
    Fidelity, Cigna, Nationwide, Travelers, USAA, PayPal, Vanguard, Humana, CVS
    Health, Banner Health, Accenture, and Booz Allen Hamilton career sites).

    ``token`` is the compound ``"{host}|{tenant}|{site}[|{display name}]"`` string
    (see ``_map_workday_job`` in ``jobspy_searxng.py``) -- Workday, unlike
    Greenhouse/Lever/Ashby/SmartRecruiters, needs three coordinates (the tenant's
    Workday pod host, the tenant id, and the career-site name) to address one
    board, not a single slug; the pipe-delimited token keeps it a single string so
    it still fits the existing ``dict[str, str]`` board-registry shape (NFR-EXT-1)
    unchanged. A 4th optional segment is a human display name (falls back to the
    tenant id when omitted).

    Pagination: Workday's own ``limit`` caps at 20/page server-side (a larger
    ``limit`` 400s) -- this client pages up to ``_WORKDAY_MAX_PAGES`` (100
    postings) and stops early once a short page signals the end of results.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_HTTP_TIMEOUT,
        max_pages: int = _WORKDAY_MAX_PAGES,
    ) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung board API can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT
        self._max_pages = max_pages or _WORKDAY_MAX_PAGES

    @staticmethod
    def _parse_token(token: str) -> tuple[str, str, str]:
        parts = [p.strip() for p in (token or "").split("|")]
        if len(parts) < 3 or not all(parts[:3]):
            raise ValueError(
                f"Workday token must be 'host|tenant|site[|Display Name]', got {token!r}"
            )
        return parts[0], parts[1], parts[2]

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        host, tenant, site = self._parse_token(token)
        proxy = proxies[0] if proxies else None
        rows: list[dict] = []
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            for page in range(self._max_pages):
                resp = client.post(
                    f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                    json={
                        "appliedFacets": {},
                        "limit": _WORKDAY_PAGE_SIZE,
                        "offset": page * _WORKDAY_PAGE_SIZE,
                        "searchText": "",
                    },
                )
                resp.raise_for_status()
                try:
                    data = resp.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Workday returned non-JSON response: {exc}") from exc
                if not isinstance(data, dict):
                    raise ValueError("Workday jobs response must be a JSON object")
                postings = data.get("jobPostings")
                if not isinstance(postings, list):
                    raise ValueError("Workday jobs response missing a jobPostings list")
                rows.extend(postings)
                if len(postings) < _WORKDAY_PAGE_SIZE:
                    break  # short page: no more results, stop paging early
        return rows


class FakeWorkdayClient:
    """Offline stand-in for the Workday CXS API — exercises ``WorkdaySource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "title": "Scrum Master, Enterprise Delivery",
                "externalPath": "/job/Remote/Scrum-Master--Enterprise-Delivery_R0001",
                "locationsText": "Remote - US",
                "postedOn": "Posted Today",
            },
            {
                "title": "Agile Delivery Program Manager",
                "externalPath": "/job/Columbus-OH/Agile-Delivery-Program-Manager_R0002",
                "locationsText": "Columbus, OH",
                "postedOn": "Posted 3 Days Ago",
            },
        ]

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)


# --- ATS board clients (Ashby; keyless directory feed) --------------------
class AshbyClient(Protocol):
    """Marked network boundary over the Ashby job-board API (FR-DISC-2/4, NFR-EXT-1)."""

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from one Ashby org's public job board."""
        ...


class LiveAshbyClient:
    """Real Ashby job-board API client (FR-DISC-2/4).

    Fetches ``https://api.ashbyhq.com/posting-api/job-board/{org}`` and returns the
    raw ``jobs`` list. Keyless/public (Ashby's own embeddable job-board widget uses
    this exact endpoint) -- no API key needed, same trust model as Greenhouse/Lever.
    Network-only; the default lane uses ``FakeAshbyClient``.
    """

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung board API can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Ashby returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Ashby job-board response must be a JSON object")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("Ashby job-board response missing a jobs list")
        return jobs


class FakeAshbyClient:
    """Offline stand-in for the Ashby job-board API — exercises ``AshbySource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "title": "Technical Program Manager",
                "location": "Remote",
                "isRemote": True,
                "workplaceType": "Remote",
                "jobUrl": "https://jobs.ashbyhq.com/acme/1",
                "applyUrl": "https://jobs.ashbyhq.com/acme/1/application",
                "descriptionPlain": "Drive cross-functional delivery for the platform org.",
                "publishedAt": "2024-01-15T10:00:00.000+00:00",
            },
            {
                "title": "Staff Backend Engineer",
                "location": "San Francisco, CA",
                "isRemote": False,
                "workplaceType": "Hybrid",
                "jobUrl": "https://jobs.ashbyhq.com/acme/2",
                "applyUrl": "https://jobs.ashbyhq.com/acme/2/application",
                "descriptionPlain": "Python, distributed systems.",
                "publishedAt": "2024-01-14T09:00:00.000+00:00",
            },
        ]

    def fetch_jobs(self, *, token: str, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)


# --- ATS board clients (SmartRecruiters; keyless directory feed) ----------
class SmartRecruitersClient(Protocol):
    """Marked network boundary over the SmartRecruiters postings API (NFR-EXT-1)."""

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        """Return raw posting dicts from one SmartRecruiters company (zero LLM tokens)."""
        ...


class LiveSmartRecruitersClient:
    """Real SmartRecruiters postings API client (FR-DISC-2/4).

    Fetches ``https://api.smartrecruiters.com/v1/companies/{company}/postings`` and
    returns the raw ``content`` list. Keyless/public (this is SmartRecruiters' own
    documented public postings feed). Network-only; the default lane uses
    ``FakeSmartRecruitersClient``.

    KNOWN LIMIT (documented, not silently hidden): the API paginates and caps a
    single page at 100 postings server-side regardless of a larger ``limit=``; this
    client fetches ONE page. For every company validated + added by this connector
    that is a real limit, not a hidden truncation -- ``result["found"]`` always
    reports the count actually returned, never a claimed total.
    """

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        # Never allow an unbounded client: fall back to the explicit default when a
        # caller passes None/0 so a hung board API can't wedge the discovery run.
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get(
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                params={"limit": 100},
            )
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"SmartRecruiters returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("SmartRecruiters postings response must be a JSON object")
        content = data.get("content")
        if not isinstance(content, list):
            raise ValueError("SmartRecruiters postings response missing a content list")
        return content


class FakeSmartRecruitersClient:
    """Offline stand-in for the SmartRecruiters postings API — exercises
    ``SmartRecruitersSource``."""

    def __init__(self, postings: list[dict] | None = None) -> None:
        self._postings = postings if postings is not None else self._default_postings()

    @staticmethod
    def _default_postings() -> list[dict]:
        return [
            {
                "id": "1001",
                "name": "Delivery Manager",
                "company": {"identifier": "acme", "name": "Acme Corp"},
                "location": {
                    "city": "Austin",
                    "region": "TX",
                    "country": "us",
                    "remote": False,
                    "fullLocation": "Austin, TX, United States",
                },
                "releasedDate": "2024-01-15T10:00:00.000Z",
            },
            {
                "id": "1002",
                "name": "Scrum Master",
                "company": {"identifier": "acme", "name": "Acme Corp"},
                "location": {
                    "city": None,
                    "region": None,
                    "country": "us",
                    "remote": True,
                    "fullLocation": "Remote, United States",
                },
                "releasedDate": "2024-01-14T09:00:00.000Z",
            },
        ]

    def fetch_postings(self, *, company: str, proxies: list[str] | None) -> list[dict]:
        return list(self._postings)


# --- remote-job AGGREGATOR clients (keyless; index ALL companies/industries) ---
# EPIC BREADTH (Kevin, 2026-08-11): "throw the net as wide as you possibly can...
# prioritize aggregators... we can't limit ourselves to specific industries."
# Unlike Greenhouse/Lever/Ashby/SmartRecruiters/Workday (one source PER COMPANY,
# so reach is bounded by which companies we happen to enumerate), each of these is
# a SINGLE global keyless feed that already indexes postings across many
# companies/industries -- so it surfaces roles at employers we never explicitly
# added. All three were live-verified to return real, non-empty postings before
# being wired in (see ``factory.py``/docs). None supports a working server-side
# search/category filter on free/anonymous access (verified live: Remotive's
# ``search=``/WorkingNomads' ``category=`` params return the identical result set
# regardless of value) -- so, like ``RssSource``, these fetch the current batch and
# rely on the SAME post-fetch ``_matches`` criteria filter every other source uses.


class RemoteOkClient(Protocol):
    """Marked network boundary over the RemoteOK public jobs API (NFR-EXT-1)."""

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from RemoteOK's global feed."""
        ...


class LiveRemoteOkClient:
    """Real RemoteOK API client. Fetches ``https://remoteok.com/api`` (keyless,
    no auth) and returns the raw list, minus its own leading legal-notice row
    (identifiable: it has no ``position`` key, every real job row does)."""

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get("https://remoteok.com/api")
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"RemoteOK returned non-JSON response: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("RemoteOK response must be a JSON array")
        return [row for row in data if isinstance(row, dict) and row.get("position")]


class FakeRemoteOkClient:
    """Offline stand-in for the RemoteOK API — exercises ``RemoteOkSource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "position": "Delivery Manager",
                "company": "Acme Remote Co",
                "url": "https://remoteok.com/remote-jobs/delivery-manager-1",
                "location": "Worldwide",
                "description": "Own delivery for a distributed engineering org.",
                "date": "2024-01-15T10:00:00+00:00",
            },
        ]

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)


class RemotiveClient(Protocol):
    """Marked network boundary over the Remotive public jobs API (NFR-EXT-1)."""

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from Remotive's global feed."""
        ...


class LiveRemotiveClient:
    """Real Remotive API client. Fetches
    ``https://remotive.com/api/remote-jobs`` (keyless, no auth) and returns the
    raw ``jobs`` list."""

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get("https://remotive.com/api/remote-jobs")
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Remotive returned non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Remotive response must be a JSON object")
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("Remotive response missing a jobs list")
        return jobs


class FakeRemotiveClient:
    """Offline stand-in for the Remotive API — exercises ``RemotiveSource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "title": "Technical Program Manager",
                "company_name": "Remotive Test Co",
                "url": "https://remotive.com/remote-jobs/tpm-1",
                "candidate_required_location": "USA",
                "description": "Coordinate cross-team delivery.",
                "publication_date": "2024-01-15T10:00:00",
            },
        ]

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)


class WorkingNomadsClient(Protocol):
    """Marked network boundary over the Working Nomads public jobs API
    (NFR-EXT-1)."""

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        """Return raw job dicts from Working Nomads' global feed."""
        ...


class LiveWorkingNomadsClient:
    """Real Working Nomads API client. Fetches
    ``https://www.workingnomads.com/api/exposed_jobs/`` (keyless, no auth) and
    returns the raw list."""

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        import httpx  # lazy

        proxy = proxies[0] if proxies else None
        with httpx.Client(timeout=self._timeout, proxy=proxy) as client:
            resp = client.get("https://www.workingnomads.com/api/exposed_jobs/")
            resp.raise_for_status()
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Working Nomads returned non-JSON response: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("Working Nomads response must be a JSON array")
        return data


class FakeWorkingNomadsClient:
    """Offline stand-in for the Working Nomads API — exercises
    ``WorkingNomadsSource``."""

    def __init__(self, jobs: list[dict] | None = None) -> None:
        self._jobs = jobs if jobs is not None else self._default_jobs()

    @staticmethod
    def _default_jobs() -> list[dict]:
        return [
            {
                "title": "Agile Program Manager",
                "company_name": "Nomads Test Co",
                "url": "https://www.workingnomads.com/job/go/1/",
                "location": "Remote",
                "description": "Run the agile program across three squads.",
                "pub_date": "2024-01-15T10:00:00Z",
            },
        ]

    def fetch_jobs(self, *, proxies: list[str] | None) -> list[dict]:
        return list(self._jobs)
