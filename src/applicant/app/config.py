"""Application settings (pydantic-settings, env-driven; zero-CLI, NFR-ZEROCLI-1)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
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
BROWSER_CHANNEL_CHROME = "chrome"
BROWSER_CHANNEL_CHROMIUM = "chromium"
BROWSER_CHANNELS = (BROWSER_CHANNEL_CHROME, BROWSER_CHANNEL_CHROMIUM)


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

    # Credential vault (FR-VAULT-3)
    credential_keyfile: str = Field(default="secrets/master.key", alias="CREDENTIAL_KEYFILE")

    # Durable orchestration (FR-DUR-3). "shim" (default, no PG) or "dbos".
    orchestrator_backend: str = Field(default="shim", alias="ORCHESTRATOR_BACKEND")
    checkpoint_dir: str = Field(default=".applicant_checkpoints", alias="CHECKPOINT_DIR")

    # Scheduler (FR-DIG-1, FR-NOTIF-2, NFR-247-1). OFF by default so the default
    # test lane / TestClient never spins a live background loop; prod compose sets
    # it True (zero-CLI via env). When True the lifespan starts the asyncio tick
    # loop on the shim, or DBOS @scheduled drives it on the DBOS path.
    scheduler_enabled: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    scheduler_interval_seconds: float = Field(
        default=60.0, alias="SCHEDULER_INTERVAL_SECONDS"
    )

    # Durable queues (FR-DUR-2): sandbox concurrency cap + per-provider LLM rate.
    sandbox_concurrency: int = Field(default=3, alias="SANDBOX_CONCURRENCY")
    llm_rate_limit: int = Field(default=0, alias="LLM_RATE_LIMIT")  # 0 disables
    llm_rate_period: float = Field(default=60.0, alias="LLM_RATE_PERIOD")

    # Observability (FR-OBS-1)
    log_format: str = Field(default="pretty", alias="LOG_FORMAT")  # pretty | json
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Notifications (FR-NOTIF-1). Live network send is OFF by default so the default
    # test lane never touches Discord/SMTP; flip on in a real deployment (zero-CLI).
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")
    apprise_urls: str = Field(default="", alias="APPRISE_URLS")
    notifications_live: bool = Field(default=False, alias="NOTIFICATIONS_LIVE")

    # Fonts (FR-FONT-1/2). A confined, configurable dir for runtime font installs;
    # all filesystem/fc-cache ops are restricted to this dir (never system-wide).
    fonts_dir: str = Field(default=".applicant_fonts", alias="FONTS_DIR")

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

    # Driving browser channel (FR-STEALTH-1, FR-PREFILL-1). Default real Google
    # Chrome (the coherent-identity foundation: genuine Chrome TLS/JA3 + correct
    # Sec-CH-UA client hints). ``chromium`` is a less-coherent fallback. Threaded
    # into launch_persistent_context(channel=...). Headful only (no headless tell).
    browser_channel: str = Field(default=BROWSER_CHANNEL_CHROME, alias="BROWSER_CHANNEL")

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
