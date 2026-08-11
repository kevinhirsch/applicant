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
from applicant.adapters.discovery.factory import build_default_discovery
from applicant.adapters.discovery.jobspy_searxng import JobSpySource, ProxyConfig
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.deps import get_container
from applicant.app.main import create_app, register_exception_handlers
from applicant.app.routers import stealth
from applicant.application.services.setup_service import SetupService
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId, new_id
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
# live re-read lane: PatchrightBrowser's own provider mechanism (mirrors
# _current_egress) — a hand-rolled provider closure, isolated from container.py.
# --------------------------------------------------------------------------- #


def test_patchright_browser_egress_provider_reads_live(client, container):
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


# --------------------------------------------------------------------------- #
# gap #2: browser_engine (camoufox toggle) + suppress_dns_leak were captured
# ONCE at __init__ and never re-read — they now re-resolve per open(), exactly
# like _current_egress/_current_suppress_webrtc.
# --------------------------------------------------------------------------- #


def test_patchright_browser_engine_and_dns_leak_reread_live():
    live = {"engine": "camoufox", "dns_leak": True}
    browser = PatchrightBrowser(
        engine="camoufox",
        suppress_dns_leak=True,
        engine_provider=lambda: live["engine"],
        suppress_dns_leak_provider=lambda: live["dns_leak"],
    )
    assert browser._current_engine() == "camoufox"  # boot value
    assert browser._current_suppress_dns_leak() is True  # boot value

    # A panel/env change AFTER the browser is built...
    live["engine"] = "chromium"
    live["dns_leak"] = False

    # ...governs the SAME (boot singleton) browser with no rebuild.
    assert browser._current_engine() == "chromium"
    assert browser._current_suppress_dns_leak() is False


def test_patchright_browser_engine_provider_failure_degrades_to_boot_value():
    def _boom():
        raise RuntimeError("store unreachable")

    browser = PatchrightBrowser(
        engine="camoufox",
        suppress_dns_leak=True,
        engine_provider=_boom,
        suppress_dns_leak_provider=_boom,
    )
    # A transient store read must never break a flow — degrade to the boot value.
    assert browser._current_engine() == "camoufox"
    assert browser._current_suppress_dns_leak() is True


# --------------------------------------------------------------------------- #
# gap #3 (fixed): the REAL boot-container lane (create_app / build_container) —
# proves container.py's OWN _egress_from_posture/_resolve_posture wiring (not a
# hand-rolled provider closure) governs the singleton browser without a restart.
# A regression in either container.py helper is caught HERE.
# --------------------------------------------------------------------------- #


@pytest.fixture
def real_app():
    return create_app()


@pytest.fixture
def real_client(real_app):
    return TestClient(real_app)


def test_boot_container_browser_egress_is_live_via_real_wiring(real_app, real_client):
    browser = real_app.state.container.browser
    assert browser._current_egress().mode == "direct"  # boot default

    assert real_client.put("/api/setup/stealth", json=_SAVE).status_code == 204

    live = browser._current_egress()
    assert live.mode == "residential-proxy"
    assert live.proxy_url == "http://user:pass@resi.example:8880"
    assert live.suppress_webrtc is False


def test_boot_container_browser_engine_is_live_via_real_wiring(real_app, real_client):
    # Gap #2 through the REAL container: camoufox_enabled=False -> chromium engine.
    browser = real_app.state.container.browser
    assert browser._current_engine() == "camoufox"  # boot default

    assert real_client.put("/api/setup/stealth", json=_SAVE).status_code == 204

    assert browser._current_engine() == "chromium"


def test_boot_container_discovery_proxy_is_live_via_real_wiring(real_app, real_client):
    # Gap #1 through the REAL container: a block-prone jobspy source's egress is
    # frozen at aggregator-build time UNLESS it consults a live stealth provider.
    src = real_app.state.container.discovery._sources["jobspy:linkedin"]
    before = src._current_proxy().as_list()

    assert real_client.put("/api/setup/stealth", json=_SAVE).status_code == 204

    after = src._current_proxy().as_list()
    assert after != before
    assert after is not None
    assert after[0].startswith("http://")


# --------------------------------------------------------------------------- #
# gap #1: JobSpySource must consult a LIVE stealth provider per fetch(), not a
# ProxyConfig frozen at aggregator-build time.
# --------------------------------------------------------------------------- #


def _criteria() -> tuple[CampaignId, SearchCriteria]:
    cid = CampaignId(new_id())
    return cid, SearchCriteria(campaign_id=cid)


def test_saved_per_source_policy_and_sticky_sessid_govern_jobspy_proxy_live(
    client, container
):
    disc = build_default_discovery(
        stealth_provider=lambda: stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).stealth_config,
        sessid_provider=lambda: stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).sticky_sessid,
    )
    src = disc._sources["jobspy:linkedin"]
    # Before save: preset "selective" -> block-prone baseline is vps, no VPS URL
    # configured on this env -> direct (no proxy).
    assert src._current_proxy().as_list() is None

    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204

    # After save: per_source_proxy_policy="always" -> residential up front, using
    # the ENV residential_proxy_url decorated with the saved sticky sessid.
    assert src._current_proxy().as_list() == [
        "http://sessid-pinned-flow-7@10.8.0.1:8880"
    ]
    # No aggregator rebuild happened — same object, same registry.
    assert disc._sources["jobspy:linkedin"] is src


def test_saved_block_detect_statuses_govern_jobspy_escalation_live(client, container):
    """A saved ``block_detect_statuses`` that NARROWS the default block set (the
    _SAVE fixture excludes 400) must govern JobSpySource's escalation decision on
    the very next fetch — not just at aggregator-build time."""

    class _AlwaysHttp400:
        def __init__(self) -> None:
            self.calls = 0

        def scrape(self, *, site, search_term, location, results_wanted, proxies, **kw):
            self.calls += 1
            raise RuntimeError("blocked (HTTP 400)")

    fake_client = _AlwaysHttp400()
    src = JobSpySource(
        site="glassdoor",
        client=fake_client,
        proxy=ProxyConfig(),
        escalation_proxy=ProxyConfig(proxies=("http://10.8.0.1:8880",), enabled=True),
        stealth_provider=lambda: stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).stealth_config,
    )
    cid, criteria = _criteria()

    # Before save: 400 is in the default block set -> escalation is ATTEMPTED
    # (1 direct call + up to the panel-preset block_detect_threshold=2 residential
    # retries), even though every attempt fails here.
    src.fetch(cid, criteria)
    assert fake_client.calls == 3

    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    fake_client.calls = 0
    src.fetch(cid, criteria)
    # After save: 400 is no longer a configured block status -> no escalation.
    assert fake_client.calls == 1


class _UnusedClient:
    """A ``JobSpyClient`` stub whose ``scrape`` must never be called by this test."""

    def scrape(self, **kw):
        raise AssertionError("scrape() should not be called by this test")


def test_saved_block_detect_threshold_governs_escalation_retry_count_live(
    client, container
):
    src = JobSpySource(
        site="indeed",
        client=_UnusedClient(),
        proxy=ProxyConfig(),
        stealth_provider=lambda: stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).stealth_config,
    )
    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    _, retries = src._current_escalation()
    assert retries == 4  # _SAVE's block_detect_threshold


def test_saved_request_rate_per_min_governs_rate_limiter_live(client, container):
    disc = build_default_discovery(
        stealth=stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).stealth_config,
        stealth_provider=lambda: stealth.resolve_effective_posture(
            container.settings, container.setup_service
        ).stealth_config,
    )
    limiter = disc._rate_limiter
    assert limiter._current_limits()[0] == 20  # panel preset request_rate_per_min

    assert client.put("/api/setup/stealth", json=_SAVE).status_code == 204
    assert limiter._current_limits()[0] == 12  # _SAVE's request_rate_per_min


def test_stealth_provider_none_stays_byte_identical_legacy_path():
    """No stealth_provider (every existing caller) => JobSpySource resolves the
    same static ProxyConfig every fetch, exactly as before this fix."""
    disc = build_default_discovery(proxies=("http://legacy:8080",))
    src = disc._sources["jobspy:linkedin"]
    assert src._current_proxy().as_list() == ["http://legacy:8080"]
    assert src._current_proxy().as_list() == src._proxy.as_list()
