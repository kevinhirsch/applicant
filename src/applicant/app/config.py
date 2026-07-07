"""Application settings (pydantic-settings, env-driven; zero-CLI, NFR-ZEROCLI-1)."""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    # (default) is the hermetic in-process trio (no deps; boot-/test-safe);
    # ``bridge`` reaches the front-door substrate (workspace/services/memory/) over
    # the engine->workspace callback channel (agent-intelligence.md §10 — recommended
    # placement). The bridge degrades to empty behavior when that channel is OFF.
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


@lru_cache
def get_settings() -> Settings:
    """Return cached settings (one instance per process)."""
    return Settings()
