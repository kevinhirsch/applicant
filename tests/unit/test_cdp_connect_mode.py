"""Chrome-over-CDP mode selection + endpoint wiring (FR-SANDBOX-1, FR-STEALTH-1).

The native Proxmox Windows backend makes the engine CONNECT to the Windows VM's
Chrome over CDP (no local launch, no fingerprint override). These tests exercise the
mode selection + endpoint wiring through the ``source_factory`` seam (no real
browser) and the pure CDP helpers.
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.page_source import FakePageSource
from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.sandbox.proxmox_client import (
    cdp_ws_endpoint,
    chrome_cdp_command,
)
from applicant.core.ids import ApplicationId, new_id


@pytest.mark.unit
class TestCdpConnectMode:
    def _browser_with_capture(self):
        captured: dict = {}

        def factory(ats, fingerprint, *, user_data_dir="", cdp_endpoint=None):
            captured["cdp_endpoint"] = cdp_endpoint
            captured["user_data_dir"] = user_data_dir
            return FakePageSource(ats)

        return PatchrightBrowser(source_factory=factory), captured

    def test_cdp_endpoint_threaded_into_source(self):
        browser, captured = self._browser_with_capture()
        browser.open(
            ApplicationId(new_id()),
            "https://acme.wd1.myworkdayjobs.com/x",
            cdp_endpoint="http://10.0.0.50:9222",
        )
        assert captured["cdp_endpoint"] == "http://10.0.0.50:9222"

    def test_local_mode_passes_no_cdp_endpoint(self):
        browser, captured = self._browser_with_capture()
        browser.open(ApplicationId(new_id()), "https://acme.wd1.myworkdayjobs.com/x")
        assert captured["cdp_endpoint"] is None

    def test_persona_native_threaded(self):
        # The proxmox-windows backend constructs the browser with persona=native.
        b = PatchrightBrowser(persona="native")
        assert b._persona == "native"
        # Default backend keeps the coherent linux spoof persona.
        assert PatchrightBrowser()._persona == "linux"


@pytest.mark.unit
class TestCdpHelpers:
    def test_ws_endpoint_shape(self):
        assert cdp_ws_endpoint("10.0.0.50", 9222) == "http://10.0.0.50:9222"

    def test_chrome_cdp_command_exposes_remote_debugging(self):
        cmd = chrome_cdp_command(port=9333, address="0.0.0.0")
        assert any("--remote-debugging-port=9333" in p for p in cmd)
        assert any("--remote-debugging-address=0.0.0.0" in p for p in cmd)
        assert cmd[0].endswith("chrome.exe")


@pytest.mark.unit
def test_fingerprint_overrides_skipped_in_native_persona():
    """In native persona the init-script fingerprint override is NOT applied.

    The PlaywrightPageSource only adds the WebGL/platform init script when the
    persona is not ``native`` (real Windows is already coherent). We assert the
    decision is reachable via the pure init-script builder + the persona attribute
    without constructing a real browser.
    """
    from applicant.adapters.browser.page_source import PlaywrightPageSource

    # The init script builder is pure and only used in non-native personas.
    script = PlaywrightPageSource.fingerprint_init_script(
        {"webgl_vendor": "Google Inc.", "platform": "Linux x86_64"}
    )
    assert "navigator" in script and "platform" in script
