"""SSRF guard for the untrusted scraped-URL navigation path (SECURITY).

The engine's real browser navigates a scraped job-posting ``source_url`` during
pre-fill. A poisoned posting must not be able to steer that browser at the cloud
metadata endpoint, the internal ``api`` service, or a LAN host (and capture the
response). These tests pin both halves of the guard:

  * ``ip_is_blocked`` — the pure core range-logic (no IO), and
  * ``assert_navigable_url`` — the adapter resolver, exercised hermetically with
    numeric IP literals + ``localhost`` (neither needs network DNS).
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.page_source import (
    PlaywrightPageSource,
    assert_navigable_url,
)
from applicant.core.errors import InvalidInput
from applicant.core.rules.url_safety import (
    ip_chain_is_blocked,
    ip_is_blocked,
    scheme_is_allowed,
)


@pytest.mark.parametrize(
    "addr",
    [
        "169.254.169.254",  # cloud metadata (link-local)
        "::ffff:169.254.169.254",  # IPv6-mapped metadata — must not bypass
        "127.0.0.1",  # loopback
        "::1",  # IPv6 loopback
        "10.0.0.5",  # RFC1918 private
        "172.16.0.1",  # RFC1918 private
        "192.168.1.10",  # RFC1918 private
        "169.254.10.1",  # link-local
        "100.64.0.1",  # shared/CGNAT
        "0.0.0.0",  # unspecified
        "224.0.0.1",  # multicast
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local (private)
        "not-an-ip",  # fail closed on garbage
        "",  # fail closed on empty
    ],
)
def test_ip_is_blocked_rejects_non_public_and_garbage(addr):
    assert ip_is_blocked(addr) is True


@pytest.mark.parametrize(
    "addr",
    [
        "8.8.8.8",  # public unicast IPv4
        "1.1.1.1",  # public unicast IPv4
        "2606:4700:4700::1111",  # public unicast IPv6
    ],
)
def test_ip_is_blocked_allows_public(addr):
    assert ip_is_blocked(addr) is False


def test_scheme_is_allowed():
    assert scheme_is_allowed("http")
    assert scheme_is_allowed("HTTPS")
    for bad in ("file", "gopher", "ftp", "javascript", "data", "", "  "):
        assert not scheme_is_allowed(bad)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/",  # loopback
        "http://localhost/api",  # resolves to loopback (no network needed)
        "http://10.0.0.5/",  # private
        "http://192.168.0.1/admin",  # private
        "file:///etc/passwd",  # non-http(s) scheme
        "gopher://evil/",  # non-http(s) scheme
        "http:///nohost",  # missing host
    ],
)
def test_assert_navigable_url_refuses_unsafe(url):
    with pytest.raises(InvalidInput):
        assert_navigable_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/jobs/123",
        "https://1.1.1.1/postings/abc",
    ],
)
def test_assert_navigable_url_allows_public(url):
    # Returns None (does not raise) for a public destination. Numeric literals
    # resolve via getaddrinfo without touching the network, so this is hermetic.
    assert assert_navigable_url(url) is None


# --- #310: the navigation-wide route guard (redirects + subresources) ----------


def test_ip_chain_is_blocked_any_member_blocks():
    # A host that resolves to several addresses is refused if ANY is non-public.
    assert ip_chain_is_blocked(["8.8.8.8", "169.254.169.254"]) is True
    assert ip_chain_is_blocked(["10.0.0.1"]) is True
    # All-public chain is allowed; an empty chain fails closed.
    assert ip_chain_is_blocked(["8.8.8.8", "1.1.1.1"]) is False
    assert ip_chain_is_blocked([]) is True
    assert ip_chain_is_blocked(None) is True


class _FakeRoute:
    def __init__(self, url: str):
        self.request = type("R", (), {"url": url})()
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


def _guard(url: str) -> _FakeRoute:
    # ``_guard_route`` ignores instance state, so an uninitialized instance is a
    # valid ``self`` — this exercises the real guard without launching a browser.
    route = _FakeRoute(url)
    PlaywrightPageSource._guard_route(object.__new__(PlaywrightPageSource), route)
    return route


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # redirect to metadata
        "http://10.0.0.5/internal-asset.js",  # private subresource
        "http://127.0.0.1:8000/",  # loopback
        "file:///etc/passwd",  # non-http(s) scheme
    ],
)
def test_guard_route_aborts_blocked_hop(url):
    route = _guard(url)
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/jobs/123",
        "https://1.1.1.1/static/app.js",
    ],
)
def test_guard_route_allows_public_hop(url):
    route = _guard(url)
    assert route.continued is True
    assert route.aborted is False
