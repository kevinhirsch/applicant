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

from applicant.adapters.browser.page_source import assert_navigable_url
from applicant.core.errors import InvalidInput
from applicant.core.rules.url_safety import (
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
