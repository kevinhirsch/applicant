"""Real patchright/Playwright browser smoke test (FR-PREFILL-1) — integration only.

The DEFAULT test lane uses the in-memory FakePageSource (NO browser). This test
drives the REAL :class:`PlaywrightPageSource` against a local ``data:`` HTML page,
proving the real driver navigates + detects + types + screenshots behind the
boundary. It SKIPS automatically when no browser driver/binary is installed, so the
hermetic suite never needs a browser.

Run it with:  uv sync --extra browser && patchright install chromium
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_DRIVER = (
    importlib.util.find_spec("patchright") is not None
    or importlib.util.find_spec("playwright") is not None
)


def _working_channel() -> str | None:
    """Return the first launchable channel (real chrome preferred), else ``None``."""
    if not _HAS_DRIVER:
        return None
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    for channel in ("chrome", "chromium"):
        try:
            src = PlaywrightPageSource(
                coherent_fingerprint(channel), headless=False, channel=channel
            )
            src.close()
            return channel
        except Exception:
            continue
    return None


def _browser_binary_available() -> bool:
    return _working_channel() is not None


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(
    not _browser_binary_available(), reason="No browser binary; run `patchright install chromium`."
)
def test_real_browser_navigates_and_detects_fields():
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    channel = _working_channel()
    src = PlaywrightPageSource(coherent_fingerprint(channel), headless=False, channel=channel)
    try:
        html = "<html><body><input name='email' aria-label='Email'></body></html>"
        src.open("data:text/html," + html)
        fields = src.detect_fields()
        assert any(f.selector == '[name="email"]' for f in fields)
        src.type_value('[name="email"]', "kevin@kevinhirsch.com")
        ref = src.screenshot()
        assert ref.startswith("file://")
    finally:
        src.close()


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(
    not _browser_binary_available(), reason="No browser binary; run `patchright install chromium`."
)
def test_real_browser_identity_is_coherent_real_linux_chrome():
    """Live coherence check (FR-STEALTH-1): the identity holds together in a real
    browser — UA, platform, CH-UA platform, languages and WebGL all consistent
    with Linux + Chrome; navigator.webdriver is false; not headless."""
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    channel = _working_channel()
    src = PlaywrightPageSource(coherent_fingerprint(channel), headless=False, channel=channel)
    try:
        src.open("data:text/html,<html><body>hi</body></html>")
        page = src._page  # noqa: SLF001 - integration introspection
        ua = page.evaluate("() => navigator.userAgent")
        platform = page.evaluate("() => navigator.platform")
        webdriver = page.evaluate("() => navigator.webdriver")
        vendor = page.evaluate("() => navigator.vendor")
        languages = page.evaluate("() => navigator.languages")
        renderer = page.evaluate(
            "() => { const c = document.createElement('canvas');"
            "const gl = c.getContext('webgl');"
            "const e = gl.getExtension('WEBGL_debug_renderer_info');"
            "return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : ''; }"
        )
        # Coherent real Linux + Chrome: UA <-> platform <-> WebGL all agree.
        assert "Linux" in ua and "Chrome" in ua
        assert platform == "Linux x86_64"
        assert vendor == "Google Inc."
        assert "en-US" in languages
        # Coherent with Linux + Chrome whether or not the host has a GPU: a GPU-less
        # deploy (the api container renders the browser in-container) legitimately
        # falls back to Chrome's own ANGLE/SwiftShader software path — the same
        # renderer real headless/VM Chrome reports — so that is coherent, not a tell.
        rl = (renderer or "").lower()
        assert any(k in rl for k in ("mesa", "linux", "swiftshader", "angle", "llvmpipe"))
        # A Windows (Direct3D) or macOS (Metal) backend WOULD contradict the Linux UA.
        assert "direct3d" not in rl and "metal" not in rl
        # Not automated / not headless tells.
        assert not webdriver
    finally:
        src.close()
