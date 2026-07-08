"""P1-9 save-a-job-from-any-page: the direct-URL intake lane.

Drives the new ``POST /api/intake/{campaign_id}/url`` router over HTTP against
the in-process app (hermetic: offline fake fetcher, in-memory storage) and pins
the whole capture chain the story promises:

* a pasted URL becomes a persisted, SCORED posting tagged ``added-by-you``;
* a digest-approval pending action appears immediately (so the role shows in
  Pending without waiting for a digest delivery);
* the digest row carries the "added by you" tag;
* duplicates (same URL) are recognized, honestly reported, and never re-added;
* a non-http(s) value is rejected with a plain-language 422;
* both setup gates (LLM + automated work) block the router, like discovery;
* a user-added posting below the viability threshold is KEPT in the digest with
  an honest rationale (service-level), never silently dropped;
* the offline/unreadable-page degrade is HONEST: ``fetched: false`` + a note
  (H-series: the absence of a fetch never renders as a fetch).

Plus direct coverage of the stdlib HTML metadata extractor (JSON-LD / OpenGraph
/ <title> precedence) used by the live fetcher.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from tests.conftest import open_automated_work_gate

URL = "https://boards.example.com/jobs/senior-backend-engineer-1234"


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def gated_client(app):
    """A client with BOTH the LLM gate and the automated-work gate open."""
    with TestClient(app) as c:
        open_automated_work_gate(c)
        yield c


# --- the capture chain --------------------------------------------------------


def test_pasted_url_is_saved_scored_and_tagged_added_by_you(gated_client):
    res = gated_client.post("/api/intake/camp-i1/url", json={"url": URL})
    assert res.status_code == 200
    body = res.json()
    assert body["saved"] is True
    assert body["duplicate"] is False
    assert body["source"] == "added-by-you"
    # Scored through the SAME viability path discovery results take.
    assert isinstance(body["viability_score"], int)
    assert body["why_suggested"]
    # The offline fake fetcher cannot read the page: the degrade is HONEST —
    # a URL-derived title, fetched=False, and a note saying so.
    assert body["fetched"] is False
    assert "couldn't read" in body["note"].lower()
    assert body["title"] == "Senior Backend Engineer"


def test_saved_url_appears_in_pending_immediately(gated_client):
    res = gated_client.post("/api/intake/camp-i2/url", json={"url": URL})
    posting_id = res.json()["posting_id"]
    pending = gated_client.get("/api/pending-actions/camp-i2").json()
    assert pending["count"] == 1
    item = pending["items"][0]
    assert item["kind"] == "digest_approval"
    assert item["payload"]["posting_id"] == posting_id
    assert item["payload"]["link"] == URL


def test_saved_url_appears_in_digest_tagged_added_by_you(gated_client):
    gated_client.post("/api/intake/camp-i3/url", json={"url": URL})
    digest = gated_client.get("/api/digest/camp-i3").json()
    assert digest["empty"] is False
    row = next(r for r in digest["rows"] if r["link"] == URL)
    assert row["added_by_you"] is True
    assert row["source"] == "added-by-you"


def test_same_url_twice_is_reported_as_duplicate_not_readded(gated_client):
    first = gated_client.post("/api/intake/camp-i4/url", json={"url": URL}).json()
    dup = gated_client.post("/api/intake/camp-i4/url", json={"url": URL})
    assert dup.status_code == 200
    body = dup.json()
    assert body["saved"] is False
    assert body["duplicate"] is True
    assert body["posting_id"] == first["posting_id"]
    assert "already being tracked" in body["note"]
    # Still exactly ONE pending item / digest row for it.
    pending = gated_client.get("/api/pending-actions/camp-i4").json()
    assert pending["count"] == 1
    digest = gated_client.get("/api/digest/camp-i4").json()
    assert sum(1 for r in digest["rows"] if r["link"] == URL) == 1


def test_non_http_url_is_rejected_with_plain_language_422(gated_client):
    res = gated_client.post("/api/intake/camp-i5/url", json={"url": "javascript:alert(1)"})
    assert res.status_code == 422
    assert "http" in res.json()["detail"]


def test_router_blocked_before_llm_gate(app):
    with TestClient(app) as c:
        res = c.post("/api/intake/camp-i6/url", json={"url": URL})
        assert res.status_code == 409


def test_router_blocked_before_automated_work_gate(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        res = c.post("/api/intake/camp-i7/url", json={"url": URL})
        assert res.status_code == 409
        assert "Automated work is blocked" in res.json()["detail"]


# --- digest keeps a below-threshold user-added row (service-level) ------------


def test_digest_keeps_user_added_posting_below_threshold():
    from applicant.adapters.storage.in_memory import InMemoryStorage
    from applicant.application.services.digest_service import DigestService
    from applicant.core.entities.job_posting import USER_ADDED_SOURCE_KEY, JobPosting
    from applicant.core.entities.viability_scoring import ViabilityScoring

    class LowScorer:
        def score_posting(self, posting, criteria=None):
            return ViabilityScoring(posting_id=posting.id, score=0.10, rationale="Low match.")

        def is_viable(self, scoring):
            return False  # everything is below threshold

    storage = InMemoryStorage()
    user_added = JobPosting(
        id="p-user", campaign_id="camp-d1", title="Dream Role", company="Acme",
        source_url="https://acme.example/jobs/dream", source_key=USER_ADDED_SOURCE_KEY,
    )
    discovered = JobPosting(
        id="p-disc", campaign_id="camp-d1", title="Other Role", company="Globex",
        source_url="https://globex.example/jobs/other", source_key="indeed",
    )
    storage.postings.add(user_added)
    storage.postings.add(discovered)
    storage.commit()

    rows = DigestService(storage, notification=None, scoring=LowScorer()).build_digest("camp-d1")
    # The discovery-found low scorer is excluded (FR-AGENT-3) — but the
    # user-added one is KEPT, tagged, with an honest why.
    assert [r["posting_id"] for r in rows] == ["p-user"]
    assert rows[0]["added_by_you"] is True
    assert rows[0]["viability_score"] == 10
    assert "you added" in rows[0]["why_suggested"].lower()


# --- the live fetcher's stdlib metadata extractor ------------------------------


def test_extractor_prefers_jsonld_jobposting():
    from applicant.adapters.discovery.url_intake import extract_posting_metadata

    html = """
    <html><head>
      <title>Careers page</title>
      <meta property="og:title" content="OG Title">
      <meta property="og:site_name" content="OG Site">
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"JobPosting",
       "title":"Staff Engineer","hiringOrganization":{"@type":"Organization","name":"Initech"},
       "description":"<p>Build <b>things</b>.</p>",
       "jobLocationType":"TELECOMMUTE",
       "jobLocation":{"@type":"Place","address":{"addressLocality":"Austin","addressRegion":"TX"}}}
      </script>
    </head><body></body></html>
    """
    meta = extract_posting_metadata(html)
    assert meta["title"] == "Staff Engineer"
    assert meta["company"] == "Initech"
    assert meta["description"] == "Build things ."
    assert meta["work_mode"] == "remote"
    assert meta["location"] == "Austin, TX"


def test_extractor_falls_back_to_opengraph_then_title():
    from applicant.adapters.discovery.url_intake import extract_posting_metadata

    og = extract_posting_metadata(
        "<html><head><title>T</title>"
        "<meta property='og:title' content='Backend Engineer - Acme'>"
        "<meta property='og:site_name' content='Acme Careers'>"
        "<meta name='description' content='A backend role.'>"
        "</head></html>"
    )
    assert og["title"] == "Backend Engineer - Acme"
    assert og["company"] == "Acme Careers"
    assert og["description"] == "A backend role."

    bare = extract_posting_metadata("<html><head><title>Just a title</title></head></html>")
    assert bare == {"title": "Just a title"}


def test_service_title_falls_back_to_url_slug():
    from applicant.application.services.intake_service import _title_from_url

    assert _title_from_url("https://x.test/jobs/staff-platform-engineer-99") == "Staff Platform Engineer"
    assert _title_from_url("https://x.test/") == "Job posting at x.test"


# --- SSRF guard on the live fetcher (Greptile finding on #740) ---------------


def test_ssrf_guard_blocks_internal_and_metadata_targets(monkeypatch):
    """Owner-supplied URLs must never let the engine fetch internal services."""
    import socket as _socket

    from applicant.adapters.discovery.url_intake import (
        BlockedFetchTarget,
        _assert_public_http_url,
    )

    def fake_getaddrinfo(host, port, **kwargs):
        table = {
            "api": "172.18.0.4",            # docker service name -> private
            "metadata.internal": "169.254.169.254",  # cloud metadata, link-local
            "localhost": "127.0.0.1",
            "intranet.example": "10.0.0.7",
            "jobs.example": "93.184.216.34",  # public
        }
        ip = table.get(host)
        if ip is None:
            raise _socket.gaierror("unknown host")
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    for bad in (
        "http://api:8000/healthz",
        "http://metadata.internal/latest/meta-data/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:7000/",
        "http://intranet.example/secret",
        "http://10.0.0.7/",
        "ftp://jobs.example/posting",
    ):
        with pytest.raises(BlockedFetchTarget):
            _assert_public_http_url(bad)

    # A public host passes.
    _assert_public_http_url("https://jobs.example/role/123")


def test_live_fetcher_validates_every_redirect_hop(monkeypatch):
    """A public URL that redirects to an internal target must be refused —
    the guard runs per hop, not only on the first URL."""
    import socket as _socket

    from applicant.adapters.discovery import url_intake as mod

    hops: list[str] = []
    real_assert = mod._assert_public_http_url

    def fake_getaddrinfo(host, port, **kwargs):
        ip = {"jobs.example": "93.184.216.34", "api": "172.18.0.4"}.get(host)
        if ip is None:
            raise _socket.gaierror("unknown host")
        return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(_socket, "getaddrinfo", fake_getaddrinfo)

    def tracking_assert(url):
        hops.append(url)
        return real_assert(url)

    monkeypatch.setattr(mod, "_assert_public_http_url", tracking_assert)

    import contextlib

    class _Resp:
        status_code = 302
        headers = {"location": "http://api:8000/internal"}

        def raise_for_status(self):
            pass

        def iter_text(self):
            return iter(())

    class _Client:
        def __init__(self, **kwargs):
            assert kwargs.get("follow_redirects") is False, (
                "the live fetcher must follow redirects MANUALLY so each hop is validated"
            )

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @contextlib.contextmanager
        def stream(self, method, url, **kwargs):
            yield _Resp()

    import httpx

    monkeypatch.setattr(httpx, "Client", _Client)

    fetcher = mod.LiveUrlPostingFetcher()
    with pytest.raises(mod.BlockedFetchTarget):
        fetcher.fetch("https://jobs.example/role/123")
    assert hops == [
        "https://jobs.example/role/123",
        "http://api:8000/internal",
    ], "both the original URL and the redirect target must pass the guard"
