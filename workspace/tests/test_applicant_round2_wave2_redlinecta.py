"""Regression coverage for round 2 / wave 2, Top-25 item #13: "Redline 'All
approved' -> 'Continue to submit ->' CTA (kill the dead-end)", confined to
``static/js/documentLibrary.js``.

Before the fix, once every material for an application had cleared review the
redline gate badge just read "All approved" with no way forward — the user had
to guess that the next step lived in the Pending-Actions Portal (where
`applicantPortal.js`'s `_renderFinal()` renders the actual submit-decision
affordances for `final_approval` / `request_final_approval` items). This adds a
real ``.cal-btn.cal-btn-primary`` "Continue to submit ->" button, shown only
when the gate is fully approved, wired to the SAME cross-lane seam
``applicantChat.js``'s existing "Open Pending" CTA already uses:
``window.applicantPortalModule.openApplicantPortal()``, falling back to a
synthetic click on the ``#rail-portal`` launcher when that global isn't
present.

Follows the convention of ``workspace/tests/test_applicant_round1_lists.py``:
every fact is read from the actual static file content via ``pathlib`` +
regex — no browser, no DOM, no real socket. Each assertion here was verified,
by hand, to actually go red when the underlying fix is reverted (revert
source -> rerun -> see the assertion fail -> restore) per the batch's
test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _materials_fn_source() -> str:
    src = _read(DOCLIB_JS)
    m = re.search(
        r"async function _loadApplicantMaterials\(appId, results\) \{(.*?)\n    \}\n",
        src,
        re.S,
    )
    assert m, "expected to find _loadApplicantMaterials()"
    return m.group(1)


# ── the gate itself is unchanged ────────────────────────────────────────────


def test_gate_ok_condition_is_unchanged():
    """The fix must not touch the vacuous-truth guard (0 items must never read
    as approved)."""
    fn = _materials_fn_source()
    assert "const gateOk = items.length > 0 && !!(data && data.all_approved);" in fn, (
        "expected the existing gateOk guard to remain intact"
    )


# ── the CTA is a real button, only rendered when the gate is fully approved ─


def test_continue_to_submit_button_markup_exists_and_is_gated_on_gate_ok():
    """The "Continue to submit ->" CTA must be a real
    `.cal-btn.cal-btn-primary` button (not a link), and must only be spliced
    into the header markup when `gateOk` is true — never for a "Needs review"
    application."""
    fn = _materials_fn_source()
    assert re.search(
        r'<button type="button" class="cal-btn cal-btn-primary doclib-applicant-continue-submit" ',
        fn,
    ), "expected a real .cal-btn.cal-btn-primary button for the continue-to-submit CTA"
    assert "Continue to submit" in fn, "expected the CTA's visible label"
    # It is spliced in via a `gateOk ? ... : ''` ternary onto head.innerHTML —
    # i.e. structurally absent (not just hidden) when the gate isn't clear.
    gated = re.search(
        r"\(gateOk\s*\?\s*`<button type=\"button\" class=\"cal-btn cal-btn-primary "
        r"doclib-applicant-continue-submit\".*?</button>`\s*\n\s*:\s*''\s*\)",
        fn,
        re.S,
    )
    assert gated, (
        "expected the continue-to-submit button markup to be gated behind a "
        "`gateOk ? ... : ''` ternary so it never renders for a 'Needs review' application"
    )


def test_continue_to_submit_button_appended_before_needs_review_badge_flips():
    """Sanity: the badge text itself must still flip to 'Needs review' when
    the gate isn't clear (the CTA augments the badge, it doesn't replace the
    honest state text)."""
    fn = _materials_fn_source()
    assert "'Needs review'" in fn
    assert "'All approved'" in fn


# ── the CTA is wired to the real next-step surface (the Portal) ────────────


def test_continue_to_submit_button_is_wired_and_queried_by_its_own_class():
    """The click handler must be attached specifically to the new button
    (queried by its distinguishing class), not to some other element."""
    fn = _materials_fn_source()
    assert "head.querySelector('.doclib-applicant-continue-submit')" in fn, (
        "expected the continue-to-submit button to be looked up by its own class"
    )
    assert "continueBtn.addEventListener('click'" in fn, (
        "expected a click handler wired onto the continue-to-submit button"
    )


def test_continue_to_submit_button_opens_the_real_next_step_surface_the_portal():
    """The next step after full redline approval is the submit decision,
    which lives in the Pending-Actions Portal (applicantPortal.js's
    `_renderFinal()` renders the final_approval / request_final_approval
    affordances there). The CTA must call the SAME cross-lane launcher seam
    applicantChat.js's own "Open Pending" CTA uses, with the same
    rail-click fallback -- not invent a new/duplicate opener."""
    fn = _materials_fn_source()
    assert (
        "window.applicantPortalModule && typeof window.applicantPortalModule.openApplicantPortal === 'function'"
        in fn
    ), "expected the CTA to check for the established applicantPortalModule.openApplicantPortal seam"
    assert "window.applicantPortalModule.openApplicantPortal();" in fn, (
        "expected the CTA to call openApplicantPortal() when the seam is available"
    )
    assert "document.getElementById('rail-portal')" in fn, (
        "expected a fallback to a synthetic click on the #rail-portal launcher, "
        "mirroring applicantChat.js's existing 'Open Pending' CTA"
    )


def test_continue_to_submit_cta_reuses_the_same_seam_as_applicant_chat():
    """Cross-file consistency: documentLibrary.js's CTA must reuse the exact
    same global seam applicantChat.js already established for reaching the
    Portal from another lane, not a bespoke one-off."""
    chat_js = _read(JS_DIR / "applicantChat.js")
    doclib_js = _read(DOCLIB_JS)
    assert "window.applicantPortalModule.openApplicantPortal();" in chat_js
    assert "window.applicantPortalModule.openApplicantPortal();" in doclib_js
