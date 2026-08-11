# Copyright 2025 Kevin Hirsch — MIT License
"""EPIC STEALTH — persisted Settings-UI prefs GOVERN runtime (resolver unit lane).

These are the FAILING-FIRST tests for the pure resolver that folds the persisted
Settings > Stealth prefs (``automation.prefs`` + ``stealth.prefs``) over the
env-sourced ``Settings`` into the effective runtime posture (``EgressPolicy`` inputs
+ ``StealthConfig``), plus the three orphaned knobs the resolver newly threads:

* ``block_detect_statuses`` -> an instance field on ``StealthConfig`` that
  ``is_block_error`` consults (was a module-level hardcoded frozenset);
* ``residential_sticky_sessid`` -> an operator seed that pins ``new_sessid``;
* ``webrtc_suppression`` -> a ``suppress_webrtc`` flag on ``EgressPolicy``.

Pure + hermetic: the resolver reads a duck-typed settings object (a
``SimpleNamespace``) + two plain dicts and touches NO network and NO app/adapter
state. Precedence MIRRORS ``routers/stealth.py`` ``build_stealth_view`` — a persisted
override wins; the existing engine fields fall back to env (``Settings``), the
stealth-only fields fall back to the panel presets.

SAFETY: the resolver only SELECTS app-level egress/proxy/residential posture. It
never touches host routing (the wg0/VPS backstop lives OUTSIDE this app).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from applicant.adapters.browser.stealth import EgressPolicy
from applicant.core.stealth_policy import (
    BLOCK_STATUS_CODES,
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_RESIDENTIAL,
    PROXY_POLICY_VPS,
    StealthConfig,
    StealthPosture,
    is_block_error,
    new_sessid,
    parse_block_statuses,
    resolve_stealth_posture,
)


def _settings(**over):
    """A duck-typed ``Settings`` carrying the env DEFAULTS the resolver reads."""
    base = dict(
        egress_mode="direct",
        egress_proxy_url="",
        egress_residential=False,
        browser_engine="camoufox",
        residential_proxy_url="http://10.8.0.1:8880",
        residential_proxy_enabled=True,
        vps_proxy_url="",
        block_prone_proxy_policy=PROXY_POLICY_RESIDENTIAL,
        default_proxy_policy=PROXY_POLICY_DIRECT,
        discovery_source_proxy_policy="",
        discovery_proxies="",
        residential_sticky_sessions=True,
        residential_sessid_label="sessid-{sessid}",
        discovery_rate_max_calls=5,
        discovery_rate_period_seconds=60.0,
        discovery_min_request_interval_seconds=2.0,
        discovery_backoff_base_seconds=2.0,
        discovery_backoff_multiplier=2.0,
        discovery_backoff_max_seconds=60.0,
        discovery_block_max_retries=1,
        browser_suppress_webrtc=True,
        browser_suppress_dns_leak=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_resolver_returns_posture_with_a_stealthconfig():
    posture = resolve_stealth_posture(_settings(), {}, {})
    assert isinstance(posture, StealthPosture)
    assert isinstance(posture.stealth_config, StealthConfig)


# --------------------------------------------------------------------------- #
# Fresh install: nothing persisted -> env engine fields + panel-preset stealth
# --------------------------------------------------------------------------- #


def test_fresh_install_uses_env_engine_fields_and_panel_presets():
    posture = resolve_stealth_posture(_settings(), {}, {})
    # existing engine fields fall back to env (Settings).
    assert posture.egress_mode == "direct"
    assert posture.egress_proxy_url == ""
    assert posture.egress_residential is False
    assert posture.browser_engine == "camoufox"
    assert posture.suppress_dns_leak is True
    # stealth-only fields fall back to the panel PRESETS (same precedence as
    # build_stealth_view), so what the panel shows is what runtime uses.
    assert posture.suppress_webrtc is True
    assert posture.sticky_sessid == ""
    cfg = posture.stealth_config
    # per_source preset "selective" -> block-prone baseline is the free VPS exit,
    # residential reserved for block-detect escalation (residential still enabled).
    assert cfg.block_prone_policy == PROXY_POLICY_VPS
    assert cfg.default_policy == PROXY_POLICY_DIRECT
    assert cfg.residential_proxy_enabled is True
    # panel-preset pacing: 1500ms -> 1.5s, 20/min, threshold 2, statuses 403/429/503.
    assert cfg.min_request_interval_seconds == pytest.approx(1.5)
    assert cfg.rate_max_calls == 20
    assert cfg.rate_period_seconds == pytest.approx(60.0)
    assert cfg.block_max_retries == 2
    assert cfg.block_status_codes == frozenset({403, 429, 503})


# --------------------------------------------------------------------------- #
# Precedence: persisted overrides env / preset
# --------------------------------------------------------------------------- #


def test_persisted_automation_egress_overrides_env():
    settings = _settings(egress_mode="direct", egress_proxy_url="", egress_residential=False)
    auto = {
        "egress_mode": "residential-proxy",
        "egress_proxy_url": "http://user:pass@resi.example:8880",
        "egress_residential": True,
    }
    posture = resolve_stealth_posture(settings, auto, {})
    assert posture.egress_mode == "residential-proxy"
    assert posture.egress_proxy_url == "http://user:pass@resi.example:8880"
    assert posture.egress_residential is True


def test_persisted_browser_engine_overrides_env():
    posture = resolve_stealth_posture(
        _settings(browser_engine="camoufox"), {"browser_engine": "chromium"}, {}
    )
    assert posture.browser_engine == "chromium"


def test_persisted_stealth_pacing_overrides_preset():
    prefs = {
        "request_pacing_ms": 3000,
        "request_rate_per_min": 10,
        "block_detect_threshold": 4,
    }
    cfg = resolve_stealth_posture(_settings(), {}, prefs).stealth_config
    assert cfg.min_request_interval_seconds == pytest.approx(3.0)
    assert cfg.rate_max_calls == 10
    assert cfg.rate_period_seconds == pytest.approx(60.0)
    assert cfg.block_max_retries == 4


def test_persisted_webrtc_suppression_overrides_preset():
    assert resolve_stealth_posture(_settings(), {}, {}).suppress_webrtc is True
    posture = resolve_stealth_posture(_settings(), {}, {"webrtc_suppression": False})
    assert posture.suppress_webrtc is False


def test_persisted_sticky_sessid_is_carried():
    posture = resolve_stealth_posture(
        _settings(), {}, {"residential_sticky_sessid": "flow-42_A"}
    )
    assert posture.sticky_sessid == "flow-42_A"


# --------------------------------------------------------------------------- #
# Vocab mapping: per_source_proxy_policy (selective/always/never)
# --------------------------------------------------------------------------- #


def test_per_source_always_maps_block_prone_to_residential():
    cfg = resolve_stealth_posture(
        _settings(), {}, {"per_source_proxy_policy": "always"}
    ).stealth_config
    assert cfg.block_prone_policy == PROXY_POLICY_RESIDENTIAL
    assert cfg.default_policy == PROXY_POLICY_DIRECT
    assert cfg.residential_proxy_enabled is True


def test_per_source_selective_baseline_vps_with_residential_escalation():
    cfg = resolve_stealth_posture(
        _settings(), {}, {"per_source_proxy_policy": "selective"}
    ).stealth_config
    assert cfg.block_prone_policy == PROXY_POLICY_VPS
    assert cfg.residential_proxy_enabled is True
    # residential escalation pool available on block-detect (has a residential URL).
    assert cfg.escalation_pool() != ()


def test_per_source_never_disables_residential():
    cfg = resolve_stealth_posture(
        _settings(), {}, {"per_source_proxy_policy": "never"}
    ).stealth_config
    assert cfg.block_prone_policy == PROXY_POLICY_VPS
    assert cfg.residential_proxy_enabled is False
    assert cfg.escalation_pool() == ()


def test_residential_enabled_master_switch_off_disables_residential():
    cfg = resolve_stealth_posture(
        _settings(),
        {},
        {"residential_enabled": False, "per_source_proxy_policy": "always"},
    ).stealth_config
    assert cfg.residential_proxy_enabled is False
    # a residential decision downgrades to vps when residential use is off.
    assert cfg.policy_for("jobspy:linkedin") == PROXY_POLICY_VPS


# --------------------------------------------------------------------------- #
# Non-panel discovery knobs still come from env
# --------------------------------------------------------------------------- #


def test_extra_residential_proxies_from_discovery_proxies_env():
    cfg = resolve_stealth_posture(
        _settings(discovery_proxies="http://a:1, http://b:2"), {}, {}
    ).stealth_config
    assert cfg.extra_residential_proxies == ("http://a:1", "http://b:2")


def test_sessid_label_and_sticky_from_env():
    cfg = resolve_stealth_posture(
        _settings(residential_sessid_label="sid-{sessid}", residential_sticky_sessions=False),
        {},
        {},
    ).stealth_config
    assert cfg.sessid_label == "sid-{sessid}"
    assert cfg.sticky_sessions is False


# --------------------------------------------------------------------------- #
# Orphaned knob (a): block_detect_statuses -> StealthConfig field + is_block_error
# --------------------------------------------------------------------------- #


def test_stealthconfig_block_status_codes_default_field():
    cfg = StealthConfig()
    assert cfg.block_status_codes == BLOCK_STATUS_CODES
    assert cfg.is_block_error(400) is True
    assert cfg.is_block_error(403) is True
    assert cfg.is_block_error(404) is False


def test_module_is_block_error_consults_custom_status_codes():
    # default (unchanged) behavior.
    assert is_block_error(400) is True
    assert is_block_error(403) is True
    # a custom set narrows/widens what counts as a block.
    assert is_block_error(400, frozenset({403})) is False
    assert is_block_error(403, frozenset({403})) is True


def test_resolver_threads_block_detect_statuses_into_config():
    cfg = resolve_stealth_posture(
        _settings(), {}, {"block_detect_statuses": "403,429"}
    ).stealth_config
    assert cfg.block_status_codes == frozenset({403, 429})
    assert cfg.is_block_error(403) is True
    assert cfg.is_block_error(400) is False  # 400 no longer a block per saved set


def test_parse_block_statuses_helper():
    assert parse_block_statuses("403, 429 ,503") == frozenset({403, 429, 503})
    assert parse_block_statuses("") == BLOCK_STATUS_CODES  # empty -> safe default
    assert parse_block_statuses(None) == BLOCK_STATUS_CODES
    assert parse_block_statuses({403, 429}) == frozenset({403, 429})


# --------------------------------------------------------------------------- #
# Orphaned knob (b): residential_sticky_sessid -> new_sessid seed pins the id
# --------------------------------------------------------------------------- #


def test_new_sessid_seed_pins_the_session():
    assert new_sessid(seed="pinned-1") == "pinned-1"
    # a seed WINS over a flow key so a whole flow shares the one pinned identity.
    assert new_sessid("some-flow", seed="pinned-1") == "pinned-1"


def test_new_sessid_without_seed_is_unchanged():
    # deterministic from a flow key (12 hex chars), random otherwise.
    a = new_sessid("flow-x")
    b = new_sessid("flow-x")
    assert a == b and len(a) == 12
    r = new_sessid()
    assert len(r) == 12 and r != new_sessid()
    # a blank/whitespace seed is ignored (falls through to the flow key / random).
    assert new_sessid("flow-x", seed="") == a
    assert new_sessid("flow-x", seed="   ") == a


# --------------------------------------------------------------------------- #
# Orphaned knob (c): webrtc_suppression -> EgressPolicy.suppress_webrtc
# --------------------------------------------------------------------------- #


def test_egress_policy_carries_suppress_webrtc():
    assert EgressPolicy().suppress_webrtc is True
    p = EgressPolicy.from_settings(
        mode="residential-proxy",
        proxy_url="http://user:pass@resi:8880",
        residential=True,
        suppress_webrtc=False,
    )
    assert p.suppress_webrtc is False
    assert p.mode == "residential-proxy"
    # default from_settings keeps suppression on.
    assert EgressPolicy.from_settings(mode="direct", proxy_url="").suppress_webrtc is True


# --------------------------------------------------------------------------- #
# Statelessness: the resolver is the foundation the adapters' "live provider"
# pattern (JobSpySource._current_stealth / PatchrightBrowser._current_egress)
# depends on — it must carry NO hidden caching between calls, so a provider
# closure that calls it fresh on every fetch/open() genuinely observes the
# latest saved prefs, not a stale first-call snapshot.
# --------------------------------------------------------------------------- #


def test_resolver_is_stateless_across_repeated_calls_with_different_prefs():
    settings = _settings()
    first = resolve_stealth_posture(settings, {}, {"per_source_proxy_policy": "always"})
    second = resolve_stealth_posture(settings, {}, {"per_source_proxy_policy": "never"})
    # The SAME settings object, two DIFFERENT persisted prefs -> two genuinely
    # different resolved configs (no cached/frozen result leaking across calls).
    assert first.stealth_config.block_prone_policy == PROXY_POLICY_RESIDENTIAL
    assert first.stealth_config.residential_proxy_enabled is True
    assert second.stealth_config.block_prone_policy == PROXY_POLICY_VPS
    assert second.stealth_config.residential_proxy_enabled is False
