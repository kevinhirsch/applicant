"""URL-intake posting fetchers (P1-9 "save a job from any page").

This is the network boundary for the direct-URL intake lane: given ONE posting
URL the user pasted (or bookmarked), fetch the page and extract the posting
metadata (title / company / description / location / work mode) so the intake
service can persist a normalized ``JobPosting`` and run it through the SAME
parse/score path discovery results take.

Mirrors ``clients.py`` exactly: the **live** fetcher (``LiveUrlPostingFetcher``)
is the only thing here that touches the network and is NEVER used in the default
test lane; the **fake** fetcher (``FakeUrlPostingFetcher``) returns canned rows
(or nothing) so the intake code path is exercised fully offline. Extraction is
stdlib-only (``html.parser`` + ``json``) — no new dependency.

A fetcher returns a *partial* metadata dict; the intake service owns every
fallback (deriving a title from the URL itself) and the honesty note about what
was and was not actually read (H-series: the absence of a fetch must never
render as a fetch).
"""

from __future__ import annotations

import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: Explicit default per-request timeout (seconds) — same rationale as
#: ``clients._DEFAULT_HTTP_TIMEOUT``: every outbound call MUST be bounded so a
#: hung posting page can never wedge the intake request.
_DEFAULT_HTTP_TIMEOUT = 15.0

#: Hard cap on how much of the page body is parsed. Posting pages are normally
#: tens of KB; a pathological multi-MB page is truncated rather than parsed whole.
_MAX_HTML_CHARS = 500_000

#: Bound on the description carried onto the posting (the scorer neutralizes and
#: bounds its prompts anyway; this keeps the stored row sane).
_MAX_DESCRIPTION_CHARS = 8_000


class _PostingHTMLExtractor(HTMLParser):
    """Collect <title>, the relevant <meta> tags, and JSON-LD blobs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.jsonld_blobs: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (attrs_d.get("property") or attrs_d.get("name") or "").strip().lower()
            content = (attrs_d.get("content") or "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "script" and "ld+json" in (attrs_d.get("type") or "").lower():
            self._in_jsonld = True
            self._jsonld_parts = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            blob = "".join(self._jsonld_parts).strip()
            if blob:
                self.jsonld_blobs.append(blob)

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_jsonld:
            self._jsonld_parts.append(data)


def _strip_tags(text: str) -> str:
    """Plain text out of an HTML fragment (JSON-LD descriptions embed markup)."""

    class _S(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data):
            self.parts.append(data)

    s = _S()
    try:
        s.feed(text)
        return " ".join(" ".join(s.parts).split())
    except Exception:  # pragma: no cover - defensive
        return text


def _iter_jsonld_nodes(parsed):
    """Yield every dict node in a JSON-LD document (top level, lists, @graph)."""
    if isinstance(parsed, dict):
        yield parsed
        graph = parsed.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict):
                    yield node
    elif isinstance(parsed, list):
        for node in parsed:
            if isinstance(node, dict):
                yield from _iter_jsonld_nodes(node)


def _jobposting_from_jsonld(blobs: list[str]) -> dict:
    """Extract schema.org JobPosting fields from JSON-LD blobs (best-effort)."""
    for blob in blobs:
        try:
            parsed = json.loads(blob)
        except Exception:
            continue
        for node in _iter_jsonld_nodes(parsed):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if not any(str(t or "").lower() == "jobposting" for t in types):
                continue
            out: dict = {}
            title = str(node.get("title") or "").strip()
            if title:
                out["title"] = title
            org = node.get("hiringOrganization")
            if isinstance(org, dict):
                company = str(org.get("name") or "").strip()
                if company:
                    out["company"] = company
            elif isinstance(org, str) and org.strip():
                out["company"] = org.strip()
            desc = str(node.get("description") or "").strip()
            if desc:
                out["description"] = _strip_tags(desc)
            loc_type = str(node.get("jobLocationType") or "").strip().upper()
            if loc_type == "TELECOMMUTE":
                out["work_mode"] = "remote"
            loc = node.get("jobLocation")
            loc_nodes = loc if isinstance(loc, list) else [loc]
            for ln in loc_nodes:
                if not isinstance(ln, dict):
                    continue
                addr = ln.get("address")
                if isinstance(addr, dict):
                    bits = [
                        str(addr.get(k) or "").strip()
                        for k in ("addressLocality", "addressRegion", "addressCountry")
                    ]
                    place = ", ".join(b for b in bits if b)
                    if place:
                        out["location"] = place
                        break
            salary = node.get("baseSalary")
            if isinstance(salary, dict):
                value = salary.get("value")
                if isinstance(value, dict):
                    lo, hi = value.get("minValue"), value.get("maxValue")
                    unit = str(value.get("unitText") or "").lower()
                    if lo and hi:
                        out["salary"] = f"{lo}-{hi}" + (f" per {unit}" if unit else "")
            if out:
                return out
    return {}


def extract_posting_metadata(html_text: str) -> dict:
    """Posting metadata out of a page's HTML (stdlib-only, best-effort).

    Precedence per field: schema.org JSON-LD ``JobPosting`` (the structured
    source most ATS pages emit) > OpenGraph metas > plain <title>/description
    meta. Returns only the fields it actually found — never fabricated values.
    """
    extractor = _PostingHTMLExtractor()
    try:
        extractor.feed(html_text[:_MAX_HTML_CHARS])
    except Exception:  # pragma: no cover - malformed HTML degrades to whatever parsed
        pass
    meta = extractor.meta
    out = _jobposting_from_jsonld(extractor.jsonld_blobs)
    if "title" not in out:
        title = (
            meta.get("og:title")
            or meta.get("twitter:title")
            or " ".join("".join(extractor.title_parts).split())
        ).strip()
        if title:
            out["title"] = title
    if "company" not in out:
        company = (meta.get("og:site_name") or "").strip()
        if company:
            out["company"] = company
    if "description" not in out:
        desc = (meta.get("og:description") or meta.get("description") or "").strip()
        if desc:
            out["description"] = desc
    if "description" in out:
        out["description"] = out["description"][:_MAX_DESCRIPTION_CHARS]
    return out


#: Bound on how many redirect hops the live fetcher follows — each hop is
#: re-validated by the SSRF guard below, so a public page can never bounce the
#: request onto an internal service.
_MAX_REDIRECTS = 5


class BlockedFetchTarget(ValueError):
    """The URL (or a redirect hop) points at a non-public network target."""


def _assert_public_http_url(url: str) -> None:
    """SSRF guard for the live URL-intake fetch (server-side, per CLAUDE.md).

    The URL is owner-supplied, but the fetch runs FROM the engine container —
    without this, ``http://api:8000/...``, ``http://169.254.169.254/...`` (cloud
    metadata), or a public URL that *redirects* there would let the intake lane
    reach internal services. Every address the hostname resolves to must be
    globally routable; anything private/loopback/link-local/reserved is refused.
    (Residual DNS-rebinding TOCTOU is out of scope for this guard — the fetch is
    a single bounded GET and the result is only ever parsed as posting text.)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedFetchTarget(f"unsupported scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise BlockedFetchTarget("URL carries no hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise BlockedFetchTarget(f"hostname does not resolve: {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise BlockedFetchTarget(
                f"refusing to fetch a non-public address ({host!r} -> {ip})"
            )


# --- LIVE fetcher (network boundary — live deployments only) -----------------
class LiveUrlPostingFetcher:
    """Real single-URL page fetcher (P1-9). Only used when DISCOVERY_LIVE is on —
    the default lane uses :class:`FakeUrlPostingFetcher` and never touches the
    network (FR-DISC-4 hermeticity)."""

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT, proxies: tuple[str, ...] = ()) -> None:
        self._timeout = timeout or _DEFAULT_HTTP_TIMEOUT
        self._proxies = proxies

    def fetch(self, url: str) -> dict:
        import httpx  # lazy: real network dependency

        proxy = self._proxies[0] if self._proxies else None
        # Redirects are followed MANUALLY so every hop passes the SSRF guard —
        # httpx's auto-follow would happily bounce a public posting URL onto an
        # internal service before we ever saw the Location header.
        with httpx.Client(
            timeout=self._timeout, proxy=proxy, follow_redirects=False
        ) as client:
            target = url
            resp = None
            for _hop in range(_MAX_REDIRECTS + 1):
                _assert_public_http_url(target)
                resp = client.get(target, headers={"Accept": "text/html,application/xhtml+xml"})
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location", "")
                    if not loc:
                        break
                    target = str(httpx.URL(target).join(loc))
                    continue
                break
            else:
                log.warning("url_intake_too_many_redirects", url=url)
                return {}
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type.lower():
                log.warning("url_intake_non_html", url=url, content_type=content_type)
                return {}
            return extract_posting_metadata(resp.text)


# --- FAKE fetcher (offline; default lane) ------------------------------------
class FakeUrlPostingFetcher:
    """Offline stand-in — canned metadata per URL, or nothing (the intake
    service then derives an honest, clearly-degraded row from the URL itself)."""

    def __init__(self, rows_by_url: dict[str, dict] | None = None) -> None:
        self._rows_by_url = rows_by_url or {}

    def fetch(self, url: str) -> dict:
        return dict(self._rows_by_url.get(url, {}))
