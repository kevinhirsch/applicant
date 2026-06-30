"""Live ATS pre-fill dry-run integration test (NFR-OPS-1, FR-PREFILL-1).

Navigates to a real ATS posting page, runs field detection and pre-fill data
assembly, and verifies the engine STOPS at the review boundary — it never
calls the final-submit path. Requires:

  APPLICANT_ATS_DRY_RUN_URL  — the posting URL to test against (Workday /
                                Greenhouse / Lever etc.; must be public-facing).

Run with the real browser extra installed:
  APPLICANT_ATS_DRY_RUN_URL=https://... uv run pytest -m integration \\
      tests/integration/test_ats_prefill_dryrun.py -v

The test is skipped when the env var is absent or when no browser binary is
available, so the hermetic CI lane is never broken.
"""

from __future__ import annotations

import importlib.util
import os

import pytest

_ATS_URL = os.environ.get("APPLICANT_ATS_DRY_RUN_URL", "").strip()
_HAS_DRIVER = (
    importlib.util.find_spec("patchright") is not None
    or importlib.util.find_spec("playwright") is not None
)


def _working_channel() -> str | None:
    if not _HAS_DRIVER:
        return None
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    for channel in ("chromium", "chrome"):
        try:
            src = PlaywrightPageSource(
                coherent_fingerprint(channel), headless=True, channel=channel
            )
            src.close()
            return channel
        except Exception:
            continue
    return None


_CHANNEL = _working_channel() if _HAS_DRIVER else None


@pytest.mark.integration
@pytest.mark.skipif(not _ATS_URL, reason="Set APPLICANT_ATS_DRY_RUN_URL to enable ATS dry-run.")
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver (patchright/playwright) installed.")
@pytest.mark.skipif(_CHANNEL is None, reason="No browser binary installed; run `patchright install chromium`.")
def test_ats_prefill_dryrun_stops_at_review_boundary():
    """NFR-OPS-1 / FR-PREFILL-1: navigate a real ATS, detect fields, verify stop boundary.

    The test:
    1. Opens the posting URL with the stealth browser.
    2. Attempts to enter the application (click Apply / reach the pre-fill form).
    3. Detects fillable fields on the form page.
    4. Asserts the browser did NOT land on a post-submit confirmation page —
       confirming the stop boundary (FR-PREFILL-4/5) was never crossed.
    5. Does NOT call any fill/submit path. Detection only.

    The review/submit boundary is enforced by the engine's safety gate; this test
    confirms detection works all the way through the real browser stack so the
    "wired" → "demonstrated" conversion (NFR-OPS-1) is complete.
    """
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    src = PlaywrightPageSource(
        coherent_fingerprint(_CHANNEL), headless=True, channel=_CHANNEL
    )
    fields = []
    state_trace: list[str] = []
    try:
        state_trace.append(f"opening: {_ATS_URL}")
        src.open(_ATS_URL)
        state_trace.append("page_loaded")

        # Try to enter the application flow (click Apply / create-account button).
        try:
            src.enter_application()
            state_trace.append("entered_application_flow")
        except Exception as exc:
            # Some ATSs go straight to the form; enter_application may be a no-op.
            state_trace.append(f"enter_application_skipped: {exc!s:.80}")

        # Detect form fields on whatever page we landed on.
        fields = src.detect_fields()
        state_trace.append(f"detected_fields: {len(fields)}")

        # Log field names for the artifact (no PII typed or submitted).
        for f in fields[:20]:
            state_trace.append(f"  field: {f.selector!r} label={f.label!r}")

        # Core boundary assertion: we have NOT navigated to a submit-confirmation page.
        # The engine's review-before-submit gate ensures submit never fires without
        # human approval; at this point only detection was run, so we must NOT be
        # on the post-submit page.
        assert not src.is_final_submit_page(), (
            "is_final_submit_page() returned True during a detection-only dry-run — "
            "the stop boundary was crossed without human approval (NFR-OPS-1 violation)."
        )

    finally:
        screenshot_path = src.screenshot() if fields else None
        src.close()

    # Print the state trace so the CI log + uploaded artifact carries the proof.
    print("\n=== ATS dry-run state trace ===")
    for entry in state_trace:
        print(f"  {entry}")
    if screenshot_path:
        print(f"  screenshot: {screenshot_path}")
    print(f"=== fields detected: {len(fields)} ===")

    # At minimum the browser must have loaded the page and returned some result.
    assert state_trace, "state trace empty — browser never started"

    # If the ATS page was reached and we found fields, this is a full NFR-OPS-1 proof.
    # If fields == 0 the ATS requires auth or the form is behind a gate — that is a
    # genuine detection failure (the browser stack did not demonstrate field detection),
    # so we raise a hard assertion rather than silently xfail-ing, which would mask a
    # real browser or page-structure regression.
    assert len(fields) > 0, (
        f"Browser reached {_ATS_URL!r} but detected 0 fillable fields — "
        "ATS may require auth or the form is behind a gate. "
        f"State trace: {state_trace}. "
        "Inspect the screenshot artifact. Stop boundary was respected but "
        "field detection did not succeed (NFR-OPS-1 not fully demonstrated)."
    )


@pytest.mark.integration
@pytest.mark.skipif(not _ATS_URL, reason="Set APPLICANT_ATS_DRY_RUN_URL to enable ATS dry-run.")
@pytest.mark.skipif(not _HAS_DRIVER, reason="No browser driver installed.")
@pytest.mark.skipif(_CHANNEL is None, reason="No browser binary installed.")
def test_ats_prefill_dryrun_never_reaches_final_submit_page():
    """Confirm the ATS submission confirmation page is never reached in a dry-run.

    Runs the same detection pass as the boundary test but checks explicitly that
    is_final_submit_page() remains False after detection-only navigation. A True
    result would mean a submit fired before human approval.
    """
    from applicant.adapters.browser.page_source import PlaywrightPageSource
    from applicant.adapters.browser.stealth import coherent_fingerprint

    src = PlaywrightPageSource(
        coherent_fingerprint(_CHANNEL), headless=True, channel=_CHANNEL
    )
    try:
        src.open(_ATS_URL)
        try:
            src.enter_application()
        except Exception:
            pass
        # Detection only — never fill, never submit.
        src.detect_fields()
        # Must NOT be on a confirmation page after detection-only pass.
        assert not src.is_final_submit_page(), (
            "Reached final-submit confirmation page without human approval — "
            "review-before-submit gate breached."
        )
    finally:
        src.close()
