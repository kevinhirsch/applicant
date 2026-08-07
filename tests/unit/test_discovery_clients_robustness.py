"""Live discovery client robustness (FR-DISC-2/4).

Hermetic: SearXNG HTTP is faked with ``httpx.MockTransport`` (monkeypatched in)
and the RSS/Atom parser runs on canned XML. No network.
"""

from __future__ import annotations

import httpx

from applicant.adapters.discovery.clients import (
    LiveGreenhouseClient,
    LiveLeverClient,
    LiveRssClient,
    LiveSearxngClient,
)


def _patch_httpx(monkeypatch, handler):
    """Force the lazily-imported ``httpx.Client`` to use a mock transport.

    ``clients.py`` does ``import httpx`` inside each method, so patching the live
    ``httpx.Client`` factory routes the request through the mock transport while
    dropping the unsupported ``proxy=`` kwarg.
    """
    real_client = httpx.Client

    def _factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _factory)


def test_searxng_request_is_bounded_by_explicit_timeout(monkeypatch):
    # Resilience: every live SearXNG request carries an explicit (non-None) read
    # timeout so a hung instance can't wedge the discovery run indefinitely.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200, json={"results": []}, headers={"content-type": "application/json"}
        )

    _patch_httpx(monkeypatch, handler)
    LiveSearxngClient("https://searxng.test", timeout=7.0).search(query="x", proxies=None)
    assert seen["timeout"]["read"] == 7.0
    assert seen["timeout"]["connect"] is not None


def test_searxng_falsy_timeout_falls_back_to_default():
    from applicant.adapters.discovery.clients import _DEFAULT_HTTP_TIMEOUT

    # A None/0 timeout must NOT create an unbounded client.
    assert LiveSearxngClient("https://x.test", timeout=0)._timeout == _DEFAULT_HTTP_TIMEOUT
    assert LiveRssClient(timeout=None)._timeout == _DEFAULT_HTTP_TIMEOUT


def test_searxng_403_returns_empty_and_logs(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>Forbidden</html>", headers={"content-type": "text/html"})

    _patch_httpx(monkeypatch, handler)
    client = LiveSearxngClient("https://searxng.test")
    rows = client.search(query="backend engineer", proxies=None)
    assert rows == []  # handled, did not crash


def test_searxng_non_json_200_returns_empty(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})

    _patch_httpx(monkeypatch, handler)
    client = LiveSearxngClient("https://searxng.test")
    assert client.search(query="x", proxies=None) == []


def test_searxng_valid_json_parses(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "Role", "url": "https://j.test/1", "content": "desc", "engine": "ddg"}]},
            headers={"content-type": "application/json"},
        )

    _patch_httpx(monkeypatch, handler)
    client = LiveSearxngClient("https://searxng.test")
    rows = client.search(query="x", proxies=None)
    assert rows == [
        {"title": "Role", "url": "https://j.test/1", "description": "desc", "company": "ddg"}
    ]


_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Backend Engineer</title>
    <link rel="self" href="https://feed.test/self"/>
    <link rel="alternate" href="https://jobs.test/backend"/>
    <summary>Python role</summary>
  </entry>
</feed>
"""

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Platform Engineer</title>
    <link>https://jobs.test/platform</link>
    <description>Kubernetes role</description>
  </item>
</channel></rss>
"""


def test_atom_prefers_alternate_href(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_ATOM)

    _patch_httpx(monkeypatch, handler)
    rows = LiveRssClient().fetch_items(feed_url="https://feed.test/atom", proxies=None)
    assert rows[0]["url"] == "https://jobs.test/backend"
    assert rows[0]["title"] == "Backend Engineer"


def test_rss_uses_link_text(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_RSS)

    _patch_httpx(monkeypatch, handler)
    rows = LiveRssClient().fetch_items(feed_url="https://feed.test/rss", proxies=None)
    assert rows[0]["url"] == "https://jobs.test/platform"


def test_greenhouse_request_is_bounded_by_explicit_timeout(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200,
            json={"jobs": []},
            headers={"content-type": "application/json"},
        )

    _patch_httpx(monkeypatch, handler)
    LiveGreenhouseClient(timeout=7.0).fetch_jobs(token="acme", proxies=None)
    assert seen["timeout"]["read"] == 7.0
    assert seen["timeout"]["connect"] is not None


def test_greenhouse_falsy_timeout_falls_back_to_default():
    from applicant.adapters.discovery.clients import _DEFAULT_HTTP_TIMEOUT

    assert LiveGreenhouseClient(timeout=0)._timeout == _DEFAULT_HTTP_TIMEOUT
    assert LiveGreenhouseClient(timeout=None)._timeout == _DEFAULT_HTTP_TIMEOUT


def test_greenhouse_malformed_response_raises(monkeypatch):
    # A non-JSON / non-dict Greenhouse payload must raise a clear ValueError rather
    # than silently returning garbage the normalizer cannot handle.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>", headers={"content-type": "text/html"})

    _patch_httpx(monkeypatch, handler)
    try:
        LiveGreenhouseClient().fetch_jobs(token="acme", proxies=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-JSON Greenhouse response")

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"notjobs": "x"}, headers={"content-type": "application/json"})

    _patch_httpx(monkeypatch, handler2)
    try:
        LiveGreenhouseClient().fetch_jobs(token="acme", proxies=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for Greenhouse response missing jobs list")


def test_greenhouse_valid_json_parses_jobs(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jobs": [{"title": "Role", "absolute_url": "https://gh.test/1"}]},
            headers={"content-type": "application/json"},
        )

    _patch_httpx(monkeypatch, handler)
    assert LiveGreenhouseClient().fetch_jobs(token="acme", proxies=None) == [
        {"title": "Role", "absolute_url": "https://gh.test/1"}
    ]


def test_lever_request_is_bounded_by_explicit_timeout(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=[], headers={"content-type": "application/json"})

    _patch_httpx(monkeypatch, handler)
    LiveLeverClient(timeout=7.0).fetch_postings(company="acme", proxies=None)
    assert seen["timeout"]["read"] == 7.0
    assert seen["timeout"]["connect"] is not None


def test_lever_falsy_timeout_falls_back_to_default():
    from applicant.adapters.discovery.clients import _DEFAULT_HTTP_TIMEOUT

    assert LiveLeverClient(timeout=0)._timeout == _DEFAULT_HTTP_TIMEOUT
    assert LiveLeverClient(timeout=None)._timeout == _DEFAULT_HTTP_TIMEOUT


def test_lever_malformed_response_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

    _patch_httpx(monkeypatch, handler)
    try:
        LiveLeverClient().fetch_postings(company="acme", proxies=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-JSON Lever response")

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"notarray": True}, headers={"content-type": "application/json"})

    _patch_httpx(monkeypatch, handler2)
    try:
        LiveLeverClient().fetch_postings(company="acme", proxies=None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non-array Lever response")


def test_lever_valid_json_parses_postings(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"text": "Role", "hostedUrl": "https://lever.test/1"}],
            headers={"content-type": "application/json"},
        )

    _patch_httpx(monkeypatch, handler)
    assert LiveLeverClient().fetch_postings(company="acme", proxies=None) == [
        {"text": "Role", "hostedUrl": "https://lever.test/1"}
    ]
