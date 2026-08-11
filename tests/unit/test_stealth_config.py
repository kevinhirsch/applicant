"""Unit tests for the EPIC STEALTH stealth-config fields on ``Settings``.

Every stealth value is a PRESET DEFAULT that is CHANGEABLE via env/Settings.
Default-value assertions pass ``_env_file=None`` so the live deployment's
``.env`` (which sets unrelated discovery fields) can never leak into them.
"""

from __future__ import annotations

import pytest

from applicant.app.config import (
    PROXY_POLICIES,
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_RESIDENTIAL,
    Settings,
    get_settings,
)
from applicant.core.stealth_policy import StealthConfig


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    get_settings.cache_clear()


def _defaults() -> Settings:
    """Settings with the on-disk ``.env`` disabled (hermetic default surface)."""
    return Settings(_env_file=None)


@pytest.mark.unit
class TestStealthDefaults:
    def test_residential_forwarder_is_the_preset_default(self):
        assert _defaults().residential_proxy_url == "http://10.8.0.1:8880"

    def test_residential_enabled_by_default(self):
        assert _defaults().residential_proxy_enabled is True

    def test_vps_proxy_url_empty_by_default(self):
        assert _defaults().vps_proxy_url == ""

    def test_block_prone_defaults_to_residential(self):
        assert _defaults().block_prone_proxy_policy == PROXY_POLICY_RESIDENTIAL

    def test_everything_else_defaults_to_direct(self):
        assert _defaults().default_proxy_policy == PROXY_POLICY_DIRECT

    def test_source_policy_override_empty_by_default(self):
        assert _defaults().discovery_source_proxy_policy == ""

    def test_sticky_sessions_on_by_default(self):
        s = _defaults()
        assert s.residential_sticky_sessions is True
        assert s.residential_sessid_label == "sessid-{sessid}"

    def test_pacing_defaults(self):
        s = _defaults()
        assert s.discovery_rate_max_calls == 5
        assert s.discovery_rate_period_seconds == 60.0
        assert s.discovery_min_request_interval_seconds == 2.0
        assert s.discovery_backoff_base_seconds == 2.0
        assert s.discovery_backoff_multiplier == 2.0
        assert s.discovery_backoff_max_seconds == 60.0
        assert s.discovery_block_max_retries == 1

    def test_browser_leak_suppression_on_by_default(self):
        s = _defaults()
        assert s.browser_suppress_webrtc is True
        assert s.browser_suppress_dns_leak is True


@pytest.mark.unit
class TestStealthOverridable:
    def test_residential_url_overridable(self, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_URL", "http://other:9999")
        assert Settings().residential_proxy_url == "http://other:9999"

    def test_residential_toggle_overridable(self, monkeypatch):
        monkeypatch.setenv("RESIDENTIAL_PROXY_ENABLED", "false")
        assert Settings().residential_proxy_enabled is False

    def test_block_prone_policy_overridable(self, monkeypatch):
        monkeypatch.setenv("BLOCK_PRONE_PROXY_POLICY", "vps")
        assert Settings().block_prone_proxy_policy == "vps"

    def test_source_policy_override_string_overridable(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_SOURCE_PROXY_POLICY", "searxng=residential")
        assert Settings().discovery_source_proxy_policy == "searxng=residential"

    def test_pacing_overridable(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_RATE_MAX_CALLS", "10")
        assert Settings().discovery_rate_max_calls == 10


@pytest.mark.unit
class TestStealthValidators:
    @pytest.mark.parametrize("policy", PROXY_POLICIES)
    def test_valid_policies_accepted(self, policy, monkeypatch):
        monkeypatch.setenv("BLOCK_PRONE_PROXY_POLICY", policy)
        monkeypatch.setenv("DEFAULT_PROXY_POLICY", policy)
        s = Settings()
        assert s.block_prone_proxy_policy == policy
        assert s.default_proxy_policy == policy

    def test_invalid_block_prone_policy_rejected(self, monkeypatch):
        monkeypatch.setenv("BLOCK_PRONE_PROXY_POLICY", "datacenter")
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    def test_invalid_default_policy_rejected(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_PROXY_POLICY", "residentail")  # typo
        with pytest.raises(ValueError, match="is invalid"):
            Settings()

    def test_malformed_source_policy_rejected_at_load(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_SOURCE_PROXY_POLICY", "jobspy:indeed=teleport")
        with pytest.raises(ValueError):
            Settings()

    def test_rate_period_must_be_positive(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_RATE_PERIOD_SECONDS", "0")
        with pytest.raises(ValueError):
            Settings()


@pytest.mark.unit
class TestBuildStealthConfigFromSettings:
    def test_builds_a_stealth_config(self):
        cfg = _defaults().build_stealth_config()
        assert isinstance(cfg, StealthConfig)
        # block-prone -> residential forwarder; keyless ATS -> direct.
        assert cfg.proxy_urls_for("jobspy:linkedin") == ("http://10.8.0.1:8880",)
        assert cfg.proxy_urls_for("greenhouse:acme") == ()

    def test_discovery_proxies_fold_in_as_extra_residential(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_PROXIES", "http://extra:8880")
        cfg = Settings().build_stealth_config()
        pool = cfg.proxy_urls_for("jobspy:indeed")
        assert "http://extra:8880" in pool
        assert "http://10.8.0.1:8880" in pool

    def test_pacing_flows_into_stealth_config(self, monkeypatch):
        monkeypatch.setenv("DISCOVERY_RATE_MAX_CALLS", "7")
        cfg = Settings().build_stealth_config()
        assert cfg.rate_max_calls == 7
