"""Browser-engine selection + Camoufox launch options (FR-STEALTH-1, FR-PREFILL-1).

The agent drives every outbound automation request through ONE browser engine,
selected by ``BROWSER_ENGINE``. The default is ``camoufox`` (a Firefox-based
anti-detect browser); ``chromium`` is the patchright/Chrome fallback (and the engine
used for the Proxmox Windows CDP backend). These hermetic tests pin the config
contract, the pure Camoufox launch-option builder (no browser), and the adapter
threading — so the selection + the FR-STEALTH-3/4 wiring are verified without a
browser binary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from applicant.adapters.browser.page_source import PlaywrightPageSource
from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT
from applicant.app.config import (
    BROWSER_ENGINE_CAMOUFOX,
    BROWSER_ENGINE_CHROMIUM,
    Settings,
)


@pytest.mark.unit
class TestBrowserEngineConfig:
    def test_default_engine_is_camoufox(self):
        # Every outbound automation request routes through Camoufox by default.
        assert Settings().browser_engine == BROWSER_ENGINE_CAMOUFOX

    def test_chromium_engine_selectable(self):
        assert Settings(BROWSER_ENGINE="chromium").browser_engine == BROWSER_ENGINE_CHROMIUM

    def test_engine_is_normalized(self):
        assert Settings(BROWSER_ENGINE="  CamouFox ").browser_engine == BROWSER_ENGINE_CAMOUFOX

    def test_invalid_engine_rejected(self):
        # A typo must fail at load, not silently route through the wrong browser.
        with pytest.raises(ValidationError):
            Settings(BROWSER_ENGINE="camofox")


@pytest.mark.unit
class TestCamoufoxOptions:
    """The pure Camoufox launch-option builder (no browser constructed)."""

    def test_residential_proxy_threaded(self):
        # FR-STEALTH-4: the residential-egress proxy reaches the real launch.
        opts = PlaywrightPageSource.camoufox_options(
            NORMALIZED_FINGERPRINT, proxy={"server": "http://home:8080"}
        )
        assert opts["proxy"] == {"server": "http://home:8080"}

    def test_proxy_omitted_for_direct_egress(self):
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT, proxy=None)
        assert "proxy" not in opts

    def test_persistent_profile_threaded(self):
        # FR-STEALTH-3: a per-tenant profile dir => a persistent context.
        opts = PlaywrightPageSource.camoufox_options(
            NORMALIZED_FINGERPRINT, user_data_dir="/data/profiles/workday-acme"
        )
        assert opts["persistent_context"] is True
        assert opts["user_data_dir"] == "/data/profiles/workday-acme"

    def test_no_profile_dir_is_non_persistent(self):
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT, user_data_dir="")
        assert opts["persistent_context"] is False
        assert "user_data_dir" not in opts

    def test_headful_request_maps_to_virtual_display(self):
        # Headful (the default) becomes a real rendered browser on a virtual X server
        # inside the display-less container — headful, no headless detection tell.
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT)
        assert opts["headless"] == "virtual"

    def test_explicit_headless_modes_are_honored(self):
        assert PlaywrightPageSource.camoufox_options(
            NORMALIZED_FINGERPRINT, headless=True
        )["headless"] is True
        assert PlaywrightPageSource.camoufox_options(
            NORMALIZED_FINGERPRINT, headless="virtual"
        )["headless"] == "virtual"

    def test_stealth_defaults_present(self):
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT)
        # Coherent OS spoof, IP-coherent geolocation, human cursor, carried locale.
        assert opts["os"] == "linux"
        assert opts["geoip"] is True
        assert opts["humanize"] is True
        assert opts["locale"] == NORMALIZED_FINGERPRINT["locale"]

    def test_os_override_honored(self):
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT, browser_os="windows")
        assert opts["os"] == "windows"

    def test_no_chrome_fingerprint_values_injected(self):
        # Camoufox owns its fingerprint — no Chrome UA / WebGL / Sec-CH-UA leaks in.
        opts = PlaywrightPageSource.camoufox_options(NORMALIZED_FINGERPRINT)
        assert "user_agent" not in opts
        assert "channel" not in opts
        assert not any("webgl" in k or "sec_ch" in k for k in opts)


@pytest.mark.unit
class TestAdapterEngineWiring:
    def test_adapter_defaults_to_camoufox(self):
        assert PatchrightBrowser()._engine == BROWSER_ENGINE_CAMOUFOX

    def test_adapter_engine_is_normalized(self):
        assert PatchrightBrowser(engine="  Chromium ")._engine == BROWSER_ENGINE_CHROMIUM

    def test_page_source_default_engine_is_chromium(self):
        # The page source default stays chromium so direct constructions (the
        # Chrome-coherence integration tests) keep exercising the real-Chrome path;
        # the product default (camoufox) is carried by the adapter/config.
        assert PlaywrightPageSource.DEFAULT_ENGINE == BROWSER_ENGINE_CHROMIUM
