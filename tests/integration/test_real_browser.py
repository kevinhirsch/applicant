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


def _browser_binary_available() -> bool:
    if not _HAS_DRIVER:
        return False
    try:
        from applicant.adapters.browser.page_source import PlaywrightPageSource
        from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT

        src = PlaywrightPageSource(NORMALIZED_FINGERPRINT, headless=True)
        src.close()
        return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(
    not _browser_binary_available(), reason="No browser binary; run `patchright install chromium`."
)
def test_real_browser_navigates_and_detects_fields():
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT

    src = PlaywrightPageSource(NORMALIZED_FINGERPRINT, headless=True)
    try:
        html = "<html><body><input name='email' aria-label='Email'></body></html>"
        src.open("data:text/html," + html)
        fields = src.detect_fields()
        assert any(f.selector == "email" for f in fields)
        src.type_value("input[name=email]", "kevin@kevinhirsch.com")
        ref = src.screenshot()
        assert ref.startswith("file://")
    finally:
        src.close()
