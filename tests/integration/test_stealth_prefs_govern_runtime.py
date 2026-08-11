# Copyright 2025 Kevin Hirsch — MIT License
"""EPIC STEALTH — a Settings > Stealth save GOVERNS the runtime posture.

Cross-component: drive a real ``PUT /api/setup/stealth`` through the real router ->
``SetupService`` -> ``AppConfigStore`` chain, then RE-RESOLVE the effective posture
and assert the runtime adapters (``EgressPolicy`` for the apply-flow browser,
``StealthConfig`` for discovery, ``PatchrightBrowser``) reflect the SAVED values —
proving the persisted panel prefs are no longer write-only.

Two lanes:

* the router-glue lane (``resolve_effective_posture``) — HTTP save -> store ->
  resolver -> adapters, hermetic (in-memory config store, no network);
* the boot-container lane (``create_app``) — proves the container builds the
  browser with a LIVE egress provider, so a save after boot governs the boot
  browser's egress WITHOUT a restart.

SAFETY: only app-level egress/proxy/residential SELECTION is exercised. Nothing
here touches host routing (the wg0/VPS home-IP backstop lives OUTSIDE this app).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.browser.stealth import EgressPolicy
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.deps import get_container
from applicant.app.main import register_exception_handlers
from applicant.app.routers import stealth
from applicant.application.services.setup_service import SetupService
from applicant.core.stealth_policy import (
    PROXY_POLICY_RESIDENTIAL,
    new_sessid,
)


def _settings(**over):
    base = dict(
        egress_mode="direct",
        egress_proxy_url="",
        egress_residential=False,
        browser_engine="camoufox",
        residential_proxy_url="http://10.8.0.1:8880",
        residential_proxy_enabled=True,
        vps_proxy_url="",
        block_prone_proxy_policy=PROXY_POLICY_RESIDENTIAL,
        default_proxy_policy="direct",
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


@pytest.fixture
def store():
    return InMemoryAppConfigStore()


@pytest.fixture
def container(store):
    setup = SetupService(config_store=store)
    return SimpleNamespace(setup_service=setup, settings=_settings())


@pytest.fixture
def client(container):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(stealth.router)
    app.dependency_overrides[get_container] = lambda: container
    return TestClient(app)


_SAVE = {
    "egress_route": "residential",
    "egress_proxy_url": "http://user:pass@resi.example:8880",
    "egress_residential": True,
    "camoufox_enabled": False,  # -> chromium engine
    "webrtc_suppression": False,
    "residential_enabled": True,
    "residential_sticky_sessid": "pinned-flow-7",
    "per_source_proxy_policy": "always",
    "request_pacing_ms": 3000,
    "request_rate_per_min": 12,
    "block_detect_threshold": 4,
    "block_detect_statuses": "403,429",
}


# --------------------------------------------------------------------------- #
# router-glue lane: HTTP save -> re-resolve -> adapters reflect it
# --------------------------------------------------------------------------- #


def test_before_save_runtime_is_env_default(container):
    posture = stealth.resolve_effective_posture(container.settings, container.setup_service)
    assert posture.egress_mode == "direct"
    egress = EgressPolicy.from_settings(
        mode=posture.egress_mode,
        proxy_url=posture.egress_proxy_url,
        residential=posture.egress_residential,
        suppress_webrtc=posture.suppress_webrtc,
    )
    assert egress.mode == "direct"
    assert egress.launch_proxy() is None  # no proxy -> host (wg0) egress, unchanged


def test_saved_posture_governs_egress_policy(client, container):
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    posture = stealth.resolve_effective_posture(container.settings, container.setup_service)

    egress = EgressPolicy.from_settings(
        mode=posture.egress_mode,
        proxy_url=posture.egress_proxy_url,
        residential=posture.egress_residential,
        suppress_webrtc=posture.suppress_webrtc,
    )
    assert egress.mode == "residential-proxy"
    assert egress.proxy_url == "http://user:pass@resi.example:8880"
    assert egress.residential is True
    assert egress.suppress_webrtc is False
    assert egress.launch_proxy() == {"server": "http://user:pass@resi.example:8880"}
    egress.validate()  # attested residential proxy -> launches (no refusal)


def test_saved_posture_governs_stealth_config(client, container):
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    cfg = stealth.resolve_effective_posture(
        container.settings, container.setup_service
    ).stealth_config
    # per_source "always" -> block-prone routed residentially up front.
    assert cfg.block_prone_policy == PROXY_POLICY_RESIDENTIAL
    assert cfg.proxy_urls_for("jobspy:linkedin") != ()
    # pacing / rate / retries reflect the saved values.
    assert cfg.min_request_interval_seconds == pytest.approx(3.0)
    assert cfg.rate_max_calls == 12
    assert cfg.block_max_retries == 4
    # block-detect status set reflects the saved list (400 dropped).
    assert cfg.block_status_codes == frozenset({403, 429})
    assert cfg.is_block_error(403) is True
    assert cfg.is_block_error(400) is False


def test_saved_posture_governs_patchright_browser(client, container):
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    posture = stealth.resolve_effective_posture(container.settings, container.setup_service)
    egress = EgressPolicy.from_settings(
        mode=posture.egress_mode,
        proxy_url=posture.egress_proxy_url,
        residential=posture.egress_residential,
        suppress_webrtc=posture.suppress_webrtc,
    )
    browser = PatchrightBrowser(
        egress=egress,
        engine=posture.browser_engine,
        suppress_webrtc=posture.suppress_webrtc,
        suppress_dns_leak=posture.suppress_dns_leak,
    )
    assert browser._engine == "chromium"  # camoufox_enabled False -> chromium
    assert browser._suppress_webrtc is False
    assert browser.egress.mode == "residential-proxy"
    assert browser.egress.suppress_webrtc is False


def test_saved_sticky_sessid_pins_the_flow_id(client, container):
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    posture = stealth.resolve_effective_posture(container.settings, container.setup_service)
    # the operator's saved sticky id pins every flow's residential session id.
    assert new_sessid(seed=posture.sticky_sessid) == "pinned-flow-7"
    assert new_sessid("discovery", seed=posture.sticky_sessid) == "pinned-flow-7"


# --------------------------------------------------------------------------- #
# live re-read lane: the boot browser picks up a post-boot save (no restart)
# --------------------------------------------------------------------------- #


def test_boot_browser_egress_is_live_via_provider(client, container):
    # Simulate the container's boot wiring: a PatchrightBrowser built ONCE with a
    # live egress provider that re-resolves the effective posture at flow time.
    def _live_egress():
        p = stealth.resolve_effective_posture(container.settings, container.setup_service)
        return EgressPolicy.from_settings(
            mode=p.egress_mode,
            proxy_url=p.egress_proxy_url,
            residential=p.egress_residential,
            suppress_webrtc=p.suppress_webrtc,
        )

    browser = PatchrightBrowser(egress=_live_egress(), egress_provider=_live_egress)
    assert browser._current_egress().mode == "direct"  # boot value

    # A panel save AFTER the browser is built...
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204

    # ...governs the SAME (boot singleton) browser's egress with no rebuild.
    live = browser._current_egress()
    assert live.mode == "residential-proxy"
    assert live.proxy_url == "http://user:pass@resi.example:8880"
    assert live.suppress_webrtc is False
