"""Application settings (pydantic-settings, env-driven; zero-CLI, NFR-ZEROCLI-1)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def llm_configured(self) -> bool:
        """True once enough LLM settings exist to satisfy the OOBE gate (FR-UI-5)."""
        return bool(self.llm_provider and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings (one instance per process)."""
    return Settings()
