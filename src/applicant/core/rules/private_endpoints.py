"""Private/on-box endpoint detection for the local-only privacy mode (P2-11).

One pure predicate answering: *does this base URL stay on the user's own
box or private network?* It is the REFUSAL gate behind ``LLM_LOCAL_ONLY``,
so it is deliberately stricter than the smart-router's local-PREFERENCE
heuristic (which happily substring-matches "ollama" — fine for choosing a
cheaper rung first, unacceptable for a privacy guarantee: it would bless
``https://ollama.example.com``).

Accepted as private:

* loopback / unspecified IPs (``127.0.0.0/8``, ``::1``, ``0.0.0.0``);
* RFC-1918 and link-local IPs (``10/8``, ``172.16/12``, ``192.168/16``,
  ``169.254/16`` — a LAN GPU box counts as "not leaving the user's
  network"), and their IPv6 analogs (unique-local ``fc00::/7``, link-local
  ``fe80::/10``). IPv4-MAPPED IPv6 addresses (``::ffff:a.b.c.d``) are
  unwrapped and judged by the embedded IPv4 — stdlib ``is_private`` for the
  mapped block has shifted across Python versions, and a privacy gate must
  not inherit that drift: ``[::ffff:8.8.8.8]`` refuses on every
  interpreter;
* ``localhost`` and private-use name suffixes (``.local``, ``.lan``,
  ``.internal``, ``.home.arpa``, ``.localhost``);
* single-label hostnames (no dot) — Docker service names on the compose
  network (``http://ollama:11434``) and bare LAN hostnames.

Everything else — any public FQDN or public IP — is not private, whatever
the name contains. Unparseable/empty URLs are not private either
(fail-closed: a URL we cannot classify must not pass a privacy gate).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_PRIVATE_NAME_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localhost")


def is_private_host_url(base_url: str) -> bool:
    """True when ``base_url``'s host is on-box or on a private network."""
    text = (base_url or "").strip()
    if not text:
        return False
    if "//" not in text:
        # urlparse("host:11434") reads "host" as the SCHEME; normalize first.
        text = "//" + text
    try:
        host = (urlparse(text).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost" or host.endswith(_PRIVATE_NAME_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP: a single-label name (no dot) is a Docker-network service
        # or bare LAN host; any dotted name that got here is a public FQDN.
        return "." not in host
    # Judge an IPv4-mapped IPv6 address by its embedded IPv4: stdlib
    # ``is_private`` for ::ffff:0:0/96 varies across Python versions, and this
    # gate must be deterministic on all of them.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
