# Copyright 2025 Kevin Hirsch — MIT License
"""EPIC STEALTH — the Settings > Stealth router surface.

Exercises GET/PUT /api/setup/stealth against a fake container holding a REAL
SetupService (sharing one in-memory config store), plus the pure helpers
(StealthPrefsStore, build_stealth_view, the validators). Hermetic — nothing
touches the network. The router is mounted on a minimal app (it is intentionally
NOT registered in routers/__init__.py — that is the Integrate step), with the real
exception handlers registered so InvalidInput maps to 422 exactly like production.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.deps import get_container
from applicant.app.main import register_exception_handlers
from applicant.app.routers import stealth
from applicant.application.services.setup_service import SetupService


def _settings(**over):
    base = dict(
        egress_mode="direct",
        egress_proxy_url="",
        egress_residential=False,
        browser_engine="camoufox",
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


# --------------------------------------------------------------------------- #
# GET — fresh install shows the recommended preset posture
# --------------------------------------------------------------------------- #


def test_get_fresh_install_shows_preset_defaults(client):
    body = client.get("/api/setup/stealth").json()
    assert body["egress_route"] == "vps"  # recommended default (direct engine mode)
    assert body["egress_mode"] == "direct"
    assert body["camoufox_enabled"] is True  # settings default engine == camoufox
    assert body["webrtc_suppression"] is True
    assert body["residential_enabled"] is True
    assert body["per_source_proxy_policy"] == "selective"
    assert body["request_pacing_ms"] == 1500
    assert body["request_rate_per_min"] == 20
    assert body["block_detect_threshold"] == 2
    assert body["block_detect_statuses"] == "403,429,503"
    assert body["choices"]["egress_route"] == ["home", "vps", "residential"]
    assert body["choices"]["per_source_proxy_policy"] == ["selective", "always", "never"]
    assert body["warnings"] == []


def test_get_infers_residential_route_from_engine_mode(store):
    # An egress mode saved via Settings > Automation (not this panel) is reflected.
    setup = SetupService(config_store=store)
    setup.set_automation_prefs(
        egress_mode="residential-proxy",
        egress_proxy_url="http://user:pass@resi.example:8880",
        egress_residential=True,
    )
    container = SimpleNamespace(setup_service=setup, settings=_settings())
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(stealth.router)
    app.dependency_overrides[get_container] = lambda: container
    body = TestClient(app).get("/api/setup/stealth").json()
    assert body["egress_route"] == "residential"
    assert body["egress_mode"] == "residential-proxy"
    assert body["egress_residential"] is True
    assert body["warnings"] == []


# --------------------------------------------------------------------------- #
# PUT — write-back + round-trip through the real plumbing
# --------------------------------------------------------------------------- #


def test_put_residential_route_derives_engine_mode(client, container):
    resp = client.put(
        "/api/setup/stealth",
        json={
            "egress_route": "residential",
            "egress_proxy_url": "http://user:pass@resi.example:8880",
            "egress_residential": True,
        },
    )
    assert resp.status_code == 204
    # Persisted through SetupService.set_automation_prefs (single source of truth).
    auto = container.setup_service.get_automation_prefs()
    assert auto["egress_mode"] == "residential-proxy"
    assert auto["egress_proxy_url"] == "http://user:pass@resi.example:8880"
    assert auto["egress_residential"] is True
    body = client.get("/api/setup/stealth").json()
    assert body["egress_route"] == "residential"
    assert body["warnings"] == []


def test_put_home_and_vps_both_map_to_direct(client, container):
    assert client.put("/api/setup/stealth", json={"egress_route": "home"}).status_code == 204
    assert container.setup_service.get_automation_prefs()["egress_mode"] == "direct"
    assert client.get("/api/setup/stealth").json()["egress_route"] == "home"
    assert client.put("/api/setup/stealth", json={"egress_route": "vps"}).status_code == 204
    assert container.setup_service.get_automation_prefs()["egress_mode"] == "direct"
    assert client.get("/api/setup/stealth").json()["egress_route"] == "vps"


def test_put_camoufox_toggle_maps_to_browser_engine(client, container):
    assert client.put("/api/setup/stealth", json={"camoufox_enabled": False}).status_code == 204
    assert container.setup_service.get_automation_prefs()["browser_engine"] == "chromium"
    assert client.get("/api/setup/stealth").json()["camoufox_enabled"] is False
    assert client.put("/api/setup/stealth", json={"camoufox_enabled": True}).status_code == 204
    assert container.setup_service.get_automation_prefs()["browser_engine"] == "camoufox"
    assert client.get("/api/setup/stealth").json()["camoufox_enabled"] is True


def test_put_new_stealth_fields_round_trip(client):
    resp = client.put(
        "/api/setup/stealth",
        json={
            "residential_enabled": False,
            "residential_sticky_sessid": "flow-42_A",
            "per_source_proxy_policy": "always",
            "webrtc_suppression": False,
            "request_pacing_ms": 3000,
            "request_rate_per_min": 10,
            "block_detect_threshold": 4,
            "block_detect_statuses": "403, 429, 999x",  # 999x is invalid -> 400 below
        },
    )
    # The invalid status entry rejects the WHOLE partial update (no partial write).
    assert resp.status_code == 400
    # Now save a clean payload and confirm the round-trip.
    resp = client.put(
        "/api/setup/stealth",
        json={
            "residential_enabled": False,
            "residential_sticky_sessid": "flow-42_A",
            "per_source_proxy_policy": "always",
            "webrtc_suppression": False,
            "request_pacing_ms": 3000,
            "request_rate_per_min": 10,
            "block_detect_threshold": 4,
            "block_detect_statuses": "403, 429, 503",
        },
    )
    assert resp.status_code == 204
    body = client.get("/api/setup/stealth").json()
    assert body["residential_enabled"] is False
    assert body["residential_sticky_sessid"] == "flow-42_A"
    assert body["per_source_proxy_policy"] == "always"
    assert body["webrtc_suppression"] is False
    assert body["request_pacing_ms"] == 3000
    assert body["request_rate_per_min"] == 10
    assert body["block_detect_threshold"] == 4
    assert body["block_detect_statuses"] == "403,429,503"  # normalized (spaces stripped)


def test_partial_update_leaves_other_fields_untouched(client):
    client.put("/api/setup/stealth", json={"request_pacing_ms": 2500})
    client.put("/api/setup/stealth", json={"per_source_proxy_policy": "never"})
    body = client.get("/api/setup/stealth").json()
    assert body["request_pacing_ms"] == 2500  # not clobbered by the second save
    assert body["per_source_proxy_policy"] == "never"


# --------------------------------------------------------------------------- #
# Coherence warnings (non-blocking, honest)
# --------------------------------------------------------------------------- #


def test_residential_without_proxy_warns(client):
    client.put("/api/setup/stealth", json={"egress_route": "residential"})
    body = client.get("/api/setup/stealth").json()
    assert body["egress_route"] == "residential"
    assert any("no proxy URL" in w for w in body["warnings"])


def test_residential_proxy_not_attested_warns(client):
    client.put(
        "/api/setup/stealth",
        json={
            "egress_route": "residential",
            "egress_proxy_url": "http://user:pass@resi.example:8880",
            "egress_residential": False,
        },
    )
    body = client.get("/api/setup/stealth").json()
    assert any("not attested" in w for w in body["warnings"])


# --------------------------------------------------------------------------- #
# Validation — invalid input is 400 (my ValueError) / 422 (delegated SSRF)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        {"egress_route": "moon"},
        {"per_source_proxy_policy": "sometimes"},
        {"residential_sticky_sessid": "bad id!"},
        {"request_pacing_ms": -5},
        {"request_pacing_ms": 999999},
        {"request_rate_per_min": -1},
        {"block_detect_threshold": 0},
        {"block_detect_statuses": "403,700"},
        {"block_detect_statuses": "notacode"},
    ],
)
def test_invalid_values_are_400(client, payload):
    assert client.put("/api/setup/stealth", json=payload).status_code == 400


def test_bad_proxy_url_is_rejected(client):
    # Delegated to set_automation_prefs' SSRF guard -> InvalidInput -> 422.
    resp = client.put(
        "/api/setup/stealth",
        json={"egress_route": "residential", "egress_proxy_url": "http://169.254.169.254/"},
    )
    assert resp.status_code == 422


def test_bad_proxy_url_does_not_partial_write(client, container):
    client.put(
        "/api/setup/stealth",
        json={"egress_route": "residential", "egress_proxy_url": "http://169.254.169.254/"},
    )
    # Nothing persisted: egress_mode override was not written (validation raised first).
    assert "egress_mode" not in container.setup_service.get_automation_prefs()


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_stealth_prefs_store_round_trip():
    store = InMemoryAppConfigStore()
    sps = stealth.StealthPrefsStore(store)
    assert sps.get_raw() == {}
    sps.update({"request_pacing_ms": 900, "webrtc_suppression": False, "skip": None})
    got = sps.get_raw()
    assert got == {"request_pacing_ms": 900, "webrtc_suppression": False}
    sps.update({"request_pacing_ms": 1200})  # partial merge
    assert sps.get_raw()["request_pacing_ms"] == 1200
    assert sps.get_raw()["webrtc_suppression"] is False


def test_build_view_prefers_saved_route_over_engine_inference():
    settings = _settings(egress_mode="residential-proxy")
    # Saved route explicitly 'vps' must win over the residential-proxy inference.
    view = stealth.build_stealth_view(settings, {}, {"egress_route": "vps"})
    assert view["egress_route"] == "vps"


def test_engine_mode_from_route_mapping():
    assert stealth._engine_mode_from_route("residential") == "residential-proxy"
    assert stealth._engine_mode_from_route("home") == "direct"
    assert stealth._engine_mode_from_route("vps") == "direct"


def test_validate_statuses_normalizes_and_rejects():
    assert stealth._validate_statuses(" 403 , 429 ,503 ") == "403,429,503"
    assert stealth._validate_statuses("") == ""
    with pytest.raises(ValueError):
        stealth._validate_statuses("403,42")  # 42 < 100
    with pytest.raises(ValueError):
        stealth._validate_statuses("abc")
