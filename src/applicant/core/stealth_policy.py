"""Stealth egress policy for discovery (EPIC STEALTH — ST-2/ST-5).

A pure, dependency-free policy layer that decides WHICH egress each discovery
source uses, so residential-proxy bandwidth (and residential IP reputation) is
spent ONLY on the block-prone scrape sources and on block-detect — never on the
keyless ATS directories / structured APIs that egress cleanly on the free
network-layer VPS WireGuard exit (ST-1).

Principle (Kevin, EPIC STEALTH): "We need stealth. We cannot be detected at all.
Our residential IP score MUST be protected." Automation must never egress from
the home IP, hard anti-bot targets (LinkedIn/Indeed/Glassdoor/ZipRecruiter/
Google via python-jobspy) go through a residential proxy with a matched
fingerprint + human-like pacing, and residential bandwidth is conserved (sticky
per flow, selective, paced — never burned).

This module is the DECISION layer only — it never touches the network. The
discovery adapters (``adapters/discovery/factory.py`` +
``adapters/discovery/jobspy_searxng.py``) apply the resolved proxy through the
existing ``ProxyConfig`` seam. It lives in ``core`` (imported by the adapters and
the app-config layer) and imports nothing from ``adapters``/``app`` so the
hexagonal layering (NFR-ARCH-1) holds.

Everything here is a preset DEFAULT that is CHANGEABLE in the Settings UI (the
values are threaded from ``app.config.Settings`` at wiring time).
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# --- per-source proxy policy (ST-2/ST-5) -----------------------------------
#: ``direct``      — no HTTP proxy; egress via the host's own path (which on the
#:                   live engine is already the VPS WireGuard exit at the network
#:                   layer, ST-1). The right choice for keyless ATS + structured
#:                   APIs + your own SearXNG (zero residential GB burned).
#: ``vps``         — an explicit VPS-side HTTP proxy URL when one is exposed; when
#:                   no ``vps_proxy_url`` is configured this is equivalent to
#:                   ``direct`` (the WG exit already covers it at the net layer).
#: ``residential`` — thread the attested residential forwarder (DataImpulse via
#:                   the VPS tunnel) so a hard anti-bot target sees a residential
#:                   IP. Used SELECTIVELY: block-prone scrape sources + on
#:                   block-detect escalation only.
PROXY_POLICY_DIRECT = "direct"
PROXY_POLICY_VPS = "vps"
PROXY_POLICY_RESIDENTIAL = "residential"
PROXY_POLICIES = (
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_VPS,
    PROXY_POLICY_RESIDENTIAL,
)

#: Discovery source-key prefixes that are BLOCK-PRONE (aggressive anti-bot: they
#: 400/403/429 a datacenter/home IP). Every ``JobSpySource`` registers as
#: ``jobspy:{site}`` (see ``adapters/discovery/jobspy_searxng.py``), so the whole
#: python-jobspy family is captured by the one prefix. Keyless ATS
#: (``greenhouse:*``/``lever:*``), custom RSS (``rss:*``), your own SearXNG
#: (``searxng``) and the offline ``sample`` source are intentionally NOT here —
#: they egress direct and never burn residential GB.
BLOCK_PRONE_SOURCE_PREFIXES: tuple[str, ...] = ("jobspy:",)

#: The exact python-jobspy sites that are block-prone (documented; the backlog's
#: ST-2 list). These are the boards whose blocks (Glassdoor 400 / ZipRecruiter
#: 403) motivated EPIC STEALTH.
BLOCK_PRONE_JOBSPY_SITES: tuple[str, ...] = (
    "linkedin",
    "indeed",
    "glassdoor",
    "google",
    "zip_recruiter",
)

#: HTTP status codes that signal a bot-block / rate-limit / throttle (the
#: block-detect set from the workstream: 400/403/429/503). A source that fails
#: with one of these — when a residential escalation pool exists and it is not
#: already residential — retries once through the residential proxy.
BLOCK_STATUS_CODES: frozenset[int] = frozenset({400, 403, 429, 503})

#: Substrings in an error message that indicate a block even when no numeric
#: status is available (python-jobspy swallows the HTTP layer and re-raises a
#: plain ``RuntimeError`` whose text carries the code / anti-bot vendor name).
_BLOCK_MARKERS: tuple[str, ...] = (
    "403",
    "429",
    "503",
    "400",
    "blocked",
    "forbidden",
    "too many requests",
    "rate limit",
    "rate-limit",
    "captcha",
    "cloudflare",
    "datadome",
    "perimeterx",
    "access denied",
    "unusual traffic",
    "bot detected",
)

#: Default DataImpulse sticky-session label injected into the proxy username
#: (``user-sessid-<id>``). ``{sessid}`` is substituted per flow.
DEFAULT_SESSID_LABEL = "sessid-{sessid}"


def is_block_prone(source_key: str) -> bool:
    """True when ``source_key`` is an aggressive anti-bot scrape source."""
    key = (source_key or "").strip().lower()
    return any(key.startswith(p) for p in BLOCK_PRONE_SOURCE_PREFIXES)


def is_block_error(error: object) -> bool:
    """Classify an exception / status as a bot-block (400/403/429/503 + markers).

    Best-effort and dependency-free: reads a numeric ``status``/``status_code``
    (directly or off a ``.response``) when present, else scans the string form
    for a block status code or a known anti-bot vendor marker. Used to decide
    whether a failed block-prone fetch should escalate to the residential proxy.
    """
    if error is None:
        return False
    # 1) an explicit int status code.
    if isinstance(error, bool):  # guard: bool is an int subclass
        return False
    if isinstance(error, int):
        return error in BLOCK_STATUS_CODES
    # 2) a status attribute on the exception (httpx.HTTPStatusError.response, or
    #    a plain ``.status_code`` on some client errors).
    for attr in ("status_code", "status"):
        code = getattr(error, attr, None)
        if isinstance(code, int) and not isinstance(code, bool) and code in BLOCK_STATUS_CODES:
            return True
    response = getattr(error, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int) and not isinstance(code, bool) and code in BLOCK_STATUS_CODES:
            return True
    # 3) fall back to a marker scan of the string form.
    text = str(error).lower()
    return any(marker in text for marker in _BLOCK_MARKERS)


def parse_source_proxy_policy(value: object) -> dict[str, str]:
    """Parse a ``key=policy,key2=policy2`` override string into a dict.

    Mirrors the comma-separated shape ``container.py`` uses for
    ``discovery_proxies``/``discovery_rss_feeds``. Whitespace is stripped; the
    policy is lower-cased and validated against :data:`PROXY_POLICIES` (an unknown
    policy raises so a typo is rejected at load, matching the config validators).
    A ``Mapping`` is accepted as-is (validated the same way). Empty ⇒ ``{}``.
    """
    if value is None:
        return {}
    items: list[tuple[str, str]]
    if isinstance(value, Mapping):
        items = [(str(k), str(v)) for k, v in value.items()]
    else:
        items = []
        for chunk in str(value).split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" not in chunk:
                raise ValueError(
                    f"invalid source proxy policy entry {chunk!r}; "
                    "expected 'source_key=policy'"
                )
            key, _, policy = chunk.partition("=")
            items.append((key, policy))
    out: dict[str, str] = {}
    for key, policy in items:
        key_norm = key.strip()
        policy_norm = policy.strip().lower()
        if not key_norm:
            continue
        if policy_norm not in PROXY_POLICIES:
            raise ValueError(
                f"invalid proxy policy {policy!r} for {key_norm!r}; "
                f"choose one of {PROXY_POLICIES}"
            )
        out[key_norm] = policy_norm
    return out


def new_sessid(flow_key: str | None = None) -> str:
    """A sticky-session id for one flow (DataImpulse ``sessid`` label body).

    A deterministic short id derived from ``flow_key`` when given (so the SAME
    flow — a discovery run, or browse→apply — reuses the SAME residential IP for
    the forwarder's ~30-min hold), else a fresh random id. Hex, 12 chars.
    """
    if flow_key:
        return hashlib.sha1(flow_key.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - label id, not security
    return secrets.token_hex(6)


def apply_sessid(
    proxy_url: str, sessid: str | None, *, label_format: str = DEFAULT_SESSID_LABEL
) -> str:
    """Decorate ``proxy_url`` with a sticky-session label in its username.

    DataImpulse threads sticky sessions through a username label
    (``user-sessid-<id>``). When the URL already carries userinfo the label is
    appended to the username (password preserved); when it has none the label
    becomes the username. A blank ``proxy_url``/``sessid`` is returned unchanged.
    Pure + deterministic so the offline lane can assert the exact decorated URL.
    """
    if not proxy_url or not sessid:
        return proxy_url
    label = label_format.format(sessid=sessid)
    parts = urlsplit(proxy_url)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        if ":" in userinfo:
            user, _, pwd = userinfo.partition(":")
            new_user = f"{user}-{label}" if user else label
            new_userinfo = f"{new_user}:{pwd}"
        else:
            new_userinfo = f"{userinfo}-{label}" if userinfo else label
        new_netloc = f"{new_userinfo}@{hostport}"
    else:
        new_netloc = f"{label}@{netloc}"
    return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))


@dataclass(frozen=True)
class StealthConfig:
    """Resolved stealth egress policy (all preset DEFAULTS, all overridable).

    Bundles the residential/VPS exits, the per-source proxy policy, sticky-session
    behaviour and scraper pacing/backoff into one value the discovery factory
    consumes. Built from ``app.config.Settings`` at wiring time via
    :func:`build_stealth_config` (kept plain-kwarg so ``core`` never imports the
    app-config layer). When a ``StealthConfig`` is NOT supplied to the factory the
    discovery path is byte-identical to before this epic.
    """

    # -- exits ---------------------------------------------------------------
    residential_proxy_url: str = ""
    residential_proxy_enabled: bool = True
    vps_proxy_url: str = ""
    #: Extra residential proxies (e.g. an operator-supplied ``DISCOVERY_PROXIES``
    #: pool) merged with ``residential_proxy_url`` for the residential policy.
    extra_residential_proxies: tuple[str, ...] = ()

    # -- per-source policy ---------------------------------------------------
    block_prone_policy: str = PROXY_POLICY_RESIDENTIAL
    default_policy: str = PROXY_POLICY_DIRECT
    source_policy_overrides: Mapping[str, str] = field(default_factory=dict)

    # -- sticky sessions -----------------------------------------------------
    sticky_sessions: bool = True
    sessid_label: str = DEFAULT_SESSID_LABEL

    # -- pacing / rate-limit / backoff (scrapers) ----------------------------
    rate_max_calls: int = 5
    rate_period_seconds: float = 60.0
    min_request_interval_seconds: float = 2.0
    backoff_base_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 60.0
    block_max_retries: int = 1

    # -- resolution ----------------------------------------------------------
    def policy_for(self, source_key: str) -> str:
        """The effective proxy policy for ``source_key``.

        An explicit per-source override wins; otherwise block-prone sources get
        ``block_prone_policy`` and everything else ``default_policy``. A
        ``residential`` decision is DOWNGRADED to ``vps`` when residential proxy
        use is disabled (or no residential URL is configured) — so turning
        residential off never silently forces the home/datacenter IP into a hard
        target, it falls back to the free network-layer exit.
        """
        override = self.source_policy_overrides.get(source_key)
        if override:
            policy = override
        elif is_block_prone(source_key):
            policy = self.block_prone_policy
        else:
            policy = self.default_policy
        if policy == PROXY_POLICY_RESIDENTIAL and not self._residential_available():
            return PROXY_POLICY_VPS
        return policy

    def _residential_available(self) -> bool:
        return self.residential_proxy_enabled and bool(
            (self.residential_proxy_url or "").strip() or self.extra_residential_proxies
        )

    def _residential_pool(self, sessid: str | None) -> tuple[str, ...]:
        pool: list[str] = []
        if (self.residential_proxy_url or "").strip():
            pool.append(self.residential_proxy_url.strip())
        pool.extend(p for p in self.extra_residential_proxies if p and p.strip())
        if self.sticky_sessions and sessid:
            pool = [
                apply_sessid(p, sessid, label_format=self.sessid_label) for p in pool
            ]
        return tuple(pool)

    def proxy_urls_for(
        self, source_key: str, *, sessid: str | None = None
    ) -> tuple[str, ...]:
        """The proxy URL tuple to apply to ``source_key`` (empty ⇒ direct).

        Resolves the source's policy then materializes it into concrete proxy
        URLs (residential pool, VPS URL, or nothing for direct). The tuple feeds
        the existing ``ProxyConfig(proxies=..., enabled=bool(...))`` seam.
        """
        policy = self.policy_for(source_key)
        if policy == PROXY_POLICY_RESIDENTIAL:
            return self._residential_pool(sessid)
        if policy == PROXY_POLICY_VPS:
            url = (self.vps_proxy_url or "").strip()
            return (url,) if url else ()
        return ()

    def escalation_pool(self, sessid: str | None = None) -> tuple[str, ...]:
        """Residential proxies to escalate to on block-detect (empty ⇒ none).

        This is the residential pool regardless of a source's baseline policy —
        it's the "on block-detect (400/403/429/503)" leg from the workstream: a
        block-prone source starting on ``vps``/``direct`` retries once through the
        residential exit when it is actually blocked. Empty when residential use
        is disabled/unconfigured (nothing to escalate to).
        """
        if not self._residential_available():
            return ()
        return self._residential_pool(sessid)

    def backoff_delay(self, attempt: int) -> float:
        """Exponential backoff delay (seconds) for retry ``attempt`` (0-indexed).

        ``base * multiplier**attempt``, clamped to ``backoff_max_seconds``. Pure
        so a caller can sleep on it (or a test can assert it) without a clock.
        """
        if attempt < 0:
            attempt = 0
        delay = self.backoff_base_seconds * (self.backoff_multiplier ** attempt)
        return min(delay, self.backoff_max_seconds)


def build_stealth_config(
    *,
    residential_proxy_url: str = "",
    residential_proxy_enabled: bool = True,
    vps_proxy_url: str = "",
    block_prone_policy: str = PROXY_POLICY_RESIDENTIAL,
    default_policy: str = PROXY_POLICY_DIRECT,
    source_proxy_policy: object = "",
    extra_residential_proxies: tuple[str, ...] = (),
    sticky_sessions: bool = True,
    sessid_label: str = DEFAULT_SESSID_LABEL,
    rate_max_calls: int = 5,
    rate_period_seconds: float = 60.0,
    min_request_interval_seconds: float = 2.0,
    backoff_base_seconds: float = 2.0,
    backoff_multiplier: float = 2.0,
    backoff_max_seconds: float = 60.0,
    block_max_retries: int = 1,
) -> StealthConfig:
    """Build a :class:`StealthConfig` from plain values (the wiring seam).

    ``container.py`` (the Integrate step) calls this with the corresponding
    ``Settings`` fields — kept plain-kwarg so ``core`` never imports ``app``.
    ``source_proxy_policy`` accepts the raw ``key=policy,...`` string (or a
    mapping) and is parsed/validated here.
    """
    overrides = parse_source_proxy_policy(source_proxy_policy)
    policy_block = (block_prone_policy or PROXY_POLICY_RESIDENTIAL).strip().lower()
    policy_default = (default_policy or PROXY_POLICY_DIRECT).strip().lower()
    if policy_block not in PROXY_POLICIES:
        raise ValueError(
            f"invalid block-prone proxy policy {block_prone_policy!r}; "
            f"choose one of {PROXY_POLICIES}"
        )
    if policy_default not in PROXY_POLICIES:
        raise ValueError(
            f"invalid default proxy policy {default_policy!r}; "
            f"choose one of {PROXY_POLICIES}"
        )
    return StealthConfig(
        residential_proxy_url=residential_proxy_url or "",
        residential_proxy_enabled=bool(residential_proxy_enabled),
        vps_proxy_url=vps_proxy_url or "",
        extra_residential_proxies=tuple(extra_residential_proxies),
        block_prone_policy=policy_block,
        default_policy=policy_default,
        source_policy_overrides=overrides,
        sticky_sessions=bool(sticky_sessions),
        sessid_label=sessid_label or DEFAULT_SESSID_LABEL,
        rate_max_calls=rate_max_calls,
        rate_period_seconds=rate_period_seconds,
        min_request_interval_seconds=min_request_interval_seconds,
        backoff_base_seconds=backoff_base_seconds,
        backoff_multiplier=backoff_multiplier,
        backoff_max_seconds=backoff_max_seconds,
        block_max_retries=block_max_retries,
    )
