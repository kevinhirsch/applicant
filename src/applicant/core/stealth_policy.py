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


def is_block_error(
    error: object, status_codes: frozenset[int] | set[int] | None = None
) -> bool:
    """Classify an exception / status as a bot-block (400/403/429/503 + markers).

    Best-effort and dependency-free: reads a numeric ``status``/``status_code``
    (directly or off a ``.response``) when present, else scans the string form
    for a block status code or a known anti-bot vendor marker. Used to decide
    whether a failed block-prone fetch should escalate to the residential proxy.

    ``status_codes`` is the set of HTTP codes treated as a block; it defaults to
    :data:`BLOCK_STATUS_CODES` so every existing caller is byte-identical, but a
    :class:`StealthConfig` (whose ``block_status_codes`` is operator-configurable
    via the Settings > Stealth panel) passes its own set through
    :meth:`StealthConfig.is_block_error`.
    """
    codes = BLOCK_STATUS_CODES if status_codes is None else status_codes
    if error is None:
        return False
    # 1) an explicit int status code.
    if isinstance(error, bool):  # guard: bool is an int subclass
        return False
    if isinstance(error, int):
        return error in codes
    # 2) a status attribute on the exception (httpx.HTTPStatusError.response, or
    #    a plain ``.status_code`` on some client errors).
    for attr in ("status_code", "status"):
        code = getattr(error, attr, None)
        if isinstance(code, int) and not isinstance(code, bool) and code in codes:
            return True
    response = getattr(error, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if isinstance(code, int) and not isinstance(code, bool) and code in codes:
            return True
    # 3) fall back to a marker scan of the string form.
    text = str(error).lower()
    return any(marker in text for marker in _BLOCK_MARKERS)


def parse_block_statuses(value: object) -> frozenset[int]:
    """Parse an operator ``block_detect_statuses`` value into a code set.

    Accepts the panel's comma-separated string (``"403,429,503"``) or an iterable
    of ints. Whitespace is stripped and non-integer chunks are skipped (the router
    already validates on save, so this is defensive — it never raises). An empty /
    unset value falls back to :data:`BLOCK_STATUS_CODES` so block-detection is
    never silently disabled to nothing.
    """
    if value is None:
        return BLOCK_STATUS_CODES
    if isinstance(value, (set, frozenset, tuple, list)):
        codes = {int(v) for v in value if isinstance(v, int) and not isinstance(v, bool)}
        return frozenset(codes) if codes else BLOCK_STATUS_CODES
    raw = str(value).strip()
    if not raw:
        return BLOCK_STATUS_CODES
    codes: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            codes.add(int(part))
        except ValueError:
            continue
    return frozenset(codes) if codes else BLOCK_STATUS_CODES


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


def new_sessid(flow_key: str | None = None, *, seed: str | None = None) -> str:
    """A sticky-session id for one flow (DataImpulse ``sessid`` label body).

    ``seed`` is the OPERATOR-pinned sticky id (``residential_sticky_sessid`` from
    the Settings > Stealth panel): when a non-blank seed is supplied it WINS over
    ``flow_key`` so every flow shares the ONE operator-chosen residential identity
    (ST-5: "browse→apply = one identity", pinned across restarts). With no seed,
    the id is a deterministic short id derived from ``flow_key`` when given (so the
    SAME flow reuses the SAME residential IP for the forwarder's ~30-min hold),
    else a fresh random id. Hex, 12 chars (or the seed verbatim when pinned).
    """
    if seed:
        pinned = str(seed).strip()
        if pinned:
            return pinned
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
    #: HTTP status codes treated as a bot-block (the operator-configurable
    #: ``block_detect_statuses`` from Settings > Stealth). Defaults to the module
    #: :data:`BLOCK_STATUS_CODES` so an unconfigured config behaves as before;
    #: :meth:`is_block_error` consults THIS set, not the module-level constant.
    block_status_codes: frozenset[int] = BLOCK_STATUS_CODES

    # -- resolution ----------------------------------------------------------
    def is_block_error(self, error: object) -> bool:
        """Classify ``error`` as a bot-block using THIS config's status set.

        Threads :attr:`block_status_codes` (the saved ``block_detect_statuses``)
        into the pure module classifier so the operator's chosen block-detect set
        actually governs the residential-escalation decision (ST-6).
        """
        return is_block_error(error, self.block_status_codes)

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
    block_status_codes: frozenset[int] | set[int] | None = None,
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
        block_status_codes=(
            BLOCK_STATUS_CODES if block_status_codes is None else frozenset(block_status_codes)
        ),
    )


# ---------------------------------------------------------------------------
# Effective-posture RESOLVER — persisted Settings-UI prefs GOVERN runtime.
# ---------------------------------------------------------------------------
#
# The Settings > Stealth panel persists two records — ``automation.prefs`` (the
# existing engine egress/browser fields) and ``stealth.prefs`` (the new
# stealth-only fields). They were WRITE-ONLY: nothing at runtime read them; the
# EgressPolicy/StealthConfig/PatchrightBrowser were built once at boot from
# ``settings.*`` (env) only. This resolver folds the persisted prefs OVER the env
# defaults into one effective posture, using the SAME precedence
# ``routers/stealth.py:build_stealth_view`` uses for the panel display — so what
# the panel SHOWS is what the runtime actually USES.
#
# It is PURE and dependency-free (reads a duck-typed settings object + two dicts),
# lives in ``core`` and imports nothing from ``adapters``/``app`` (NFR-ARCH-1), and
# returns primitives for the browser egress (the app layer builds ``EgressPolicy``
# from them, since that type lives in ``adapters``) plus a ready ``StealthConfig``.
#
# HARD SAFETY INVARIANT: this SELECTS app-level egress/proxy/residential posture
# ONLY. It never touches — and must never be used to touch — the HOST-level
# WireGuard/VPS source-routing that protects the home IP (configured OUTSIDE this
# app). An app pref of "home"/"direct" still egresses through the host route; the
# resolver merely picks proxies, never host networking.

#: Settings > Stealth per-source residential policy (the panel's 3-way). Distinct
#: from :data:`PROXY_POLICIES` (the ``StealthConfig`` vocab direct/vps/residential)
#: — these are the higher-level OPERATOR intents the resolver maps onto it.
PER_SOURCE_SELECTIVE = "selective"
PER_SOURCE_ALWAYS = "always"
PER_SOURCE_NEVER = "never"
PER_SOURCE_POLICIES = (PER_SOURCE_SELECTIVE, PER_SOURCE_ALWAYS, PER_SOURCE_NEVER)

#: Preset DEFAULTS for the stealth-only panel fields — the values the resolver
#: falls back to when nothing is persisted, so runtime matches the panel display.
#: ``routers/stealth.py:STEALTH_PREFS_DEFAULTS`` is built ON TOP of this (adding the
#: display-only ``egress_route``) so there is ONE source of truth for the presets.
STEALTH_RUNTIME_DEFAULTS: dict[str, object] = {
    "residential_enabled": True,
    "residential_sticky_sessid": "",
    "per_source_proxy_policy": PER_SOURCE_SELECTIVE,
    "webrtc_suppression": True,
    "request_pacing_ms": 1500,
    "request_rate_per_min": 20,
    "block_detect_threshold": 2,
    "block_detect_statuses": "403,429,503",
}


def _map_per_source_policy(policy: object) -> tuple[str, str, bool]:
    """Map a panel per-source intent onto ``(block_prone, default, residential_off)``.

    * ``always``   — route block-prone sources residentially UP FRONT.
    * ``selective`` — baseline the free VPS/network exit; reserve residential for
      block-detect escalation only (conserve residential GB/reputation, ST-5).
    * ``never``    — never use residential at all (baseline VPS; residential OFF).

    ``default`` (every other source) is always ``direct`` — keyless ATS / SearXNG /
    RSS egress cleanly and must never burn residential GB. ``residential_off`` folds
    into the master switch so ``never`` disables the escalation pool too.
    """
    p = str(policy or "").strip().lower()
    if p == PER_SOURCE_ALWAYS:
        return (PROXY_POLICY_RESIDENTIAL, PROXY_POLICY_DIRECT, False)
    if p == PER_SOURCE_NEVER:
        return (PROXY_POLICY_VPS, PROXY_POLICY_DIRECT, True)
    # selective (and any unknown -> the safe conserving default).
    return (PROXY_POLICY_VPS, PROXY_POLICY_DIRECT, False)


@dataclass(frozen=True)
class StealthPosture:
    """The effective runtime stealth posture (persisted prefs folded over env).

    Browser-egress fields are PRIMITIVES (``core`` cannot import the adapter's
    ``EgressPolicy``); the app layer builds ``EgressPolicy.from_settings(...)`` from
    them. ``stealth_config`` is the ready per-source discovery policy. ``sticky_sessid``
    is the operator-pinned residential session seed ("" = auto-mint per flow).
    """

    egress_mode: str
    egress_proxy_url: str
    egress_residential: bool
    suppress_webrtc: bool
    suppress_dns_leak: bool
    browser_engine: str
    sticky_sessid: str
    stealth_config: StealthConfig


def resolve_stealth_posture(
    settings: object,
    automation_prefs: Mapping[str, object] | None = None,
    stealth_prefs: Mapping[str, object] | None = None,
) -> StealthPosture:
    """Fold persisted Settings > Stealth prefs OVER the env ``Settings`` -> posture.

    Precedence mirrors ``routers/stealth.py:build_stealth_view``:

    * the EXISTING engine fields (egress mode/proxy/attestation, browser engine)
      prefer a persisted ``automation.prefs`` override, else the env ``Settings``;
    * the NEW stealth-only fields prefer a persisted ``stealth.prefs`` override,
      else the panel PRESET (:data:`STEALTH_RUNTIME_DEFAULTS`);
    * the discovery knobs with NO panel field (residential/VPS URLs, sticky-label,
      backoff, source overrides) come from env ``Settings`` as before.

    Reads ``settings`` duck-typed (``getattr`` with env-default fallbacks) so it is
    unit-testable with a ``SimpleNamespace`` and never imports the app-config layer.
    """
    auto = dict(automation_prefs or {})
    prefs = dict(stealth_prefs or {})

    def _s(name: str, default: object) -> object:
        return getattr(settings, name, default)

    def _pref(key: str) -> object:
        return prefs.get(key, STEALTH_RUNTIME_DEFAULTS[key])

    # --- existing engine fields: automation.prefs override, else env -----------
    egress_mode = auto.get("egress_mode", _s("egress_mode", "direct")) or "direct"
    egress_proxy_url = auto.get("egress_proxy_url", _s("egress_proxy_url", "")) or ""
    egress_residential = bool(auto.get("egress_residential", _s("egress_residential", False)))
    browser_engine = auto.get("browser_engine", _s("browser_engine", "camoufox")) or "camoufox"

    # --- stealth-only fields: stealth.prefs override, else panel preset --------
    residential_enabled = bool(_pref("residential_enabled"))
    sticky_sessid = str(_pref("residential_sticky_sessid") or "")
    per_source = _pref("per_source_proxy_policy")
    suppress_webrtc = bool(_pref("webrtc_suppression"))
    pacing_ms = int(_pref("request_pacing_ms"))
    rate_per_min = int(_pref("request_rate_per_min"))
    block_threshold = int(_pref("block_detect_threshold"))
    block_status_codes = parse_block_statuses(_pref("block_detect_statuses"))

    block_prone_policy, default_policy, residential_off = _map_per_source_policy(per_source)
    residential_enabled_eff = residential_enabled and not residential_off

    # --- non-panel discovery knobs: env only (unchanged) ----------------------
    extra = tuple(
        p.strip() for p in str(_s("discovery_proxies", "") or "").split(",") if p.strip()
    )

    stealth_config = build_stealth_config(
        residential_proxy_url=str(_s("residential_proxy_url", "") or ""),
        residential_proxy_enabled=residential_enabled_eff,
        vps_proxy_url=str(_s("vps_proxy_url", "") or ""),
        block_prone_policy=block_prone_policy,
        default_policy=default_policy,
        source_proxy_policy=_s("discovery_source_proxy_policy", "") or "",
        extra_residential_proxies=extra,
        sticky_sessions=bool(_s("residential_sticky_sessions", True)),
        sessid_label=str(_s("residential_sessid_label", DEFAULT_SESSID_LABEL) or DEFAULT_SESSID_LABEL),
        rate_max_calls=rate_per_min,
        rate_period_seconds=60.0,
        min_request_interval_seconds=pacing_ms / 1000.0,
        backoff_base_seconds=float(_s("discovery_backoff_base_seconds", 2.0)),
        backoff_multiplier=float(_s("discovery_backoff_multiplier", 2.0)),
        backoff_max_seconds=float(_s("discovery_backoff_max_seconds", 60.0)),
        block_max_retries=block_threshold,
        block_status_codes=block_status_codes,
    )

    return StealthPosture(
        egress_mode=str(egress_mode),
        egress_proxy_url=str(egress_proxy_url),
        egress_residential=egress_residential,
        suppress_webrtc=suppress_webrtc,
        suppress_dns_leak=bool(_s("browser_suppress_dns_leak", True)),
        browser_engine=str(browser_engine),
        sticky_sessid=sticky_sessid,
        stealth_config=stealth_config,
    )
