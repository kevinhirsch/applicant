"""URL-safety rules for UNTRUSTED, attacker-influenced URLs (SECURITY / SSRF).

A scraped job-posting ``source_url`` is attacker-influenced: during pre-fill the
engine's *real* browser navigates it, so a poisoned posting could otherwise steer
that browser at the cloud-metadata endpoint, the internal ``api`` service, or any
LAN host — and capture the response body (server-side request forgery). Unlike
``setup_service.validate_operator_url`` — which intentionally ALLOWS the operator's
own ``localhost``/private Ollama/SearXNG — these rules confine an untrusted URL to
PUBLIC hosts only.

This module is pure (no DNS, no IO) so it stays in the hexagon's core and is
hermetically testable: the browser adapter (which owns the network) resolves the
host to its concrete IP address(es) and asks :func:`ip_is_blocked` about each one.
Splitting it this way keeps the SSRF range-logic under unit test even though the
navigation sink itself is integration-gated.
"""

from __future__ import annotations

import ipaddress

#: The only schemes a browser-navigable URL may use. A scraped value carrying a
#: ``file:``/``gopher:``/``data:``/``javascript:`` scheme is rejected outright.
ALLOWED_URL_SCHEMES = ("http", "https")


def scheme_is_allowed(scheme: str) -> bool:
    """Return True if ``scheme`` is an http(s) scheme safe to navigate."""
    return (scheme or "").strip().lower() in ALLOWED_URL_SCHEMES


def ip_is_blocked(ip_text: str) -> bool:
    """Return True if ``ip_text`` is an address an untrusted URL must NOT reach.

    Blocks every non-public destination — loopback, link-local (incl. the cloud
    metadata address ``169.254.169.254`` and the IPv6 ``fe80::/10`` range), private
    (RFC1918 / ``fc00::/7``), shared/CGNAT, reserved, multicast and the unspecified
    address — and fails CLOSED on anything that is not a valid IP literal. An
    IPv4-mapped IPv6 form (e.g. ``::ffff:169.254.169.254``) is normalized to its
    IPv4 address first so the block cannot be bypassed via the mapped form, and an
    IPv6 zone id (``fe80::1%eth0``) is stripped before parsing. Only a
    globally-routable public unicast address returns ``False`` (navigation allowed).
    """
    text = (ip_text or "").strip().split("%", 1)[0]  # drop any IPv6 zone id
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return True  # not an IP literal => fail closed
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    # ``not is_global`` already covers loopback/link-local/private/reserved/
    # unspecified; the explicit flags are belt-and-suspenders against
    # version-to-version drift in ``is_global``/``is_private`` classification, and
    # ``is_multicast`` is named explicitly (some multicast ranges report global).
    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def ip_chain_is_blocked(ips) -> bool:
    """Return True if ANY address in ``ips`` is a destination an untrusted URL must
    not reach.

    A single host can resolve to several addresses, and a navigation can hop through
    several hosts (redirects) or fan out to several subresources — the request must be
    refused if *any* hop/address is non-public. This is the chain form of
    :func:`ip_is_blocked` used by the browser adapter's per-request route guard so the
    SSRF policy is identical on the entry URL, every redirect, and every subresource
    (not just the first hop). An empty chain is treated as blocked (fail closed).
    """
    addrs = list(ips or [])
    if not addrs:
        return True
    return any(ip_is_blocked(addr) for addr in addrs)
