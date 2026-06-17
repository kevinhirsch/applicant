"""Live discovery client robustness (FR-DISC-2/4).

Hermetic: SearXNG HTTP is faked with ``httpx.MockTransport`` (monkeypatched in)
and the RSS/Atom parser runs on canned XML. No network.
"""

from __future__ import annotations

import httpx

from applicant.adapters.discovery.clients import LiveRssClient, LiveSearxngClient


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
