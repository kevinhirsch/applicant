"""Unit tests for applicant.app.config: Settings, validators, and lru_cache helper."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from applicant.app.config import (
    BROWSER_CHANNEL_CHROME,
    BROWSER_CHANNEL_CHROMIUM,
    BROWSER_CHANNELS,
    BROWSER_ENGINE_CAMOUFOX,
    BROWSER_ENGINE_CHROMIUM,
    BROWSER_ENGINES,
    CAPTCHA_STRATEGIES,
    CAPTCHA_STRATEGY_HUMAN,
    EGRESS_MODES,
    PREFIX_CACHE_MODES,
    PROXMOX_CLONE_MODES,
    PROXMOX_TAKEOVER_METHODS,
    REMOTE_VIEW_BACKENDS,
    SANDBOX_BACKENDS,
    STEALTH_PERSONA_LINUX,
    STEALTH_PERSONA_NATIVE,
    STEALTH_PERSONAS,
    TAKEOVER_DESKTOP_CINNAMON,
    TAKEOVER_DESKTOP_GNOME,
    TAKEOVER_DESKTOP_IMAGES,
    TAKEOVER_DESKTOP_PANTHEON,
    TAKEOVER_DESKTOP_XFCE,
    TAKEOVER_DESKTOPS,
    Settings,
    get_settings,
    resolve_takeover_image,
)


# ---------------------------------------------------------------------------
# Autouse: clear the lru_cache before each test so tests are process-isolated
# (parallel-safe with xdist).
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Clear the lru_cache on get_settings between tests."""
    get_settings.cache_clear()


# ===================================================================
# Default values
# ===================================================================

@pytest.mark.unit
class TestDefaults:
    """Settings constructed with no env overrides use documented defaults."""

    def test_applicant_mode_empty(self) -> None:
        s = Settings()
        assert s.applicant_mode == ""

    def test_database_url_default(self) -> None:
        s = Settings()
        assert s.database_url == (
            "postgresql+psycopg://applicant:applicant@localhost:5432/applicant"
        )

    def test_app_static_dir(self) -> None:
        s = Settings()
        assert s.app_static_dir == "frontend/static"

    def test_truth_policy_balanced(self) -> None:
        s = Settings()
        assert s.truth_policy == "balanced"

    def test_parse_verify_enabled_true(self) -> None:
        s = Settings()
        assert s.parse_verify_enabled is True

    def test_context_compress_threshold(self) -> None:
        s = Settings()
        assert s.context_compress_threshold == 64000

    def test_prefix_cache_auto(self) -> None:
        s = Settings()
        assert s.prefix_cache == "auto"

    def test_browser_engine_camoufox(self) -> None:
        s = Settings()
        assert s.browser_engine == BROWSER_ENGINE_CAMOUFOX

    def test_browser_channel_chrome(self) -> None:
        s = Settings()
        assert s.browser_channel == BROWSER_CHANNEL_CHROME

    def test_browser_real_false(self) -> None:
        s = Settings()
        assert s.browser_real is False

    def test_discovery_live_false(self) -> None:
        s = Settings()
        assert s.discovery_live is False

    def test_notifications_live_false(self) -> None:
        s = Settings()
        assert s.notifications_live is False

    def test_orchestrator_backend_shim(self) -> None:
        s = Settings()
        assert s.orchestrator_backend == "shim"

    def test_captcha_strategy_human(self) -> None:
        s = Settings()
        assert s.captcha_strategy == CAPTCHA_STRATEGY_HUMAN

    def test_egress_mode_direct(self) -> None:
        s = Settings()
        assert s.egress_mode == "direct"

    def test_takeover_desktop_cinnamon(self) -> None:
        s = Settings()
        assert s.takeover_desktop == TAKEOVER_DESKTOP_CINNAMON

    def test_remote_view_backend_webtop(self) -> None:
        s = Settings()
        assert s.remote_view_backend == "webtop"

    def test_sandbox_backend_local(self) -> None:
        s = Settings()
        assert s.sandbox_backend == "local"

    def test_stealth_persona_empty(self) -> None:
        s = Settings()
        assert s.stealth_persona == ""

    def test_proxmox_clone_mode_snapshot_revert(self) -> None:
        s = Settings()
        assert s.proxmox_clone_mode == "snapshot-revert"

    def test_proxmox_takeover_method_rdp(self) -> None:
        s = Settings()
        assert s.proxmox_takeover_method == "rdp"

    def test_llm_local_only_false(self) -> None:
        s = Settings()
        assert s.llm_local_only is False

    def test_telemetry_enabled_false(self) -> None:
        s = Settings()
        assert s.telemetry_enabled is False

    def test_scheduler_enabled_true(self) -> None:
        s = Settings()
        assert s.scheduler_enabled is True

    def test_llm_smart_routing_true(self) -> None:
        s = Settings()
        assert s.llm_smart_routing is True

    def test_sandbox_concurrency(self) -> None:
        s = Settings()
        assert s.sandbox_concurrency == 3

    def test_llm_rate_limit(self) -> None:
        s = Settings()
        assert s.llm_rate_limit == 30

    def test_approval_timeout_days(self) -> None:
        s = Settings()
        assert s.approval_timeout_days == 30

    def test_pii_retention_days_zero(self) -> None:
        s = Settings()
        assert s.pii_retention_days == 0

    def test_context_compress_threshold_ge_zero(self) -> None:
        s = Settings()
        assert s.context_compress_threshold >= 0


# ===================================================================
# Environment variable overrides (fields with alias)
# ===================================================================

@pytest.mark.unit
class TestEnvOverrides:
    """Settings picks up env vars by alias name."""

    def test_database_url_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://other:pass@host:5432/db")
        s = Settings()
        assert s.database_url == "postgresql://other:pass@host:5432/db"

    def test_llm_provider_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-12345")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        s = Settings()
        assert s.llm_provider == "openai"
        assert s.llm_base_url == "https://api.openai.com"
        assert s.llm_api_key == "sk-test-12345"
        assert s.llm_model == "gpt-4"

    def test_bool_field_as_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_REAL", "true")
        s = Settings()
        assert s.browser_real is True

    def test_bool_field_as_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCOVERY_LIVE", "false")
        s = Settings()
        assert s.discovery_live is False

    def test_int_field_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXT_COMPRESS_THRESHOLD", "32000")
        s = Settings()
        assert s.context_compress_threshold == 32000

    def test_float_field_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_COST_PER_1K_INPUT_USD", "0.30")
        s = Settings()
        assert s.llm_cost_per_1k_input_usd == 0.30

    def test_enum_field_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_ENGINE", "chromium")
        s = Settings()
        assert s.browser_engine == BROWSER_ENGINE_CHROMIUM

    def test_browser_channel_chromium_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_CHANNEL", "chromium")
        s = Settings()
        assert s.browser_channel == BROWSER_CHANNEL_CHROMIUM

    def test_takeover_desktop_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAKEOVER_DESKTOP", "xfce")
        s = Settings()
        assert s.takeover_desktop == TAKEOVER_DESKTOP_XFCE

    def test_applicant_mode_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPLICANT_MODE", "production")
        s = Settings()
        assert s.applicant_mode == "production"
        # production mode also flips some defaults
        assert s.browser_real is True


# ===================================================================
# Field validators
# ===================================================================

@pytest.mark.unit
class TestFieldValidators:
    """Each @field_validator rejects invalid values and normalises valid ones."""

    @pytest.mark.parametrize(
        "desktop",
        [TAKEOVER_DESKTOP_CINNAMON, TAKEOVER_DESKTOP_XFCE, TAKEOVER_DESKTOP_GNOME, TAKEOVER_DESKTOP_PANTHEON],
    )
    def test_takeover_desktop_valid(self, desktop: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAKEOVER_DESKTOP", desktop)
        s = Settings()
        assert s.takeover_desktop == desktop

    @pytest.mark.parametrize(
        "invalid",
        ["kde", "awesome", "sway", "gnome3", "mate", ""],
    )
    def test_takeover_desktop_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAKEOVER_DESKTOP", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "mode",
        PREFIX_CACHE_MODES,
    )
    def test_prefix_cache_valid(self, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFIX_CACHE", mode)
        s = Settings()
        assert s.prefix_cache == mode

    @pytest.mark.parametrize(
        "invalid",
        ["automatic", "enabled", "disabled", "yes", "no", ""],
    )
    def test_prefix_cache_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PREFIX_CACHE", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "mode",
        EGRESS_MODES,
    )
    def test_egress_mode_valid(self, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EGRESS_MODE", mode)
        s = Settings()
        assert s.egress_mode == mode

    @pytest.mark.parametrize(
        "invalid",
        ["datacenter", "residential", "egress", ""],
    )
    def test_egress_mode_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EGRESS_MODE", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "strategy",
        CAPTCHA_STRATEGIES,
    )
    def test_captcha_strategy_valid(self, strategy: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CAPTCHA_STRATEGY", strategy)
        s = Settings()
        assert s.captcha_strategy == strategy

    @pytest.mark.parametrize(
        "invalid",
        ["avoidance", "solve", "manual", ""],
    )
    def test_captcha_strategy_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CAPTCHA_STRATEGY", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "channel",
        BROWSER_CHANNELS,
    )
    def test_browser_channel_valid(self, channel: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_CHANNEL", channel)
        s = Settings()
        assert s.browser_channel == channel

    @pytest.mark.parametrize(
        "invalid",
        ["firefox", "edge", "safari", ""],
    )
    def test_browser_channel_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_CHANNEL", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "engine",
        BROWSER_ENGINES,
    )
    def test_browser_engine_valid(self, engine: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_ENGINE", engine)
        s = Settings()
        assert s.browser_engine == engine

    @pytest.mark.parametrize(
        "invalid",
        ["firefox", "webkit", "playwright", ""],
    )
    def test_browser_engine_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BROWSER_ENGINE", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "engine",
        REMOTE_VIEW_BACKENDS,
    )
    def test_remote_view_backend_valid(self, engine: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTE_VIEW_BACKEND", engine)
        s = Settings()
        assert s.remote_view_backend == engine

    @pytest.mark.parametrize(
        "invalid",
        ["novnc", "xpra", ""],
    )
    def test_remote_view_backend_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTE_VIEW_BACKEND", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "engine",
        SANDBOX_BACKENDS,
    )
    def test_sandbox_backend_valid(self, engine: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", engine)
        s = Settings()
        assert s.sandbox_backend == engine

    @pytest.mark.parametrize(
        "invalid",
        ["docker", "vmware", ""],
    )
    def test_sandbox_backend_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "persona",
        [STEALTH_PERSONA_LINUX, STEALTH_PERSONA_NATIVE],
    )
    def test_stealth_persona_valid(self, persona: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEALTH_PERSONA", persona)
        s = Settings()
        assert s.stealth_persona == persona

    def test_stealth_persona_empty_allowed(self) -> None:
        """Empty stealth_persona is valid — the resolved property fills it."""
        s = Settings()
        assert s.stealth_persona == ""

    @pytest.mark.parametrize(
        "invalid",
        ["windows", "macos", "android"],
    )
    def test_stealth_persona_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEALTH_PERSONA", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "mode",
        PROXMOX_CLONE_MODES,
    )
    def test_proxmox_clone_mode_valid(self, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROXMOX_CLONE_MODE", mode)
        s = Settings()
        assert s.proxmox_clone_mode == mode

    @pytest.mark.parametrize(
        "invalid",
        ["clone", "full", ""],
    )
    def test_proxmox_clone_mode_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROXMOX_CLONE_MODE", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    @pytest.mark.parametrize(
        "method",
        PROXMOX_TAKEOVER_METHODS,
    )
    def test_proxmox_takeover_method_valid(self, method: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROXMOX_TAKEOVER_METHOD", method)
        s = Settings()
        assert s.proxmox_takeover_method == method

    @pytest.mark.parametrize(
        "invalid",
        ["vnc", "spice", ""],
    )
    def test_proxmox_takeover_method_invalid(self, invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROXMOX_TAKEOVER_METHOD", invalid)
        with pytest.raises(ValueError, match="is invalid"):
            Settings()


# ===================================================================
# Model validator – production mode
# ===================================================================

@pytest.mark.unit
class TestProductionMode:
    """_apply_production_mode flips the five integration-flag defaults."""

    def test_production_sets_live_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPLICANT_MODE", "production")
        s = Settings()
        assert s.browser_real is True
        assert s.discovery_live is True
        assert s.notifications_live is True
        assert s.orchestrator_backend == "dbos"
        assert s.scheduler_enabled is True

    def test_production_preserves_explicit_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit env overrides still win over the production preset."""
        monkeypatch.setenv("APPLICANT_MODE", "production")
        monkeypatch.setenv("BROWSER_REAL", "false")
        monkeypatch.setenv("DISCOVERY_LIVE", "false")
        s = Settings()
        assert s.browser_real is False  # explicit env wins
        assert s.discovery_live is False  # explicit env wins
        # other production flags still apply
        assert s.notifications_live is True
        assert s.orchestrator_backend == "dbos"

    def test_not_production_keeps_defaults(self) -> None:
        s = Settings()
        assert s.browser_real is False
        assert s.discovery_live is False
        assert s.notifications_live is False
        assert s.orchestrator_backend == "shim"

    def test_production_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPLICANT_MODE", "PRODUCTION")
        s = Settings()
        assert s.applicant_mode == "PRODUCTION"
        assert s.browser_real is True

    def test_production_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPLICANT_MODE", "  production  ")
        s = Settings()
        assert s.browser_real is True


# ===================================================================
# Properties
# ===================================================================

@pytest.mark.unit
class TestProperties:
    """Computed properties and resolved fields."""

    def test_scheduler_should_run_true_when_enabled(self) -> None:
        s = Settings()
        assert s.scheduler_should_run is True  # scheduler_enabled defaults to True

    def test_scheduler_should_run_false_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULER_ENABLED", "false")
        s = Settings()
        assert s.scheduler_should_run is False

    def test_scheduler_should_run_true_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCHEDULER_ENABLED", "false")
        monkeypatch.setenv("APPLICANT_MODE", "production")
        s = Settings()
        # production mode overrides scheduler_enabled
        assert s.scheduler_should_run is True

    def test_stealth_persona_resolved_default_linux(self) -> None:
        s = Settings()
        assert s.stealth_persona_resolved == STEALTH_PERSONA_LINUX

    def test_stealth_persona_resolved_native_for_proxmox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", "proxmox-windows")
        s = Settings()
        assert s.stealth_persona_resolved == STEALTH_PERSONA_NATIVE

    def test_stealth_persona_resolved_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STEALTH_PERSONA", "linux")
        monkeypatch.setenv("SANDBOX_BACKEND", "proxmox-windows")
        s = Settings()
        # explicit value wins even when backend suggests native
        assert s.stealth_persona_resolved == STEALTH_PERSONA_LINUX

    def test_llm_configured_false_by_default(self) -> None:
        s = Settings()
        assert s.llm_configured is False

    def test_llm_configured_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        s = Settings()
        assert s.llm_configured is True

    def test_llm_configured_false_partial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        # no LLM_MODEL set
        s = Settings()
        assert s.llm_configured is False

    def test_deployment_profile_hermetic(self) -> None:
        s = Settings()
        assert s.deployment_profile == ""

    def test_is_proxmox_windows_backend_false(self) -> None:
        s = Settings()
        assert s.is_proxmox_windows_backend is False

    def test_is_proxmox_windows_backend_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_BACKEND", "proxmox-windows")
        s = Settings()
        assert s.is_proxmox_windows_backend is True


# ===================================================================
# Takeover desktop resolution table
# ===================================================================

@pytest.mark.unit
class TestTakeoverDesktopResolution:
    """TAKEOVER_DESKTOP_IMAGES dict and resolve_takeover_image function."""

    def test_table_contains_all_desktops(self) -> None:
        for de in TAKEOVER_DESKTOPS:
            assert de in TAKEOVER_DESKTOP_IMAGES, f"Missing image entry for {de}"

    def test_cinnamon_image(self) -> None:
        assert TAKEOVER_DESKTOP_IMAGES[TAKEOVER_DESKTOP_CINNAMON] == "applicant/webtop-chrome:cinnamon"

    def test_xfce_image(self) -> None:
        assert TAKEOVER_DESKTOP_IMAGES[TAKEOVER_DESKTOP_XFCE] == "applicant/webtop-chrome:xfce"

    def test_gnome_image(self) -> None:
        assert TAKEOVER_DESKTOP_IMAGES[TAKEOVER_DESKTOP_GNOME] == "applicant/webtop-gnome:latest"

    def test_pantheon_image(self) -> None:
        assert TAKEOVER_DESKTOP_IMAGES[TAKEOVER_DESKTOP_PANTHEON] == "applicant/webtop-pantheon:latest"

    def test_resolve_takeover_image_lookup(self) -> None:
        assert resolve_takeover_image(TAKEOVER_DESKTOP_CINNAMON) == "applicant/webtop-chrome:cinnamon"

    def test_resolve_takeover_image_override(self) -> None:
        assert (
            resolve_takeover_image(TAKEOVER_DESKTOP_CINNAMON, override="my/image:tag")
            == "my/image:tag"
        )

    def test_resolve_takeover_image_override_whitespace(self) -> None:
        assert (
            resolve_takeover_image(TAKEOVER_DESKTOP_GNOME, override="  custom/image:tag  ")
            == "custom/image:tag"
        )

    def test_resolve_takeover_image_override_empty(self) -> None:
        """Empty override falls through to table lookup."""
        assert (
            resolve_takeover_image(TAKEOVER_DESKTOP_XFCE, override="")
            == "applicant/webtop-chrome:xfce"
        )

    def test_resolve_takeover_image_unknown_desktop(self) -> None:
        with pytest.raises(ValueError, match="Unknown takeover desktop"):
            resolve_takeover_image("nonexistent")

    def test_takeover_desktop_image_resolved_property(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAKEOVER_DESKTOP", "gnome")
        s = Settings()
        assert s.takeover_desktop_image_resolved == "applicant/webtop-gnome:latest"

    def test_takeover_desktop_image_resolved_with_image_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAKEOVER_DESKTOP", "cinnamon")
        monkeypatch.setenv("TAKEOVER_DESKTOP_IMAGE", "my/override:latest")
        s = Settings()
        assert s.takeover_desktop_image_resolved == "my/override:latest"


# ===================================================================
# lru_cache behaviour on get_settings
# ===================================================================

@pytest.mark.unit
class TestGetSettingsCache:
    """get_settings is @lru_cache'd; repeated calls return the same instance."""

    def test_get_settings_returns_settings_instance(self) -> None:
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_cached(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_settings_cache_clear(self) -> None:
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        assert s1 is not s2

    def test_cache_info(self) -> None:
        get_settings()
        info = get_settings.cache_info()
        assert info.hits == 0  # first call is a miss
        get_settings()
        info2 = get_settings.cache_info()
        assert info2.hits >= 1


# ===================================================================
# Edge cases & boundary values
# ===================================================================

@pytest.mark.unit
class TestEdgeCases:
    """Boundary value checks on numeric fields with ge/le constraints."""

    def test_context_compress_threshold_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXT_COMPRESS_THRESHOLD", "0")
        s = Settings()
        assert s.context_compress_threshold == 0

    def test_context_compress_threshold_large(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTEXT_COMPRESS_THRESHOLD", "999999")
        s = Settings()
        assert s.context_compress_threshold == 999999

    def test_pii_retention_days_zero(self) -> None:
        s = Settings()
        assert s.pii_retention_days == 0

    def test_pii_retention_days_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PII_RETENTION_DAYS", "90")
        s = Settings()
        assert s.pii_retention_days == 90

    def test_approval_timeout_days_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPROVAL_TIMEOUT_DAYS", "0")
        s = Settings()
        assert s.approval_timeout_days == 0

    def test_approval_wait_seconds_none_by_default(self) -> None:
        s = Settings()
        assert s.approval_wait_seconds is None

    def test_approval_wait_seconds_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APPROVAL_WAIT_SECONDS", "300")
        s = Settings()
        assert s.approval_wait_seconds == 300.0

    def test_ats_match_rate_floor_default(self) -> None:
        s = Settings()
        assert s.ats_match_rate_floor == 0.2

    def test_ats_match_rate_floor_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATS_MATCH_RATE_FLOOR", "0")
        s = Settings()
        assert s.ats_match_rate_floor == 0.0

    def test_ats_match_rate_floor_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATS_MATCH_RATE_FLOOR", "1")
        s = Settings()
        assert s.ats_match_rate_floor == 1.0

    def test_sandbox_concurrency_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SANDBOX_CONCURRENCY", "1")
        s = Settings()
        assert s.sandbox_concurrency == 1

    def test_loop_failure_alert_threshold_default(self) -> None:
        s = Settings()
        assert s.loop_failure_alert_threshold == 3

    def test_loop_failure_alert_threshold_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOOP_FAILURE_ALERT_THRESHOLD", "1")
        s = Settings()
        assert s.loop_failure_alert_threshold == 1

    def test_empty_string_fields_default_to_empty(self) -> None:
        s = Settings()
        assert s.llm_provider == ""
        assert s.llm_base_url == ""
        assert s.llm_api_key == ""
        assert s.llm_model == ""
        assert s.discord_webhook_url == ""
        assert s.apprise_urls == ""
        assert s.ntfy_url == ""
