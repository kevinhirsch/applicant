"""Application settings (pydantic-settings, env-driven; zero-CLI, NFR-ZEROCLI-1)."""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# EPIC MODEL-CONFIG: the pure per-use-case catalog lives in ``core.model_config`` so
# both the ``application`` and ``app`` layers can import it (application must not
# import app). Re-exported below so routers/UI keep one ``config`` import site.
from applicant.core.model_config import (
    LLM_BINDING_MODE_DEFAULT,
    LLM_BINDING_MODE_ENDPOINT,
    LLM_BINDING_MODES,
    LLM_USE_CASE_GROUP_AGENTS,
    LLM_USE_CASE_GROUP_CHAT,
    LLM_USE_CASE_GROUP_DRAFTING,
    LLM_USE_CASE_GROUP_EMBEDDINGS,
    LLM_USE_CASE_GROUP_RESEARCH,
    LLM_USE_CASE_GROUP_SCORING,
    LLM_USE_CASE_GROUP_SYSTEM,
    LLM_USE_CASES,
    LLM_USE_CASES_BY_KEY,
    LLMUseCase,
    llm_use_case_keys,
)

# EPIC STEALTH: the per-source proxy-policy vocabulary lives in
# ``core.stealth_policy`` (a pure, adapter-free layer both the discovery adapters
# and this config layer import). Re-exported below so the Settings validators + the
# router/UI keep one ``config`` import site for the policy names.
from applicant.core.stealth_policy import (
    PROXY_POLICIES,
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_RESIDENTIAL,
    PROXY_POLICY_VPS,
    StealthConfig,
    parse_source_proxy_policy,
)
from applicant.core.stealth_policy import (
    build_stealth_config as _build_stealth_config,
)

# Re-exported so router/UI + downstream ``from applicant.app.config import ...``
# sites keep one import site for the stealth proxy-policy vocabulary (mirrors the
# ``_MODEL_CONFIG_REEXPORTS`` pattern above).
_STEALTH_CONFIG_REEXPORTS = (
    PROXY_POLICIES,
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_RESIDENTIAL,
    PROXY_POLICY_VPS,
    StealthConfig,
    parse_source_proxy_policy,
)

# --- Takeover desktop (FR-SANDBOX-2/3, FR-PREFILL-5) -------------------------
#: The takeover desktop is a containerized, web-streamed Ubuntu desktop (the DE is
#: an image/arg swap). Default Cinnamon; Xfce, GNOME, Pantheon also selectable.
TAKEOVER_DESKTOP_CINNAMON = "cinnamon"
TAKEOVER_DESKTOP_XFCE = "xfce"
TAKEOVER_DESKTOP_GNOME = "gnome"
TAKEOVER_DESKTOP_PANTHEON = "pantheon"
TAKEOVER_DESKTOPS = (
    TAKEOVER_DESKTOP_CINNAMON,
    TAKEOVER_DESKTOP_XFCE,
    TAKEOVER_DESKTOP_GNOME,
    TAKEOVER_DESKTOP_PANTHEON,
)

#: DE -> container image resolution table (FR-SANDBOX-2, FR-STEALTH-1). Every DE
#: must ship **Google Chrome** so the human takes over the SAME real Chrome the
#: engine drives (coherent real-Linux/Chrome identity). The stock LinuxServer
#: webtops do NOT ship Chrome, so Cinnamon & Xfce resolve to LOCAL derived images
#: (``docker/webtop-chrome/Dockerfile``, ``FROM`` the LinuxServer webtop, adding
#: google-chrome-stable + a realistic font set). Full GNOME does NOT ship as a
#: prebuilt webtop (GNOME assumes Wayland/systemd) so ``gnome`` resolves to the
#: custom ``docker/webtop-gnome/Dockerfile`` (now also Chrome + fonts). Likewise
#: ``pantheon`` (elementary's DE) is not a prebuilt webtop, so it resolves to the
#: custom ``docker/webtop-pantheon/Dockerfile`` (Ubuntu + pantheon-session/Gala on
#: X11 + Chrome + fonts; cosmetic-only, not pixel-pure elementary). See README.
TAKEOVER_DESKTOP_IMAGES: dict[str, str] = {
    TAKEOVER_DESKTOP_CINNAMON: "applicant/webtop-chrome:cinnamon",
    TAKEOVER_DESKTOP_XFCE: "applicant/webtop-chrome:xfce",
    TAKEOVER_DESKTOP_GNOME: "applicant/webtop-gnome:latest",
    TAKEOVER_DESKTOP_PANTHEON: "applicant/webtop-pantheon:latest",
}

#: Remote-view backends (FR-SANDBOX-2): ``webtop`` (full Ubuntu desktop, default)
#: or ``neko`` (browser-only, kept selectable/swappable).
REMOTE_VIEW_WEBTOP = "webtop"
REMOTE_VIEW_NEKO = "neko"
REMOTE_VIEW_BACKENDS = (REMOTE_VIEW_WEBTOP, REMOTE_VIEW_NEKO)

#: Driving browser channel (FR-STEALTH-1). ``chrome`` = real Google Chrome (the
#: default, the foundation of the coherent identity — genuine TLS/JA3 + client
#: hints); ``chromium`` = the bundled Chromium fallback (less coherent; only when
#: Google Chrome is unavailable). Headless is NEVER used (it is a detection tell).
#: Only consulted by the ``chromium`` browser engine (Camoufox manages its own).
BROWSER_CHANNEL_CHROME = "chrome"
BROWSER_CHANNEL_CHROMIUM = "chromium"
BROWSER_CHANNELS = (BROWSER_CHANNEL_CHROME, BROWSER_CHANNEL_CHROMIUM)

#: Browser ENGINE the agent drives for all pre-fill / ATS automation — the only
#: surface through which Applicant makes outbound browser traffic (FR-STEALTH-1,
#: FR-PREFILL-1). ``camoufox`` (the default) is a Firefox-based anti-detect browser
#: that injects its own coherent, real-world-distribution fingerprint (so no Chrome
#: init-script override is applied); ``chromium`` is the patchright + real
#: Chrome/Chromium path (the honest real-Chrome identity, and the engine used for
#: the Proxmox Windows CDP backend, which connects to a remote real Chrome).
BROWSER_ENGINE_CAMOUFOX = "camoufox"
BROWSER_ENGINE_CHROMIUM = "chromium"
BROWSER_ENGINES = (BROWSER_ENGINE_CAMOUFOX, BROWSER_ENGINE_CHROMIUM)

#: Sandbox backend (FR-SANDBOX-1, FR-STEALTH-1). ``local`` (default) is the existing
#: webtop/Neko container path where the browser the engine drives + the human takes
#: over runs on the host. ``proxmox-windows`` is a NATIVE backend where that browser
#: is real Google Chrome inside a real, licensed Windows VM on a Proxmox node — so
#: the fingerprint (JA3/TLS, Direct3D WebGL, Segoe UI/Calibri, OS signals) is
#: GENUINELY Windows with ZERO spoofing (the strongest FR-STEALTH-1).
SANDBOX_BACKEND_LOCAL = "local"
SANDBOX_BACKEND_PROXMOX_WINDOWS = "proxmox-windows"
SANDBOX_BACKENDS = (SANDBOX_BACKEND_LOCAL, SANDBOX_BACKEND_PROXMOX_WINDOWS)

#: Stealth persona (FR-STEALTH-1). ``linux`` = the coherent REAL-Linux/Chrome spoof
#: (the default for the ``local`` backend: apply a coherent honest fingerprint).
#: ``native`` = use the browser's REAL identity with NO fingerprint override —
#: selected automatically for the ``proxmox-windows`` backend because it IS real
#: Windows + real Chrome (genuine Windows fingerprint, no override needed).
STEALTH_PERSONA_LINUX = "linux"
STEALTH_PERSONA_NATIVE = "native"
STEALTH_PERSONAS = (STEALTH_PERSONA_LINUX, STEALTH_PERSONA_NATIVE)

#: Proxmox Windows clone modes (FR-SANDBOX-1/4). ``linked-clone`` spins a fresh
#: linked clone of the template per session (strongest isolation; destroyed on
#: teardown). ``snapshot-revert`` reuses ONE persistent VM and rolls it back to a
#: clean snapshot per session (cheaper; no per-session clone). Default is the
#: cheaper, operator-friendly ``snapshot-revert``.
PROXMOX_CLONE_LINKED = "linked-clone"
PROXMOX_CLONE_SNAPSHOT_REVERT = "snapshot-revert"
PROXMOX_CLONE_MODES = (PROXMOX_CLONE_LINKED, PROXMOX_CLONE_SNAPSHOT_REVERT)

#: Takeover methods for the Windows VM (FR-SANDBOX-2/3). ``rdp`` mints an ``rdp://``
#: (or ``.rdp``) one-click URI to the VM's RDP host; ``web-console`` mints a URL
#: against a web RDP gateway (e.g. Guacamole / PVE noVNC) template.
PROXMOX_TAKEOVER_RDP = "rdp"
PROXMOX_TAKEOVER_WEB_CONSOLE = "web-console"
PROXMOX_TAKEOVER_METHODS = (PROXMOX_TAKEOVER_RDP, PROXMOX_TAKEOVER_WEB_CONSOLE)

#: Browser egress modes (FR-STEALTH-4). ``direct`` uses the host's own residential
#: connection; ``residential-proxy`` threads an attested residential proxy into the
#: real browser launch. A typo must be rejected at load (item 12) — not silently
#: treated as ``direct`` (which would unknowingly egress without the intended proxy).
EGRESS_MODE_DIRECT = "direct"
EGRESS_MODE_RESIDENTIAL_PROXY = "residential-proxy"
EGRESS_MODES = (EGRESS_MODE_DIRECT, EGRESS_MODE_RESIDENTIAL_PROXY)

#: CAPTCHA handling strategies (issue #350). ``human`` (default) reproduces today's
#: behavior — every captcha hands off to the operator. ``avoid``/``service`` are opt-in.
CAPTCHA_STRATEGY_HUMAN = "human"
CAPTCHA_STRATEGY_AVOID = "avoid"
CAPTCHA_STRATEGY_SERVICE = "service"
CAPTCHA_STRATEGIES = (
    CAPTCHA_STRATEGY_HUMAN,
    CAPTCHA_STRATEGY_AVOID,
    CAPTCHA_STRATEGY_SERVICE,
)

#: Prefix-cache posture (FR-MIND-8). ``auto``/``on`` apply provider cache
#: breakpoints where the provider advertises support; ``off`` never does.
PREFIX_CACHE_AUTO = "auto"
PREFIX_CACHE_ON = "on"
PREFIX_CACHE_OFF = "off"
PREFIX_CACHE_MODES = (PREFIX_CACHE_AUTO, PREFIX_CACHE_ON, PREFIX_CACHE_OFF)


# --- EPIC MODEL-CONFIG: env-overridable preset-model overlay -----------------
# The catalog itself is re-exported from ``core.model_config`` (imported at the top).
# The names below are re-exported so downstream ``from applicant.app.config import
# LLM_USE_CASES`` sites keep working; this tuple also documents the surface.
_MODEL_CONFIG_REEXPORTS = (
    LLM_BINDING_MODE_DEFAULT,
    LLM_BINDING_MODE_ENDPOINT,
    LLM_BINDING_MODES,
    LLM_USE_CASE_GROUP_AGENTS,
    LLM_USE_CASE_GROUP_CHAT,
    LLM_USE_CASE_GROUP_DRAFTING,
    LLM_USE_CASE_GROUP_EMBEDDINGS,
    LLM_USE_CASE_GROUP_RESEARCH,
    LLM_USE_CASE_GROUP_SCORING,
    LLM_USE_CASE_GROUP_SYSTEM,
    LLM_USE_CASES,
    LLM_USE_CASES_BY_KEY,
    LLMUseCase,
    llm_use_case_keys,
)


def llm_preset_model_overrides(settings: Settings) -> dict[str, str]:
    """Map the env-overridable preset-model Settings onto use-case keys.

    Returns ``{use_case_key: preset_model}`` for the use cases whose preset model
    is env-configurable (drafting shares one model across its three sub-cases).
    Only non-empty overrides are returned; the caller overlays these onto the
    static ``LLM_USE_CASES`` ``preset_model`` when rendering the Settings surface,
    so the documented preset is never a hardcoded decision.
    """
    out: dict[str, str] = {}
    if settings.llm_preset_scoring_model:
        out["scoring"] = settings.llm_preset_scoring_model
    if settings.llm_preset_drafting_model:
        for key in ("drafting_cover_letter", "drafting_screening", "drafting_resume"):
            out[key] = settings.llm_preset_drafting_model
    if settings.llm_preset_research_model:
        out["research"] = settings.llm_preset_research_model
    if settings.llm_preset_chat_model:
        out["chat"] = settings.llm_preset_chat_model
    if settings.llm_preset_embeddings_model:
        out["embeddings"] = settings.llm_preset_embeddings_model
    return out


def resolve_takeover_image(desktop: str, override: str = "") -> str:
    """Resolve a takeover DE to its container image (FR-SANDBOX-2).

    An explicit ``override`` (advanced ``TAKEOVER_DESKTOP_IMAGE``) wins; otherwise
    the DE->image table is used. Cinnamon/Xfce -> LinuxServer webtop tags;
    ``gnome`` -> the local custom ``applicant/webtop-gnome:latest`` image.
    """
    if override.strip():
        return override.strip()
    try:
        return TAKEOVER_DESKTOP_IMAGES[desktop]
    except KeyError as exc:  # pragma: no cover - guarded by config validation
        raise ValueError(
            f"Unknown takeover desktop {desktop!r}; choose one of {TAKEOVER_DESKTOPS}."
        ) from exc


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Deployment mode (FR-DEPLOY). "" (default) = every integration ships
    # hermetic/safe; "production" = ONE preset that turns on live browser, live
    # discovery, live notifications, durable orchestration (DBOS), and the 24/7
    # scheduler at once - the engine does real work out of the box. You can still
    # override any individual flag after the mode is applied.
    applicant_mode: str = Field(default="", alias="APPLICANT_MODE")

    # Storage (FR-CRIT-4, FR-DUR-3)
    database_url: str = Field(
        default="postgresql+psycopg://applicant:applicant@localhost:5432/applicant",
        alias="DATABASE_URL",
    )

    # Frontend (FR-UI-1)
    app_static_dir: str = Field(default="frontend/static", alias="APP_STATIC_DIR")

    # LLM (FR-LLM-1/2). Empty until configured via OOBE; the gate keys off these.
    llm_provider: str = Field(default="", alias="LLM_PROVIDER")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    # --- LLM HTTP timeout (P0 durability fix) --------------------------------
    # A flat 60.0s httpx default was too short for a cold-start local model call
    # (e.g. vLLM warm-up ~38s could still exceed 60s under load) — a call that
    # timed out looked like a permanent failure and (before the companion fix in
    # scoring_service.py) silently degraded viability scoring to the local
    # embedding signal, with the bad sub-threshold score persisted forever with no
    # retry. Raised + made configurable; split into a SHORT connect budget and a
    # LONG read budget (container.py builds an ``httpx.Timeout`` from the two) so a
    # genuinely unreachable host still fails fast while a slow-but-alive model
    # gets the time it needs.
    llm_http_timeout: float = Field(default=120.0, ge=1.0, alias="LLM_HTTP_TIMEOUT")
    llm_http_connect_timeout: float = Field(
        default=10.0, ge=1.0, alias="LLM_HTTP_CONNECT_TIMEOUT"
    )

    # --- Deterministic cloud fallback tier (P0 durability fix) ---------------
    # The tier ladder normally holds only the local model. When it fails/times out
    # repeatedly, scoring degrades to the local embedding signal (see
    # scoring_service.py's transient-retry guard). Setting LLM_FALLBACK_API_KEY
    # appends an ADDITIONAL cloud rung — default DeepSeek's OpenAI-compatible
    # endpoint — BELOW the local tier(s) in the ladder (setup_service.py
    # build_ladder), so the existing climb-on-failure escalation logic has a real
    # model to fall through to instead of only the embedding signal. Empty key
    # (the default) adds NO fallback tier — the ladder is local-only, byte-
    # identical to before. Never persisted to the tier-ladder store or surfaced to
    # the UI; resolved fresh from env at ladder-build time. Also dropped under
    # LLM_LOCAL_ONLY private mode (P2-11) exactly like any other cloud tier.
    llm_fallback_provider: str = Field(default="openai", alias="LLM_FALLBACK_PROVIDER")
    llm_fallback_base_url: str = Field(
        default="https://api.deepseek.com/v1", alias="LLM_FALLBACK_BASE_URL"
    )
    llm_fallback_model: str = Field(default="deepseek-chat", alias="LLM_FALLBACK_MODEL")
    llm_fallback_api_key: str = Field(default="", alias="LLM_FALLBACK_API_KEY")
    llm_fallback_context_window: int = Field(
        default=65536, ge=1, alias="LLM_FALLBACK_CONTEXT_WINDOW"
    )

    # --- Local-LLM wedge detector (ADR-0008 / EPIC SELF-HEAL, Slice S1) -------
    # How many CONSECUTIVE primary-tier completion failures (climbed past or
    # ladder-exhausted) declare a "wedge" rather than ordinary transient noise
    # the ladder already absorbs silently -- see
    # `application/services/llm_wedge_detector.py`. Mirrors
    # `SCORING_MAX_TRANSIENT_RETRIES`'s bounded-retry-count idiom.
    llm_wedge_detection_threshold: int = Field(
        default=3, ge=1, alias="LLM_WEDGE_DETECTION_THRESHOLD"
    )

    # Truth policy for the material fabrication guard (P1-13). "balanced" (default):
    # the model may freely rewrite/restructure; invented *facts* are surfaced for
    # review, not hard-blocked (safe — a human approves every send). "strict": any
    # unsupported fact hard-fails generation (the historical behaviour).
    truth_policy: str = Field(default="balanced", alias="TRUTH_POLICY")

    # P1-1a: LLM verify-and-correct over the deterministic résumé parse (slotting).
    # ON by default; degrades to the deterministic parse with an honest not-verified
    # marker when no model is configured. Set 0/false to force deterministic-only.
    parse_verify_enabled: bool = Field(default=True, alias="PARSE_VERIFY_ENABLED")

    # Context management (FR-MIND-8, FR-MIND-13). Token budget over which the LLM
    # adapter compresses/evicts MIDDLE turns (the system tier + most recent turns
    # are always kept). 64000 (~250k chars) is a sensible default for multi-turn
    # conversations; set 0 to disable compression.
    context_compress_threshold: int = Field(
        default=64000, ge=0, alias="CONTEXT_COMPRESS_THRESHOLD"
    )
    prefix_cache: str = Field(default="auto", alias="PREFIX_CACHE")

    # P1-6 (cost & pace guardrails): $/1K-token rates used to turn captured token
    # counts into an ESTIMATED dollar figure (never exact billing — the engine has
    # no way to know a provider's live per-model price without another network
    # call). Defaults are a conservative blended cloud-model rate; tune to your
    # actual provider's pricing if you want a tighter estimate.
    llm_cost_per_1k_input_usd: float = Field(
        default=0.15, ge=0, alias="LLM_COST_PER_1K_INPUT_USD"
    )
    llm_cost_per_1k_output_usd: float = Field(
        default=0.60, ge=0, alias="LLM_COST_PER_1K_OUTPUT_USD"
    )

    # Credential vault (FR-VAULT-3)
    credential_keyfile: str = Field(default="secrets/master.key", alias="CREDENTIAL_KEYFILE")

    # PII retention policy (#363, FR-CRIT-4, NFR-PRIV-1). How many days stored PII
    # (parsed PII / EEO answers + the onboarding intake) is kept before a retention
    # sweep prunes it. Default 0 = keep PII until the campaign is deleted (no
    # time-based prune) — byte-identical to today until an operator opts in. ge=0 so a
    # negative window is rejected at load rather than silently disabling retention.
    pii_retention_days: int = Field(default=0, ge=0, alias="PII_RETENTION_DAYS")
    # PII retention sweep schedule (#363). ``off`` (default) keeps it dormant; ``daily``
    # opts in to a once-per-UTC-day sweep. Mirrors the curation/status-update/essentials
    # nudge schedule pattern so the deploy surface stays uniform.
    pii_retention_schedule: str = Field(default="off", alias="PII_RETENTION_SCHEDULE")

    # Durable orchestration (FR-DUR-3). "shim" (default, no PG) or "dbos".
    orchestrator_backend: str = Field(default="shim", alias="ORCHESTRATOR_BACKEND")
    checkpoint_dir: str = Field(default=".applicant_checkpoints", alias="CHECKPOINT_DIR")

    # Durable approval-gate timeout (FR-DUR-3). How many days the engine waits for
    # a human decision (final approval / account hand-off) before timing out the
    # pending workflow. Default 30 days — long enough for a real vacation, short
    # enough that a genuinely abandoned application is surfaced. Set 0 for no timeout
    # (effectively forever, matching the old hardcoded ~10 years).
    approval_timeout_days: int = Field(default=30, ge=0, alias="APPROVAL_TIMEOUT_DAYS")

    # Fine-grained override for the durable approval-gate ``recv`` wait, in SECONDS
    # (#189). The "indefinite" wait was a hardcoded ~10-year module constant with no
    # per-deployment knob; this field makes it tunable. When set (>0) it takes
    # precedence over ``approval_timeout_days``; 0 means "no timeout" (wait forever);
    # unset (None) falls back to the days-based setting. Exposed in seconds so a short
    # operational/test window (e.g. a few minutes) can be configured precisely.
    approval_wait_seconds: float | None = Field(
        default=None, ge=0, alias="APPROVAL_WAIT_SECONDS"
    )

    # Scheduler (FR-DIG-1, FR-NOTIF-2, NFR-247-1). OFF by default so the default
    # test lane / TestClient never spins a live background loop; prod compose sets
    # it True (zero-CLI via env). When True the lifespan starts the asyncio tick
    # loop on the shim, or DBOS @scheduled drives it on the DBOS path.
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: float = Field(
        default=60.0, alias="SCHEDULER_INTERVAL_SECONDS"
    )
    # Observability / NFR-OPS (FR-OBS-2): how many CONSECUTIVE scheduler ticks must
    # fail before the loop raises ONE operator alert through the existing notification
    # ladder (idempotent — it re-arms only after a tick succeeds again). Default 3
    # catches a real stall fast while tolerating a single transient blip. ge=1 so a
    # 0/negative value (which would alert on the first failure or never) is rejected
    # at load rather than silently disabling stall detection.
    loop_failure_alert_threshold: int = Field(
        default=3, ge=1, alias="LOOP_FAILURE_ALERT_THRESHOLD"
    )

    # Durable queues (FR-DUR-2): sandbox concurrency cap + per-provider LLM rate.
    # ge=1: a 0/negative cap would admit nothing; reject it at load.
    sandbox_concurrency: int = Field(default=3, ge=1, alias="SANDBOX_CONCURRENCY")
    llm_rate_limit: int = Field(default=30, alias="LLM_RATE_LIMIT")  # 0 disables; default 30 req/min
    llm_rate_period: float = Field(default=60.0, alias="LLM_RATE_PERIOD")

    # Observability (FR-OBS-1)
    log_format: str = Field(default="pretty", alias="LOG_FORMAT")  # pretty | json
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Notifications (FR-NOTIF-1). Live network send is OFF by default so the default
    # test lane never touches Discord/SMTP; flip on in a real deployment (zero-CLI).
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    apprise_urls: str = Field(default="", alias="APPRISE_URLS")
    # #300: ntfy push channel — opt-in, empty by default. Comma-separated ntfy:// URLs
    # (e.g. ``ntfy://ntfy.sh/my-topic``). The ntfy service is already in the Compose
    # stack; configure this to route urgent action alerts to push-notification clients.
    ntfy_url: str = Field(default="", alias="NTFY_URL")
    notifications_live: bool = Field(default=False, alias="NOTIFICATIONS_LIVE")

    # Stage 2.5 — ENGINE -> WORKSPACE callback channel. The engine calls BACK into
    # the front-door workspace app (``applicant-ui``) over the private docker
    # network to read calendar interviews / run research.
    # ``workspace_url`` is where to reach it (the in-network address); the shared
    # ``applicant_internal_token`` is the bearer of trust (constant-time compared
    # by the workspace). Empty token => the channel is OFF and the client's
    # ``available()`` is False, so callers degrade gracefully.
    workspace_url: str = Field(default="http://applicant-ui:7000", alias="WORKSPACE_URL")
    applicant_internal_token: str = Field(default="", alias="APPLICANT_INTERNAL_TOKEN")
    # Owner attribution sent as X-Applicant-Owner on every owner-scoped workspace
    # callback (research/calendar/emails/memory). The companion requires it non-empty
    # or 400s ("Owner attribution required"). Single-user non-empty default so a fresh
    # install's callbacks work out of the box; override via APPLICANT_OWNER (e.g. email).
    applicant_owner: str = Field(default="applicant", alias="APPLICANT_OWNER")
    #: Backend selection for the WorkspacePort adapter. ``"real"`` (default) uses
    #: ``HttpWorkspaceClient`` which speaks HTTP to the companion workspace app.
    #: ``"mock"`` uses ``MockWorkspaceClient`` which serves deterministic fixture
    #: data with no network — useful for testing lane email/calendar logic without
    #: real IMAP/CalDAV credentials. Every other value is equivalent to ``"real"``
    #: (the safe default for production).
    workspace_backend: str = Field(default="real", alias="WORKSPACE_BACKEND")

    # --- Pre-application research feed (#299) --------------------------------
    # When enabled, on-demand cover-letter generation may best-effort pull the
    # capped/deduped/cached company research (over the engine->workspace deep-research
    # channel) and fold it into the generation context so the letter can reference
    # company-specific detail. Budget-aware (reuses the ResearchService per-campaign
    # cap) and degrades silently when research is unavailable / the budget is spent —
    # so flipping this off (or the channel being down) is byte-identical to before.
    # Default OFF (opt-in): it widens the truthfulness ground truth to include the
    # researched company facts (so a real research fact is not flagged as a
    # fabrication), and consumes research budget per cover letter — the applicant's
    # own resume claims stay checked against the resume regardless. Set
    # MATERIAL_RESEARCH_ENABLED=true to enrich cover letters with company research.
    material_research_enabled: bool = Field(
        default=False, alias="MATERIAL_RESEARCH_ENABLED"
    )

    # --- Agent intelligence: learning/looping substrate (FR-MIND) -----------
    # Backend for the curated-memory / skills / recall stores. ``in_memory``
    # (default — keeps the test lane + hermetic boot fast and isolated) is the
    # in-process trio (no deps); ``sql`` is the DURABLE, production backend (#286):
    # the trio persisted to the shared Postgres/SQLAlchemy stack so memory SURVIVES
    # an engine restart, read locally + single-query (no network — unlike bridge).
    # The PROD default is set to ``sql`` in docker-compose.prod.yml. ``bridge``
    # reaches the front-door substrate (workspace/services/memory/) over the
    # engine->workspace callback channel (agent-intelligence.md §10) but was disabled
    # for stalling the read path ~45s. Valid values: MIND_BACKENDS (factory.py) —
    # ``in_memory`` | ``sql`` | ``bridge`` | ``temporal`` | ``mem0`` | ``letta``.
    # ``sql`` with no reachable DB falls back to ``in_memory`` so boot is always safe.
    mind_backend: str = Field(default="in_memory", alias="MIND_BACKEND")
    # Stage agent self-writes for human review by default (FR-MIND-9). Memory MAY be
    # relaxed to auto-apply non-sensitive entries; skills/identity always require
    # approval regardless of these flags.
    memory_write_approval: bool = Field(default=True, alias="MEMORY_WRITE_APPROVAL")
    skills_write_approval: bool = Field(default=True, alias="SKILLS_WRITE_APPROVAL")
    # Curated-memory size caps (FR-MIND-1) — keep the per-tick prompt snapshot bounded
    # (FR-MIND-13). Environment-lessons budget and the user-preferences budget.
    memory_max_chars: int = Field(default=8000, ge=0, alias="MEMORY_MAX_CHARS")
    user_max_chars: int = Field(default=4000, ge=0, alias="USER_MAX_CHARS")
    # Cadence of the closed-loop curation nudge (FR-MIND-7). Empty/``off`` disables
    # scheduling; a periodic string (e.g. ``daily``) opts in. Default OFF so the
    # substrate ships dormant (FR-MIND-12) until the stores are wired.
    curation_schedule: str = Field(default="off", alias="CURATION_SCHEDULE")
    # Cadence of the proactive "I'm still blocked on essentials" onboarding nudge
    # (FR-NOTIF / FR-ONBOARD). Empty/``off`` disables scheduling; a periodic string
    # (e.g. ``daily``) opts in to a once-per-(campaign, UTC day) push naming the missing
    # apply-essentials. Default OFF so the hermetic lane is byte-identical (no behavior
    # change) until a deploy opts in.
    essentials_nudge_schedule: str = Field(default="daily", alias="ESSENTIALS_NUDGE_SCHEDULE")
    # Cadence of the proactive "here's where your campaigns stand" status update
    # (sibling of the chatbot self-report). ``off`` (default) keeps it dormant; a
    # periodic string (e.g. ``daily``) opts in. Read through Settings like its
    # siblings rather than a raw ``os.getenv`` so the deploy surface stays uniform.
    status_update_schedule: str = Field(default="off", alias="STATUS_UPDATE_SCHEDULE")
    # Cadence of the weekly recap (Top-25 #18: applications sent + best-performing
    # source over the trailing 7 days), pushed through the SAME notification fan-out
    # the daily digest already uses. ``off`` (default) keeps it dormant; a periodic
    # string (e.g. ``weekly``) opts in to a once-per-(campaign, ISO week) push. Read
    # through Settings like its daily siblings rather than a raw ``os.getenv``.
    weekly_recap_schedule: str = Field(default="off", alias="WEEKLY_RECAP_SCHEDULE")
    # Model id for the (cheaper) background curation pass (FR-MIND-7/-13). Empty =>
    # reuse the main configured model.
    curation_model: str = Field(default="", alias="CURATION_MODEL")
    # FR-MIND-6: lets the chat ASSISTANT call its own tools mid-conversation
    # (remember/recall/save-a-playbook + a bounded desktop action). ``off`` (the
    # conservative default) keeps the chat on its current single-shot completion,
    # byte-identical to today. ``auto`` enables the bounded tool-dispatch loop ONLY
    # when the configured model also advertises tool calling; otherwise it stays
    # single-shot. Writes always stage for review (FR-MIND-9) and route through the
    # FR-UI-4 toggles — tools can never bypass review or the stop-boundary.
    chat_tools: str = Field(default="off", alias="CHAT_TOOLS")
    # FR-MIND-6 / FR-CUA-2: lets the AUTONOMOUS agent loop call the SAME tools the chat
    # assistant can (remember/forget/save-or-update a playbook/recall + a bounded desktop
    # action) mid-reasoning, instead of only receiving them as passive context. ``off``
    # (the conservative default) registers no tools and keeps the loop byte-identical to
    # today. ``auto`` registers the tool set ONLY when the configured model also advertises
    # tool calling. Writes always stage for review (FR-MIND-9), an authority-claiming write
    # is refused (FR-MIND-11), the desktop action inherits the stop-boundary (FR-CUA), and
    # each tool respects the per-tool on/off toggles — the loop tools reuse the chat
    # toolbox + every existing guard and can never bypass review or the stop-boundary.
    loop_tools: str = Field(default="off", alias="LOOP_TOOLS")

    # Fonts (FR-FONT-1/2). A confined, configurable dir for runtime font installs;
    # all filesystem/fc-cache ops are restricted to this dir (never system-wide).
    fonts_dir: str = Field(default=".applicant_fonts", alias="FONTS_DIR")

    # Persistent per-tenant browser profiles (FR-STEALTH-3): the user-data dirs that
    # cache a signed-in session (Workday/Google cookies) so the user signs in ONCE and
    # the engine reuses the session across applications + restarts. Point at a persisted
    # volume in the deploy (docker-compose.prod.yml) so sessions survive recreation.
    browser_profiles_dir: str = Field(default=".applicant_profiles", alias="BROWSER_PROFILES_DIR")

    # Resume render fidelity (FR-RESUME-4). "auto" (default) auto-enables the real
    # xelatex/lualatex compile + LibreOffice docx->PDF convert when the engine binary
    # is present at runtime, else degrades to the deterministic stub (so the hermetic
    # lane needs no TeX/LibreOffice). "on" forces real render; "off" forces the stub.
    resume_render: str = Field(default="auto", alias="RESUME_RENDER")

    # Discovery (FR-DISC-2/4/6). Live boards are OFF by default so the default lane
    # never touches the network; flip on in a real deployment (zero-CLI via env/UI).
    discovery_live: bool = Field(default=False, alias="DISCOVERY_LIVE")
    searxng_url: str = Field(default="", alias="SEARXNG_URL")
    # FR-DISC-6 proxy hook: comma-separated; empty = direct egress (no proxy committed).
    discovery_proxies: str = Field(default="", alias="DISCOVERY_PROXIES")
    # Dark-engine audit item 80 (B7): comma-separated custom job-board RSS feed
    # URLs an operator can add without a code change. Merged ALONGSIDE the
    # hardcoded default feed (factory.py's ``RSS_FEEDS``) -- empty (the
    # default) keeps today's hardcoded-only behavior byte-identical.
    discovery_rss_feeds: str = Field(default="", alias="DISCOVERY_RSS_FEEDS")
    # Keyless ATS directory sources (NFR-EXT-1): comma-separated Greenhouse board
    # tokens / Lever company slugs an operator can add without a code change.
    # Each token/company becomes one toggleable discovery source in factory.py
    # (appended ALONGSIDE the hardcoded registry) -- empty (the default)
    # registers zero ATS sources and keeps discovery byte-identical to before.
    discovery_greenhouse_boards: str = Field(default="", alias="DISCOVERY_GREENHOUSE_BOARDS")
    discovery_lever_companies: str = Field(default="", alias="DISCOVERY_LEVER_COMPANIES")
    # EPIC BREADTH (NFR-EXT-1, 2026-08-11): same additive/empty-default shape,
    # widened to three more keyless ATS connector types. Ashby org slugs / Smart-
    # Recruiters company ids are plain slugs like Greenhouse/Lever; Workday board
    # tokens are the compound "host|tenant|site[|Display Name]" string
    # ``LiveWorkdayClient`` needs (Kevin's PRIMARY target industries -- financial
    # services, healthcare, insurance, consulting -- run Workday almost
    # exclusively, unlike Greenhouse/Lever/Ashby which skew tech/startup).
    discovery_ashby_orgs: str = Field(default="", alias="DISCOVERY_ASHBY_ORGS")
    discovery_smartrecruiters_companies: str = Field(
        default="", alias="DISCOVERY_SMARTRECRUITERS_COMPANIES"
    )
    discovery_workday_boards: str = Field(default="", alias="DISCOVERY_WORKDAY_BOARDS")

    # Browser egress (FR-STEALTH-4). The automation MUST egress via the user's
    # residential connection. "direct" (default) uses the host's own connection;
    # "residential-proxy" requires EGRESS_PROXY_URL (attested residential) and is
    # threaded into the real browser launch. A datacenter exit is refused.
    egress_mode: str = Field(default="direct", alias="EGRESS_MODE")  # direct | residential-proxy
    egress_proxy_url: str = Field(default="", alias="EGRESS_PROXY_URL")
    # FR-STEALTH-4: explicit operator attestation that the configured proxy is a
    # RESIDENTIAL exit. Default False so a residential-proxy that is NOT attested
    # residential refuses to launch (the datacenter-egress refusal is reachable via
    # config). Set True only when the operator vouches the proxy is residential.
    egress_residential: bool = Field(default=False, alias="EGRESS_RESIDENTIAL")

    # --- EPIC STEALTH: residential proxy + per-source proxy policy (ST-2/ST-5) --
    # Principle (Kevin): "We cannot be detected at all. Our residential IP score
    # MUST be protected." Automation NEVER egresses from the home IP; block-prone
    # scrape sources go through an attested RESIDENTIAL proxy with a matched
    # fingerprint + human-like pacing, keyless ATS / structured APIs stay DIRECT
    # (they egress cleanly on the free network-layer VPS WireGuard exit, ST-1), and
    # residential bandwidth is conserved (sticky per flow, selective, paced). Every
    # value here is a PRESET DEFAULT that is CHANGEABLE in the Settings UI.
    #
    # The residential exit: DataImpulse (sticky-US) reached through the VPS tunnel
    # forwarder ``http://10.8.0.1:8880`` (see [[VPS Egress Node]] / EPIC STEALTH).
    # A preset default so a fresh install already routes hard targets residentially;
    # override or blank it in Settings. It is applied SELECTIVELY (block-prone
    # sources + on block-detect), never to easy/keyless targets, so GB is not burned.
    residential_proxy_url: str = Field(
        default="http://10.8.0.1:8880", alias="RESIDENTIAL_PROXY_URL"
    )
    # Master toggle for residential-proxy use (ST-5 conservation knob). When False,
    # a ``residential`` policy DOWNGRADES to ``vps`` (the free network-layer exit) —
    # so turning residential off never silently forces the home/datacenter IP into a
    # hard target; it just stops spending residential GB.
    residential_proxy_enabled: bool = Field(
        default=True, alias="RESIDENTIAL_PROXY_ENABLED"
    )
    # Optional explicit VPS-side HTTP proxy URL for the ``vps`` policy. Normally
    # EMPTY: the VPS WireGuard exit already covers egress at the NETWORK layer
    # (ST-1), so ``vps`` == ``direct`` at the HTTP-proxy level. Set this only if the
    # VPS also exposes an HTTP forward proxy you want threaded per-request.
    vps_proxy_url: str = Field(default="", alias="VPS_PROXY_URL")
    # Default proxy policy for BLOCK-PRONE scrape sources (python-jobspy:
    # linkedin/indeed/glassdoor/zip_recruiter/google). ``residential`` (default)
    # avoids the datacenter/home-IP block outright — the top principle is "never get
    # blocked". Flip to ``vps`` to conserve residential GB and rely on the
    # block-detect escalation leg instead, or ``direct``. One of PROXY_POLICIES.
    block_prone_proxy_policy: str = Field(
        default=PROXY_POLICY_RESIDENTIAL, alias="BLOCK_PRONE_PROXY_POLICY"
    )
    # Default proxy policy for EVERY OTHER source (keyless Greenhouse/Lever, custom
    # RSS, your own SearXNG, the offline sample). ``direct`` (default) — these
    # egress cleanly and must never burn residential GB. One of PROXY_POLICIES.
    default_proxy_policy: str = Field(
        default=PROXY_POLICY_DIRECT, alias="DEFAULT_PROXY_POLICY"
    )
    # Per-source policy OVERRIDES: comma-separated ``source_key=policy`` pairs
    # (e.g. ``jobspy:glassdoor=residential,searxng=vps``). Same comma-shape as
    # ``discovery_proxies``/``discovery_rss_feeds``. Empty (default) ⇒ the two
    # defaults above govern every source. A typo'd policy is rejected at load.
    discovery_source_proxy_policy: str = Field(
        default="", alias="DISCOVERY_SOURCE_PROXY_POLICY"
    )
    # Sticky residential session (ST-5: "browse→apply = one identity"). When True
    # the forwarder proxy URL is decorated with a per-flow DataImpulse ``sessid``
    # label so a whole flow shares ONE residential IP (reads as one human, ~30-min
    # hold) instead of hopping IPs mid-flow (a detection tell + reputation churn).
    residential_sticky_sessions: bool = Field(
        default=True, alias="RESIDENTIAL_STICKY_SESSIONS"
    )
    # The DataImpulse sticky-session label injected into the proxy username
    # (``user-sessid-<id>``). ``{sessid}`` is substituted per flow. Change only if
    # your forwarder expects a different label convention.
    residential_sessid_label: str = Field(
        default="sessid-{sessid}", alias="RESIDENTIAL_SESSID_LABEL"
    )

    # --- EPIC STEALTH: scraper pacing / rate-limit / backoff (ST-5) -------------
    # Human-like pacing conserves residential reputation (never hammer a board).
    # Per-source (per-board) sliding-window rate limit — threaded into the discovery
    # aggregator's ``PerBoardRateLimiter`` so one aggressive board never hogs a run.
    discovery_rate_max_calls: int = Field(
        default=5, ge=1, alias="DISCOVERY_RATE_MAX_CALLS"
    )
    discovery_rate_period_seconds: float = Field(
        default=60.0, gt=0, alias="DISCOVERY_RATE_PERIOD_SECONDS"
    )
    # Minimum human-like delay (seconds) between paced scrape requests within a run.
    discovery_min_request_interval_seconds: float = Field(
        default=2.0, ge=0, alias="DISCOVERY_MIN_REQUEST_INTERVAL_SECONDS"
    )
    # Exponential backoff on block-detect (400/403/429/503): base * multiplier**n,
    # clamped to the max; ``discovery_block_max_retries`` bounds the residential
    # escalation retries before a source is given up for the run.
    discovery_backoff_base_seconds: float = Field(
        default=2.0, ge=0, alias="DISCOVERY_BACKOFF_BASE_SECONDS"
    )
    discovery_backoff_multiplier: float = Field(
        default=2.0, ge=1.0, alias="DISCOVERY_BACKOFF_MULTIPLIER"
    )
    discovery_backoff_max_seconds: float = Field(
        default=60.0, ge=0, alias="DISCOVERY_BACKOFF_MAX_SECONDS"
    )
    discovery_block_max_retries: int = Field(
        default=1, ge=0, alias="DISCOVERY_BLOCK_MAX_RETRIES"
    )

    # --- EPIC STEALTH: browser stealth flags surfaced (ST-3/ST-4) --------------
    # These are preset DEFAULTS surfaced here + threaded into the browser launch by
    # the browser adapter (Integrate wiring). ``browser_engine`` (camoufox) and the
    # residential fields above are reused by the apply-flow browser; the two flags
    # below suppress the WebRTC/DNS leaks that would reveal the real IP behind a
    # residential proxy (ST-5: no IPv6/DNS/WebRTC leaks).
    browser_suppress_webrtc: bool = Field(
        default=True, alias="BROWSER_SUPPRESS_WEBRTC"
    )
    browser_suppress_dns_leak: bool = Field(
        default=True, alias="BROWSER_SUPPRESS_DNS_LEAK"
    )

    # Browser engine the agent drives for all pre-fill / ATS automation — every
    # outbound browser request routes through it (FR-STEALTH-1, FR-PREFILL-1).
    # ``camoufox`` (default) is the Firefox-based anti-detect browser; ``chromium``
    # is the patchright + real Chrome/Chromium path (also used for the Proxmox
    # Windows CDP backend). Camoufox injects its own coherent fingerprint, so the
    # Chrome-specific channel/init-script below is consulted only by ``chromium``.
    browser_engine: str = Field(default=BROWSER_ENGINE_CAMOUFOX, alias="BROWSER_ENGINE")

    # Driving browser channel (FR-STEALTH-1, FR-PREFILL-1). Default real Google
    # Chrome (the coherent-identity foundation: genuine Chrome TLS/JA3 + correct
    # Sec-CH-UA client hints). ``chromium`` is a less-coherent fallback. Threaded
    # into launch_persistent_context(channel=...). Headful only (no headless tell).
    # Only used by the ``chromium`` browser engine (Camoufox manages its own binary).
    browser_channel: str = Field(default=BROWSER_CHANNEL_CHROME, alias="BROWSER_CHANNEL")

    # Drive a REAL browser (patchright + a real Chrome/Chromium binary) for pre-fill
    # instead of the hermetic in-memory FakePageSource. Default OFF so tests/CI stay
    # browserless and deterministic; the production deploy sets BROWSER_REAL=true (see
    # docker-compose.prod.yml) so the api container actually launches Chrome and
    # pre-fills live ATS pages (FR-PREFILL-1/2). Without this the engine would only
    # ever SIMULATE pre-fill.
    browser_real: bool = Field(default=False, alias="BROWSER_REAL")

    # Universal-ATS field-match-rate floor (issue #177, FR-PREFILL-2/6). The pre-fill
    # loop fills ANY form via the generic live-DOM driver (issue #173); this is the
    # minimum acceptable ratio of fields actually filled to fields detected over a run.
    # When at least one field was detected but the run came in BELOW this floor — the
    # selectors missed / nothing mapped — the application is FLAGGED as a probable
    # wrong-ATS / near-empty fill for human review instead of being offered for final
    # submission (never silently submit garbage). Default 0.2 (20%); ge=0/le=1 reject a
    # nonsensical floor at load. Set 0 to disable the flag (always offer for review).
    ats_match_rate_floor: float = Field(
        default=0.2, ge=0.0, le=1.0, alias="ATS_MATCH_RATE_FLOOR"
    )

    # Let the engine CREATE an account at the ATS account gate from a predefined
    # credential set (ADR-0004), not just log in to an existing one. Default OFF: the
    # account-create submit stays an irreducible hand-off unless the operator opts in.
    # Server-derived gate — never opted in by a request input. CAPTCHA + email/SMS
    # verification + final-submit remain irreducible regardless.
    allow_automated_accounts: bool = Field(default=False, alias="ALLOW_AUTOMATED_ACCOUNTS")

    # --- CAPTCHA handling (issue #350, opt-in, safe-by-default) ---------------
    # A driven solver port sits in FRONT of the existing captcha human-handoff. ALL
    # defaults reproduce today's behavior (the run pauses and hands off to the operator):
    #   ``human``   (default) — every captcha hands off to the operator + backstop.
    #   ``avoid``   — score/behavioral families (reCAPTCHA v3, Turnstile) proceed via
    #                 the shipped stealth layer; interactive challenges still hand off.
    #   ``service`` — interactive challenges (reCAPTCHA v2, hCaptcha) are solved by token
    #                 injection via the third-party service; score/behavioral still avoid;
    #                 any failure or unconfigured key degrades to the hand-off.
    # NOTHING here lets the engine self-authorize past account-create / final-submit —
    # those stay irreducible human steps. This only removes the *captcha* manual step
    # when the operator explicitly opts in.
    captcha_strategy: str = Field(default="human", alias="CAPTCHA_STRATEGY")  # human|avoid|service
    # The third-party solving service used by the ``service`` strategy.
    captcha_service: str = Field(default="capsolver", alias="CAPTCHA_SERVICE")
    # The solver-service API key. Sealed via the credential vault on seed (never logged);
    # empty (default) ⇒ the ``service`` strategy has no key and cleanly degrades to hand-off.
    captcha_api_key: str = Field(default="", alias="CAPTCHA_API_KEY")
    # Optional egress proxy threaded into the solver-service call (keeps the solve on the
    # same residential exit as the browser). Empty (default) ⇒ direct.
    egress_proxy: str = Field(default="", alias="EGRESS_PROXY")

    # --- Computer use / desktop control (FR-CUA, docs/spec/computer-use.md) ---
    # Background desktop control (click/type/scroll/drag over the OS accessibility
    # tree) confined to the sandbox/takeover surface, complementing the browser path.
    # ``noop`` (default) records calls + performs NO side effects (the CI/test backend);
    # ``cua`` selects the real TryCUA cua-driver adapter, which itself degrades to noop
    # semantics until the driver is baked into the sandbox image (FR-CUA-12). Names
    # mirror the upstream env switches for lift-and-shift clarity (the white-label rule
    # applies to user-facing copy, not these engine env keys).
    computer_use_backend: str = Field(default="noop", alias="COMPUTER_USE_BACKEND")
    # Override the driver binary path for tests/CI/local builds (else detected on PATH).
    cua_driver_cmd: str = Field(default="", alias="CUA_DRIVER_CMD")
    # Capture mode: ``som`` (screenshot with numbered elements, default) or ``ax``
    # (accessibility-tree text only — the degraded path when the model lacks vision,
    # FR-CUA-11).
    computer_use_mode: str = Field(default="som", alias="COMPUTER_USE_MODE")
    # Approval posture: ``manual`` (review each action, default) or ``session`` (one
    # authorization per open takeover). Maps to review-before-act (FR-CUA-4).
    computer_use_approvals: str = Field(default="manual", alias="COMPUTER_USE_APPROVALS")
    # Driver anonymous telemetry — OFF by default (upstream CUA_DRIVER_RS_TELEMETRY_ENABLED=0).
    cua_telemetry: bool = Field(default=False, alias="CUA_TELEMETRY")
    # Override: force the driver to report as AVAILABLE even when ``shutil.which()``
    # cannot find it on PATH. Use when the ``cua-driver`` binary is baked into the
    # sandbox image at a non-standard location or is invoked via a custom launcher.
    # Default False — the driver is detected via PATH probe. Set True to skip the
    # PATH check and assume the driver is present (FR-CUA-12 gate override).
    cua_driver_override_available: bool = Field(
        default=False, alias="CUA_DRIVER_OVERRIDE_AVAILABLE"
    )

    # Timezone/locale pinned to the residential EGRESS geolocation (FR-STEALTH-1
    # <-> FR-STEALTH-4) so tz/locale <-> IP are consistent. Derive these from the
    # egress IP's region in a real deployment; the defaults are a sensible coherent
    # pair (Phoenix has no DST, a stable choice). Threaded into the browser context
    # (timezone_id / locale) so the fingerprint never contradicts the exit IP.
    egress_timezone: str = Field(default="America/Phoenix", alias="EGRESS_TIMEZONE")
    egress_locale: str = Field(default="en-US", alias="EGRESS_LOCALE")

    # Takeover desktop (FR-SANDBOX-2/3, FR-PREFILL-5). When the agent hits an
    # irreducible human step (CAPTCHA / verification / final submit), the user takes
    # over via a one-click live session. The takeover environment is a containerized,
    # web-streamed FULL Ubuntu desktop whose DE is configurable here (default
    # Cinnamon; Xfce + full GNOME also selectable). All three run on X11 (not Wayland)
    # for remote streaming + automation. ``gnome`` uses the local custom webtop image.
    takeover_desktop: str = Field(default=TAKEOVER_DESKTOP_CINNAMON, alias="TAKEOVER_DESKTOP")
    # Advanced override: pin an exact takeover-desktop image (wins over the DE table).
    takeover_desktop_image: str = Field(default="", alias="TAKEOVER_DESKTOP_IMAGE")
    # Swappable remote-view backend (FR-SANDBOX-2): ``webtop`` (full desktop, default)
    # or ``neko`` (browser-only). Neko remains a selectable backend.
    remote_view_backend: str = Field(default=REMOTE_VIEW_WEBTOP, alias="REMOTE_VIEW_BACKEND")
    # Base URL the streamed takeover desktop is published at (the one-click link host).
    takeover_desktop_base_url: str = Field(
        default="https://sandbox.local/webtop", alias="TAKEOVER_DESKTOP_BASE_URL"
    )

    # --- Sandbox backend selection (FR-SANDBOX-1, FR-STEALTH-1) --------------
    # ``local`` (default) = the existing webtop/Neko container path. ``proxmox-windows``
    # = a native Proxmox Windows VM where the engine drives + the human takes over a
    # REAL Google Chrome inside a real, licensed Windows VM (genuine Windows
    # fingerprint, ZERO spoofing). The proxmox-windows backend is GATED on the OOBE
    # sandbox-connection step (Proxmox API + RDP login data collected in the UI).
    sandbox_backend: str = Field(default=SANDBOX_BACKEND_LOCAL, alias="SANDBOX_BACKEND")
    # Stealth persona: ``linux`` (coherent spoof, default for the local backend) or
    # ``native`` (no fingerprint override — the real browser identity). When empty,
    # the persona is derived from the backend: ``native`` for proxmox-windows (it IS
    # Windows), ``linux`` otherwise. An explicit value still validates.
    stealth_persona: str = Field(default="", alias="STEALTH_PERSONA")

    # --- Proxmox / Windows connection (non-secret in app_config; SECRETS go to
    # the credential vault via the OOBE sandbox-connection step, FR-VAULT-3). These
    # env defaults are a fallback ONLY; the wizard-persisted config wins. The token
    # SECRET + RDP password are NEVER read from env into logs — they are vaulted.
    proxmox_api_url: str = Field(default="", alias="PROXMOX_API_URL")
    proxmox_node: str = Field(default="", alias="PROXMOX_NODE")
    proxmox_token_id: str = Field(default="", alias="PROXMOX_TOKEN_ID")
    proxmox_template_vmid: int = Field(default=0, alias="PROXMOX_TEMPLATE_VMID")
    proxmox_clone_mode: str = Field(
        default=PROXMOX_CLONE_SNAPSHOT_REVERT, alias="PROXMOX_CLONE_MODE"
    )
    # Chrome remote-debugging (CDP) endpoint inside the Windows VM.
    proxmox_cdp_host: str = Field(default="", alias="PROXMOX_CDP_HOST")  # "" = guest IP
    proxmox_cdp_port: int = Field(default=9222, alias="PROXMOX_CDP_PORT")
    # RDP username (the password is a vault secret, never here in cleartext logs).
    proxmox_rdp_username: str = Field(default="", alias="PROXMOX_RDP_USERNAME")
    # Takeover method + (for web-console) a URL template. ``{host}``/``{vmid}``/
    # ``{node}``/``{token}`` placeholders are substituted per session.
    proxmox_takeover_method: str = Field(
        default=PROXMOX_TAKEOVER_RDP, alias="PROXMOX_TAKEOVER_METHOD"
    )
    proxmox_takeover_url_template: str = Field(
        default="", alias="PROXMOX_TAKEOVER_URL_TEMPLATE"
    )

    # --- #305 Plan-as-Data (experimental, default OFF) ----------------------
    # When true AND an LLM is configured, the pre-fill loop emits a typed Plan
    # per page (via LLMPlanner) and executes each op through the existing guarded
    # actions. The STOP boundary is still enforced. Default OFF: behaviour is
    # byte-identical to today until an operator opts in.
    prefill_use_planner: bool = Field(default=False, alias="PREFILL_USE_PLANNER")

    # --- Smart LLM routing (#298) -------------------------------------------
    # When ON, a SmartLlmRouter inspects the configured model endpoints
    # (ModelEndpointService) and REORDERS the tier ladder so a router-preferred
    # endpoint (e.g. a local Ollama/OpenAI-compatible model under the
    # local-preference policy) is walked first by OpenAICompatibleLLM. The
    # existing context-window tier-walk/fallback is preserved within that order.
    # Default ON: the router reorders the ladder per its policy. This is safe
    # because the reorder is additive (every tier is retained as a fallback
    # rung) and a no-op when no router-preferred endpoint exists — with the
    # default prefer-local policy and no local endpoint configured, the ladder
    # is returned unchanged (see order_ladder_by_router's no-stranding path).
    # Set LLM_SMART_ROUTING=false to pin the byte-identical cloud-first ladder.
    llm_smart_routing: bool = Field(default=True, alias="LLM_SMART_ROUTING")
    # Prefer a local model when smart routing is ON and a local endpoint is
    # configured and online (keeps tokens free/on-box, FR-LLM-5/NFR-TOKEN-1).
    llm_smart_routing_prefer_local: bool = Field(
        default=True, alias="LLM_SMART_ROUTING_PREFER_LOCAL"
    )
    # --- EPIC MODEL-CONFIG: env-overridable preset model names ---------------
    # The documented per-use-case preset MODELS, overridable via env so nothing
    # is a hardcoded decision even at the config layer (the UI overlays these
    # onto ``LLM_USE_CASES`` when rendering the Settings surface). "" for a
    # use case means "whatever the configured tier ladder serves" (fresh-install
    # zero-config: everything resolves to the ladder, so the app works OOTB). An
    # operator's explicit per-use-case binding (persisted by SetupService) always
    # wins over these presets. See docs/APPLICANT-BACKLOG.md §EPIC MODEL-CONFIG.
    llm_preset_scoring_model: str = Field(default="", alias="LLM_PRESET_SCORING_MODEL")
    llm_preset_drafting_model: str = Field(
        default="deepseek-v4-flash", alias="LLM_PRESET_DRAFTING_MODEL"
    )
    llm_preset_research_model: str = Field(
        default="", alias="LLM_PRESET_RESEARCH_MODEL"
    )
    llm_preset_chat_model: str = Field(default="", alias="LLM_PRESET_CHAT_MODEL")
    llm_preset_embeddings_model: str = Field(
        default="", alias="LLM_PRESET_EMBEDDINGS_MODEL"
    )
    # --- Verified local-only private mode (P2-11) ----------------------------
    # When ON, the engine's LLM ladder REFUSES every tier whose base_url is not
    # an on-box/private-network host (core/rules/private_endpoints.py — strict
    # host classification, NOT the router's loose local-preference heuristic).
    # This is a hard privacy mode, not a preference: non-private tiers are
    # dropped at ladder construction inside SetupService, so the SAME filter
    # governs the effective ladder, the LLM-configured gate, and setup-status —
    # a stranded cloud-only config honestly reports "not configured" instead of
    # silently keeping a cloud fallback (H2). The stored tier config is left
    # untouched; turning the mode off restores it. What still leaves the box in
    # this mode (job-board discovery queries, the automation browser submitting
    # what the user approved, opt-in notification fan-out) is documented in
    # docs/private-mode.md — the mode's claim is precisely "profile/job data
    # never goes to a third-party LLM API".
    llm_local_only: bool = Field(default=False, alias="LLM_LOCAL_ONLY")

    # --- Opt-in error telemetry (P5-3) ---------------------------------------
    # OFF by default (opt-in, not opt-out) and HARD-disabled whenever
    # ``llm_local_only`` is on, regardless of this flag — enforced in
    # ``SetupService.telemetry_status``, the one place every consumer (the
    # global exception handler via ``observability.telemetry.TelemetryReporter``)
    # reads before sending anything. These are only the env-sourced DEFAULTS;
    # an operator can override both at runtime in Settings > System (persisted
    # like every other Settings > Automation knob), which takes effect with no
    # restart. There is no Applicant-operated collection endpoint and no
    # hardcoded third-party default — ``telemetry_endpoint`` must be an
    # operator-supplied sink (self-hosted or otherwise) or nothing is ever sent.
    telemetry_enabled: bool = Field(default=False, alias="TELEMETRY_ENABLED")
    telemetry_endpoint: str = Field(default="", alias="TELEMETRY_ENDPOINT")

    # --- Pre-submit safety (G07) --------------------------------------------
    # Scam/ghost-job detection: maximum allowed age (in days) for a listing.
    # Postings older than this are blocked before the pipeline starts.
    presubmit_max_listing_age_days: int = Field(
        default=90, ge=0, alias="PRESUBMIT_MAX_LISTING_AGE_DAYS"
    )
    # Duplicate-application cooldown: how many days must pass before the same
    # (company, role) pair may be applied to again.
    presubmit_duplicate_cooldown_days: int = Field(
        default=30, ge=0, alias="PRESUBMIT_DUPLICATE_COOLDOWN_DAYS"
    )
    # Per-company application volume cap: max applications per company per day.
    presubmit_max_apps_per_company_per_day: int = Field(
        default=3, ge=0, alias="PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY"
    )
    # Eligibility filter: when True, the engine checks work-authorization data
    # from the onboarding intake against posting requirements (sponsorship/
    # clearance) before starting the pipeline.
    presubmit_eligibility_enabled: bool = Field(
        default=True, alias="PRESUBMIT_ELIGIBILITY_ENABLED"
    )

    @model_validator(mode="after")
    def _apply_production_mode(self) -> Self:
        """Apply the production preset when APPLICANT_MODE=production.

        Sets the five real-integration flags to their production defaults.
        Individual env overrides still win because this runs after model
        construction - any explicit env var already landed on the field and is
        left untouched when the preset disagrees with the default.
        """
        if (self.applicant_mode or "").strip().lower() != "production":
            return self
        explicit = self.model_fields_set
        if "browser_real" not in explicit:
            object.__setattr__(self, "browser_real", True)
        if "discovery_live" not in explicit:
            object.__setattr__(self, "discovery_live", True)
        if "notifications_live" not in explicit:
            object.__setattr__(self, "notifications_live", True)
        if "orchestrator_backend" not in explicit:
            object.__setattr__(self, "orchestrator_backend", "dbos")
        if "scheduler_enabled" not in explicit:
            object.__setattr__(self, "scheduler_enabled", True)
        return self

    @property
    def scheduler_should_run(self) -> bool:
        """True when the scheduler should be active: either explicitly enabled or in production mode."""
        return self.scheduler_enabled or (self.applicant_mode or "").strip().lower() == "production"

    @property
    def deployment_profile(self) -> str:
        """The deployment profile derived from applicant_mode (empty = hermetic)."""
        return self.applicant_mode

    @field_validator("takeover_desktop")
    @classmethod
    def _validate_takeover_desktop(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in TAKEOVER_DESKTOPS:
            raise ValueError(
                f"TAKEOVER_DESKTOP={v!r} is invalid; choose one of {TAKEOVER_DESKTOPS} "
                "(default 'cinnamon')."
            )
        return norm

    @field_validator("prefix_cache")
    @classmethod
    def _validate_prefix_cache(cls, v: str) -> str:
        # Reject a typo at load instead of silently disabling prefix caching.
        norm = (v or "").strip().lower()
        if norm not in PREFIX_CACHE_MODES:
            raise ValueError(
                f"PREFIX_CACHE={v!r} is invalid; choose one of {PREFIX_CACHE_MODES} "
                "(default 'auto')."
            )
        return norm

    @field_validator("egress_mode")
    @classmethod
    def _validate_egress_mode(cls, v: str) -> str:
        # Item 12 (SECURITY): accept ONLY the two valid egress modes (strip/lower) so a
        # typo (e.g. "residential_proxy"/"diretc") is rejected at load instead of being
        # silently coerced to direct egress.
        norm = (v or "").strip().lower()
        if norm not in EGRESS_MODES:
            raise ValueError(
                f"EGRESS_MODE={v!r} is invalid; choose one of {EGRESS_MODES} "
                "(default 'direct')."
            )
        return norm

    @field_validator("block_prone_proxy_policy", "default_proxy_policy")
    @classmethod
    def _validate_proxy_policy(cls, v: str) -> str:
        # EPIC STEALTH (ST-2): reject a typo'd policy at load rather than silently
        # coercing — a wrong value must not change which egress a source uses.
        norm = (v or "").strip().lower()
        if norm not in PROXY_POLICIES:
            raise ValueError(
                f"proxy policy {v!r} is invalid; choose one of {PROXY_POLICIES} "
                "(default 'residential' for block-prone, 'direct' otherwise)."
            )
        return norm

    @field_validator("discovery_source_proxy_policy")
    @classmethod
    def _validate_source_proxy_policy(cls, v: str) -> str:
        # EPIC STEALTH (ST-2): validate the ``source_key=policy,...`` override
        # shape at load — a malformed entry or an unknown policy raises here (via
        # ``parse_source_proxy_policy``) instead of being silently dropped at wiring.
        # The raw string is stored unchanged; the container parses it into a dict.
        parse_source_proxy_policy(v)
        return v

    @field_validator("captcha_strategy")
    @classmethod
    def _validate_captcha_strategy(cls, v: str) -> str:
        # Reject a typo at load instead of silently coercing — a wrong value must not
        # change the safe default behavior. ``human`` is the safe path.
        norm = (v or "").strip().lower()
        if norm not in CAPTCHA_STRATEGIES:
            raise ValueError(
                f"CAPTCHA_STRATEGY={v!r} is invalid; choose one of {CAPTCHA_STRATEGIES} "
                "(default 'human' — hand off to the operator)."
            )
        return norm

    @field_validator("browser_channel")
    @classmethod
    def _validate_browser_channel(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in BROWSER_CHANNELS:
            raise ValueError(
                f"BROWSER_CHANNEL={v!r} is invalid; choose one of {BROWSER_CHANNELS} "
                "(default 'chrome' — real Google Chrome)."
            )
        return norm

    @field_validator("browser_engine")
    @classmethod
    def _validate_browser_engine(cls, v: str) -> str:
        # Reject a typo at load instead of silently falling back to a different
        # engine (which would route automation traffic through the wrong browser).
        norm = (v or "").strip().lower()
        if norm not in BROWSER_ENGINES:
            raise ValueError(
                f"BROWSER_ENGINE={v!r} is invalid; choose one of {BROWSER_ENGINES} "
                "(default 'camoufox' — the anti-detect browser)."
            )
        return norm

    @field_validator("remote_view_backend")
    @classmethod
    def _validate_remote_view_backend(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in REMOTE_VIEW_BACKENDS:
            raise ValueError(
                f"REMOTE_VIEW_BACKEND={v!r} is invalid; choose one of "
                f"{REMOTE_VIEW_BACKENDS} (default 'webtop')."
            )
        return norm

    @field_validator("sandbox_backend")
    @classmethod
    def _validate_sandbox_backend(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in SANDBOX_BACKENDS:
            raise ValueError(
                f"SANDBOX_BACKEND={v!r} is invalid; choose one of {SANDBOX_BACKENDS} "
                "(default 'local')."
            )
        return norm

    @field_validator("stealth_persona")
    @classmethod
    def _validate_stealth_persona(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        # Empty is allowed: the persona is then derived from the backend (see
        # ``stealth_persona_resolved``). A non-empty value must be a known persona.
        if norm and norm not in STEALTH_PERSONAS:
            raise ValueError(
                f"STEALTH_PERSONA={v!r} is invalid; choose one of {STEALTH_PERSONAS} "
                "(or leave empty to derive from SANDBOX_BACKEND)."
            )
        return norm

    @field_validator("proxmox_clone_mode")
    @classmethod
    def _validate_clone_mode(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in PROXMOX_CLONE_MODES:
            raise ValueError(
                f"PROXMOX_CLONE_MODE={v!r} is invalid; choose one of {PROXMOX_CLONE_MODES} "
                "(default 'snapshot-revert')."
            )
        return norm

    @field_validator("proxmox_takeover_method")
    @classmethod
    def _validate_takeover_method(cls, v: str) -> str:
        norm = (v or "").strip().lower()
        if norm not in PROXMOX_TAKEOVER_METHODS:
            raise ValueError(
                f"PROXMOX_TAKEOVER_METHOD={v!r} is invalid; choose one of "
                f"{PROXMOX_TAKEOVER_METHODS} (default 'rdp')."
            )
        return norm

    @property
    def stealth_persona_resolved(self) -> str:
        """The effective persona (FR-STEALTH-1).

        An explicit ``STEALTH_PERSONA`` wins; otherwise it is DERIVED from the
        backend: ``native`` for ``proxmox-windows`` (real Windows + real Chrome — no
        spoof needed), ``linux`` for the local backend (coherent honest spoof).
        """
        if self.stealth_persona:
            return self.stealth_persona
        if self.sandbox_backend == SANDBOX_BACKEND_PROXMOX_WINDOWS:
            return STEALTH_PERSONA_NATIVE
        return STEALTH_PERSONA_LINUX

    @property
    def is_proxmox_windows_backend(self) -> bool:
        """True when the native Proxmox Windows VM backend is selected."""
        return self.sandbox_backend == SANDBOX_BACKEND_PROXMOX_WINDOWS

    @property
    def takeover_desktop_image_resolved(self) -> str:
        """The container image for the configured takeover DE (FR-SANDBOX-2)."""
        return resolve_takeover_image(self.takeover_desktop, self.takeover_desktop_image)

    @property
    def llm_configured(self) -> bool:
        """True once enough LLM settings exist to satisfy the OOBE gate (FR-UI-5)."""
        return bool(self.llm_provider and self.llm_model)

    def build_stealth_config(self) -> StealthConfig:
        """Materialize the EPIC STEALTH per-source proxy policy (ST-2/ST-5).

        The one-liner the container passes into ``build_default_discovery`` so the
        residential forwarder is applied SELECTIVELY (block-prone scrape sources +
        on block-detect) while keyless ATS / APIs stay direct. Folds an
        operator-supplied ``discovery_proxies`` pool in as ADDITIONAL residential
        exits (they share the block-prone concept). Pure — reads only settings.

        # WIRING: the Integrate step should call ``settings.build_stealth_config()``
        # and thread the result into ``build_default_discovery(stealth=..., flow_sessid=
        # new_sessid(<campaign/flow key>))`` in container.py, and reuse
        # ``residential_proxy_*`` / ``browser_suppress_*`` for the browser launch.
        """
        extra = tuple(
            p.strip() for p in (self.discovery_proxies or "").split(",") if p.strip()
        )
        return _build_stealth_config(
            residential_proxy_url=self.residential_proxy_url,
            residential_proxy_enabled=self.residential_proxy_enabled,
            vps_proxy_url=self.vps_proxy_url,
            block_prone_policy=self.block_prone_proxy_policy,
            default_policy=self.default_proxy_policy,
            source_proxy_policy=self.discovery_source_proxy_policy,
            extra_residential_proxies=extra,
            sticky_sessions=self.residential_sticky_sessions,
            sessid_label=self.residential_sessid_label,
            rate_max_calls=self.discovery_rate_max_calls,
            rate_period_seconds=self.discovery_rate_period_seconds,
            min_request_interval_seconds=self.discovery_min_request_interval_seconds,
            backoff_base_seconds=self.discovery_backoff_base_seconds,
            backoff_multiplier=self.discovery_backoff_multiplier,
            backoff_max_seconds=self.discovery_backoff_max_seconds,
            block_max_retries=self.discovery_block_max_retries,
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings (one instance per process)."""
    return Settings()
