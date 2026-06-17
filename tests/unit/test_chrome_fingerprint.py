"""Google Chrome driver + coherent real-Linux/Chrome fingerprint (FR-STEALTH-1).

Hermetic: no browser, no network. These pin the OWNER DECISION — present a COHERENT
REAL Linux + Google Chrome identity (not a spoofed Windows persona) and APPLY every
fingerprint field to the launched context. Each test is fail-before/pass-after the
implementation. The real-browser coherence check lives in
``tests/integration/test_real_browser.py`` (skips without a browser).
"""

from __future__ import annotations

import random

import pytest

from applicant.adapters.browser.page_source import PlaywrightPageSource
from applicant.adapters.browser.stealth import (
    NORMALIZED_FINGERPRINT,
    PINNED_CHROME_MAJOR,
    coherent_fingerprint,
    detect_chrome_major,
    fingerprint_is_coherent,
)


@pytest.mark.unit
class TestCoherentLinuxChromeIdentity:
    """The single coherent real-Linux + Google Chrome identity (FR-STEALTH-1)."""

    def test_default_identity_is_real_linux_chrome(self):
        fp = NORMALIZED_FINGERPRINT
        # Real Linux x86_64 Chrome UA — NOT a Windows/macOS string.
        assert "X11; Linux x86_64" in fp["user_agent"]
        assert f"Chrome/{PINNED_CHROME_MAJOR}" in fp["user_agent"]
        assert fp["platform"] == "Linux x86_64"
        assert fp["vendor"] == "Google Inc."
        assert fp["languages"] == "en-US,en"
        assert fp["sec_ch_ua_platform"] == "Linux"
        assert fp["sec_ch_ua_mobile"] == "?0"

    def test_webgl_is_a_real_linux_gpu_not_windows_d3d(self):
        # A plausible real Linux GPU (Mesa) — never a Windows Direct3D/ANGLE D3D11.
        r = NORMALIZED_FINGERPRINT["webgl_renderer"].lower()
        assert "mesa" in r
        assert "direct3d" not in r and "d3d11" not in r
        assert "apple" not in r and "metal" not in r

    def test_sec_ch_ua_major_agrees_with_ua_major(self):
        fp = NORMALIZED_FINGERPRINT
        assert f'"Google Chrome";v="{PINNED_CHROME_MAJOR}"' in fp["sec_ch_ua"]
        assert f'"Chromium";v="{PINNED_CHROME_MAJOR}"' in fp["sec_ch_ua"]

    def test_identity_is_internally_coherent(self):
        assert fingerprint_is_coherent(NORMALIZED_FINGERPRINT) is True

    def test_webgl_is_stable_not_randomized(self):
        # Randomization is itself a tell; two builds yield the SAME renderer.
        a = coherent_fingerprint("chrome")["webgl_renderer"]
        b = coherent_fingerprint("chrome")["webgl_renderer"]
        assert a == b


@pytest.mark.unit
class TestRejectIncoherentCombos:
    """fingerprint_is_coherent must reject the combos a real browser never makes."""

    def test_rejects_windows_on_linux_spoof(self):
        # The sweep-3 audit gap: Linux UA + Win32 platform + D3D WebGL is incoherent.
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["platform"] = "Win32"
        assert fingerprint_is_coherent(bad) is False

    def test_rejects_linux_ua_with_direct3d_renderer(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["webgl_renderer"] = "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11, D3D11)"
        assert fingerprint_is_coherent(bad) is False

    def test_rejects_linux_ua_with_windows_ch_ua_platform(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["sec_ch_ua_platform"] = "Windows"
        assert fingerprint_is_coherent(bad) is False

    def test_rejects_ua_chrome_major_disagreeing_with_ch_ua(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        # UA says one major; CH-UA says another -> client hints contradict the UA.
        bad["sec_ch_ua"] = '"Google Chrome";v="999", "Chromium";v="999"'
        assert fingerprint_is_coherent(bad) is False

    def test_old_windows_persona_is_now_rejected(self):
        # The pre-rewrite Windows fingerprint must NOT validate as coherent here.
        old = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/124.0.0.0",
            "platform": "Win32",
            "sec_ch_ua_platform": "Linux",  # incoherent: Win UA, Linux CH-UA
            "webgl_renderer": "ANGLE (Intel, ... Direct3D11, D3D11)",
            "locale": "en-US",
            "timezone": "America/Phoenix",
            "resolution": "1920x1080",
        }
        assert fingerprint_is_coherent(old) is False


@pytest.mark.unit
class TestChromeMajorFromInstalledChrome:
    """Derive the Chrome major from the installed Chrome so UA <-> engine agree."""

    def test_detect_uses_google_chrome_version_output(self, monkeypatch):
        import applicant.adapters.browser.stealth as st

        monkeypatch.setattr(st.shutil, "which", lambda name: "/usr/bin/google-chrome")

        class _R:
            stdout = "Google Chrome 137.0.7151.68 \n"

        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _R())
        assert detect_chrome_major("chrome") == 137

    def test_detect_returns_none_when_chrome_absent(self, monkeypatch):
        import applicant.adapters.browser.stealth as st

        monkeypatch.setattr(st.shutil, "which", lambda name: None)
        assert detect_chrome_major("chrome") is None

    def test_coherent_fingerprint_pins_to_detected_major(self, monkeypatch):
        import applicant.adapters.browser.stealth as st

        monkeypatch.setattr(st, "detect_chrome_major", lambda channel="chrome": 137)
        fp = coherent_fingerprint("chrome")
        assert "Chrome/137" in fp["user_agent"]
        assert '"Google Chrome";v="137"' in fp["sec_ch_ua"]
        assert fingerprint_is_coherent(fp) is True

    def test_coherent_fingerprint_falls_back_to_pinned_major(self, monkeypatch):
        import applicant.adapters.browser.stealth as st

        monkeypatch.setattr(st, "detect_chrome_major", lambda channel="chrome": None)
        fp = coherent_fingerprint("chrome")
        assert f"Chrome/{PINNED_CHROME_MAJOR}" in fp["user_agent"]


@pytest.mark.unit
class TestEveryFieldAppliedToLaunch:
    """The sweep-3 gap: fields were computed but not applied. Assert they ARE."""

    def test_launch_kwargs_carries_chrome_channel_and_is_headful(self):
        kwargs = PlaywrightPageSource.launch_kwargs(NORMALIZED_FINGERPRINT, channel="chrome")
        assert kwargs["channel"] == "chrome"  # real Google Chrome drives
        assert kwargs["headless"] is False  # headful (no --headless tell)

    def test_launch_kwargs_threads_ua_locale_tz_viewport_scale(self):
        kwargs = PlaywrightPageSource.launch_kwargs(NORMALIZED_FINGERPRINT)
        assert kwargs["user_agent"] == NORMALIZED_FINGERPRINT["user_agent"]
        assert kwargs["locale"] == "en-US"
        assert kwargs["timezone_id"] == "America/Phoenix"
        assert kwargs["viewport"] == {"width": 1920, "height": 1080}
        assert kwargs["device_scale_factor"] == 1.0

    def test_launch_kwargs_disables_automation_controlled(self):
        kwargs = PlaywrightPageSource.launch_kwargs(NORMALIZED_FINGERPRINT)
        assert "--disable-blink-features=AutomationControlled" in kwargs["args"]
        # No automation-revealing flags.
        assert not any("headless" in a.lower() for a in kwargs["args"])
        assert not any("enable-automation" in a.lower() for a in kwargs["args"])

    def test_init_script_applies_platform_vendor_languages_webgl(self):
        script = PlaywrightPageSource.fingerprint_init_script(NORMALIZED_FINGERPRINT)
        assert "Linux x86_64" in script  # navigator.platform
        assert "Google Inc." in script  # navigator.vendor + webgl vendor
        assert "en-US" in script and "en" in script  # navigator.languages
        assert NORMALIZED_FINGERPRINT["webgl_renderer"] in script
        assert "37445" in script and "37446" in script  # UNMASKED vendor/renderer

    def test_init_script_does_not_override_sec_ch_ua(self):
        # Real Chrome emits CH-UA itself; the init script must NOT re-set it.
        script = PlaywrightPageSource.fingerprint_init_script(NORMALIZED_FINGERPRINT)
        assert "Sec-CH-UA" not in script
        assert "userAgentData" not in script


@pytest.mark.unit
class TestEgressTzLocaleAndChannelThreaded:
    """tz/locale pinned to egress + channel reach the page source (FR-STEALTH-1/4)."""

    def test_adapter_pins_tz_locale_into_fingerprint(self):
        from applicant.adapters.browser.patchright_browser import PatchrightBrowser

        b = PatchrightBrowser(egress_timezone="Europe/London", egress_locale="en-GB")
        assert b.fingerprint["timezone"] == "Europe/London"
        assert b.fingerprint["locale"] == "en-GB"

    def test_adapter_threads_channel_and_tz_into_source(self):
        from applicant.adapters.browser import patchright_browser as pb
        from applicant.core.ids import ApplicationId, new_id

        captured: dict = {}

        class _FakeSource:
            def __init__(self, fingerprint, *, proxy=None, user_data_dir="", channel="chrome"):
                captured["channel"] = channel
                captured["fingerprint"] = fingerprint

            def open(self, url):
                pass

            def current(self):
                from applicant.ports.driven.browser_automation import PageState

                return PageState(url="https://acme.wd1.myworkdayjobs.com/x", fields=())

        def factory(ats, fingerprint, *, user_data_dir=""):
            return _FakeSource(fingerprint, user_data_dir=user_data_dir, channel="chromium")

        # Use the source_factory seam to confirm the channel flows through cleanly.
        b = pb.PatchrightBrowser(
            channel="chromium",
            egress_timezone="America/New_York",
            source_factory=lambda ats, fp, *, user_data_dir="": _FakeSource(
                fp, user_data_dir=user_data_dir, channel=b._channel
            ),
        )
        b.open(ApplicationId(new_id()), "https://acme.wd1.myworkdayjobs.com/x")
        assert captured["channel"] == "chromium"
        assert captured["fingerprint"]["timezone"] == "America/New_York"

    def test_default_channel_is_chrome(self):
        from applicant.adapters.browser.patchright_browser import PatchrightBrowser

        assert PatchrightBrowser()._channel == "chrome"


@pytest.mark.unit
class TestBrowserChannelConfig:
    """BROWSER_CHANNEL config: default chrome + validation (FR-STEALTH-1)."""

    def test_default_channel_is_chrome(self):
        from applicant.app.config import Settings

        assert Settings(_env_file=None).browser_channel == "chrome"

    def test_chromium_fallback_is_accepted(self):
        from applicant.app.config import Settings

        assert Settings(_env_file=None, BROWSER_CHANNEL="chromium").browser_channel == "chromium"

    def test_invalid_channel_is_rejected(self):
        from pydantic import ValidationError

        from applicant.app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, BROWSER_CHANNEL="firefox")

    def test_egress_tz_locale_defaults_are_coherent_pair(self):
        from applicant.app.config import Settings

        s = Settings(_env_file=None)
        assert s.egress_timezone == "America/Phoenix"
        assert s.egress_locale == "en-US"


@pytest.mark.unit
class TestPerTenantProfileWithChrome:
    """FR-STEALTH-3: the chrome channel uses the per-tenant user_data_dir."""

    def test_user_data_dir_threaded_with_chrome_channel(self):
        from applicant.adapters.browser import patchright_browser as pb
        from applicant.core.ids import ApplicationId, new_id

        captured: dict = {}

        class _FakeSource:
            def __init__(self, fingerprint, *, proxy=None, user_data_dir="", channel="chrome"):
                captured["user_data_dir"] = user_data_dir
                captured["channel"] = channel

            def open(self, url):
                pass

            def current(self):
                from applicant.ports.driven.browser_automation import PageState

                return PageState(url="https://acme.wd1.myworkdayjobs.com/x", fields=())

        def factory(ats, fp, *, user_data_dir=""):
            return _FakeSource(fp, user_data_dir=user_data_dir, channel="chrome")

        b = pb.PatchrightBrowser(source_factory=factory, rng=random.Random(0))
        app_id = ApplicationId(new_id())
        b.open(app_id, "https://acme.wd1.myworkdayjobs.com/x")
        # A per-tenant persistent profile dir (FR-STEALTH-3) reached the source.
        assert "acme" in captured["user_data_dir"]
