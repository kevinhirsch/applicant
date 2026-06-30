"""Real patchright/Playwright browser smoke test (FR-PREFILL-1) — integration only.

The DEFAULT test lane uses the in-memory FakePageSource (NO browser). These tests
drive the REAL :class:`PlaywrightPageSource` against a locally-injected HTML fixture,
proving the real driver detects + types + screenshots behind the boundary. They SKIP
automatically when no browser driver/binary is installed, so the hermetic suite never
needs a browser.

Fixtures are loaded with Playwright ``set_content`` (see :func:`_load_fixture`), NOT a
``data:text/html`` navigation: the production navigation sink ``open()`` runs the SSRF
guard (``assert_navigable_url``), which by design refuses every non-http(s) scheme —
``data:``/``file:``/``javascript:`` — so a ``data:`` fixture is rejected (locked in by
``tests/unit/test_ssrf_navigation_guard.py``). These tests exercise the driver's DOM
mechanics, not URL navigation, so they inject the markup directly and keep the guard
intact rather than carving a ``data:`` hole into a security boundary.

Run it with:  uv sync --extra browser && patchright install chromium
"""

from __future__ import annotations

import importlib.util

import pytest


def _load_fixture(src, html: str) -> None:
    """Inject fixture ``html`` into the REAL browser without a URL navigation.

    Uses Playwright ``set_content`` (which parses + runs inline scripts) instead of
    ``src.open("data:text/html,...")`` so the fixtures never touch the SSRF guard or
    any host — hermetic, no network — while still driving the real engine. Runs the
    same ``_settle()`` hydration wait ``open()`` performs so the DOM is ready to scan.
    """
    src._page.set_content(html)  # noqa: SLF001 - integration introspection
    src._settle()  # noqa: SLF001 - integration introspection


_HAS_DRIVER = (
    importlib.util.find_spec("patchright") is not None
    or importlib.util.find_spec("playwright") is not None
)

_HAS_CAMOUFOX = importlib.util.find_spec("camoufox") is not None


def _camoufox_launchable() -> bool:
    """True when Camoufox is installed AND its browser binary has been fetched."""
    if not _HAS_CAMOUFOX:
        return False
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT

    try:
        src = PlaywrightPageSource(dict(NORMALIZED_FINGERPRINT), engine="camoufox")
        src.close()
        return True
    except Exception:
        return False


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
        _load_fixture(src, html)
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
def test_real_browser_enter_application_clicks_into_the_flow():
    """FR-PREFILL-1: a Workday-shaped posting renders an "Apply" button with the form
    behind it. ``enter_application()`` must click that entry so the real form becomes
    inspectable — without it the engine only ever sees the posting page (no fields),
    which is exactly what a live NVIDIA Workday run exhibited (blank page, 0 fields)."""
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    channel = _working_channel()
    # Posting page: an Apply button (Workday `adventureButton`) injects the
    # create-account form on click — so the form is NOT in the DOM until we apply.
    html = (
        "<html><body><h1>Senior Engineer at Acme</h1>"
        "<button data-automation-id='adventureButton' id='applyBtn'>Apply</button>"
        "<div id='signin'></div>"
        "<script>document.getElementById('applyBtn').addEventListener('click',function(){"
        "document.getElementById('signin').innerHTML="
        "'<h2>Create Account</h2>'"
        "+'<input name=\"email\" aria-label=\"Email Address\" type=\"text\">'"
        "+'<input name=\"password\" aria-label=\"Password\" type=\"password\">';});"
        "</script></body></html>"
    )
    src = PlaywrightPageSource(coherent_fingerprint(channel), headless=False, channel=channel)
    try:
        _load_fixture(src, html)
        # Before applying: the posting page exposes no fillable fields.
        assert src.detect_fields() == []
        assert src.is_account_create_page() is False
        # Click "Apply" -> the create-account form is revealed.
        src.enter_application()
        fields = src.detect_fields()
        assert any(f.selector == '[name="email"]' for f in fields)
        assert any(f.selector == '[name="password"]' for f in fields)
        # And the revealed page is now recognized as the account-create gate.
        assert src.is_account_create_page() is True
    finally:
        src.close()


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(
    not _browser_binary_available(), reason="No browser binary; run `patchright install chromium`."
)
def test_real_browser_recognizes_sign_in_gate():
    """FR-PREFILL-4: a Workday "Create Account / Sign In" step shows auth *buttons*
    ("Sign in with email" / "Sign in with Google") before any form field. The loop
    must recognize this as the account gate (so it hands off / logs in) rather than
    mistaking a field-less page for 'done' — exactly the live NVIDIA failure where the
    engine sailed past the Sign In page to AWAITING_FINAL_APPROVAL. "Sign in with
    Google" is an OAuth flow the engine cannot drive, so it still counts as a gate."""
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    channel = _working_channel()
    signin = (
        "<html><body><h2>Sign In</h2>"
        "<button>Sign in with Google</button>"
        "<button>Sign in with email</button></body></html>"
    )
    form = (
        "<html><body><h2>My Information</h2>"
        "<input name='firstName' aria-label='First Name'></body></html>"
    )
    src = PlaywrightPageSource(coherent_fingerprint(channel), headless=False, channel=channel)
    try:
        _load_fixture(src, signin)
        # The Sign In gate has no inputs yet but MUST be recognized as the account gate.
        assert src.detect_fields() == []
        assert src.is_account_gate() is True
        assert src.is_account_create_page() is False  # it's sign-in, not create
        # A real form page (fields present) is NOT an account gate.
        _load_fixture(src, form)
        assert src.is_account_gate() is False
    finally:
        src.close()


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(
    not _browser_binary_available(), reason="No browser binary; run `patchright install chromium`."
)
def test_real_browser_detects_and_fills_workday_listbox_dropdown():
    """FR-PREFILL-2/3: Workday renders Country / Phone-type / EEO fields as custom
    ``<button aria-haspopup="listbox">`` widgets (NOT ``<select>``). The engine must
    DETECT them (the input/select/textarea query misses them) and FILL them by opening
    the dropdown and clicking the matching option — typing does nothing. A live
    Workday run otherwise leaves every such field blank."""
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    channel = _working_channel()
    # A faithful Workday dropdown: a button with real data-automation-id +
    # aria-haspopup="listbox" that opens a role=listbox of role=option items.
    html = (
        "<html><body><h2>Voluntary Disclosures</h2>"
        "<button data-automation-id='gender' aria-haspopup='listbox' aria-label='gender' "
        "id='g'>Select One</button>"
        "<ul role='listbox' id='lb' style='display:none'>"
        "<li role='option' data-automation-label='Male'>Male</li>"
        "<li role='option' data-automation-label='Prefer not to say'>Prefer not to say</li>"
        "</ul>"
        "<script>var b=document.getElementById('g'),l=document.getElementById('lb');"
        "b.addEventListener('click',function(){l.style.display='block';});"
        "l.querySelectorAll('li').forEach(function(o){o.addEventListener('click',"
        "function(){b.textContent=o.getAttribute('data-automation-label');"
        "l.style.display='none';});});</script></body></html>"
    )
    src = PlaywrightPageSource(coherent_fingerprint(channel), headless=False, channel=channel)
    try:
        _load_fixture(src, html)
        # 1. The <button> dropdown is detected as a 'listbox' field (NOT missed).
        fields = src.detect_fields()
        gender = [f for f in fields if f.label == "gender" and f.field_type == "listbox"]
        assert gender, f"listbox not detected: {[(f.selector, f.field_type) for f in fields]}"
        # 2. Filling it opens the dropdown and picks the matching option (typing a
        #    custom dropdown does nothing — it must be opened + clicked).
        src.type_value(gender[0].selector, "Prefer not to say")
        assert src._page.inner_text(gender[0].selector) == "Prefer not to say"  # noqa: SLF001
    finally:
        src.close()


@pytest.mark.integration
@pytest.mark.skipif(
    not _camoufox_launchable(),
    reason="Camoufox not installed/fetched; run `uv sync --extra browser && camoufox fetch`.",
)
def test_camoufox_engine_navigates_and_detects_fields():
    """FR-PREFILL-1/FR-STEALTH-1: the DEFAULT Camoufox engine drives the SAME page
    logic as the chromium path — navigate + detect + type + screenshot — proving the
    engine swap reuses the existing Playwright-API machinery unchanged."""
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT

    src = PlaywrightPageSource(dict(NORMALIZED_FINGERPRINT), engine="camoufox")
    try:
        html = "<html><body><input name='email' aria-label='Email'></body></html>"
        _load_fixture(src, html)
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
        _load_fixture(src, "<html><body>hi</body></html>")
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
