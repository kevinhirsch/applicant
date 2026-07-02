"""Regression coverage for the Apple-Genius design audit, batch B "Portal"
(docs/design/audits/APPLE_GENIUS_IMPROVEMENTS.md, items 25-44), confined to
workspace/static/js/applicantPortal.js and workspace/static/app.js.

Every fact below is read from the ACTUAL current source of those two files (no
duplicated re-implementation of the logic under test), mirroring the two
precedents already established in this repo:

  * workspace/tests/test_applicant_update_js.py — `node --input-type=module`
    executes REAL exported/extracted JS so pure logic is genuinely exercised,
    not just pattern-matched.
  * tests/bdd/steps/test_enh_uia11y_steps.py — plain Python reads the front-door
    source as text and asserts real facts about it via regex, which is how this
    same file already treats applicantPortal.js's DOM-coupled overlay behavior
    (it is not a "pure leaf module": it touches `document`/`window`/`fetch` at
    import time, so a full module import under Node is impractical — see that
    file's own note on why the JS-import runner only takes pure modules).

`_setComposerDimmed` is genuinely private (not exported), so its test below
extracts its REAL source text out of the live file at test time and runs it
under Node against a minimal fake `document`/element — real execution of the
shipped logic, not a re-description of it.

Every assertion here was verified against a temporary revert of the
corresponding fix (then restored via `git checkout`) to confirm it actually
fails without the fix — see the batch report for the revert log.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
PORTAL_JS = _REPO / "static" / "js" / "applicantPortal.js"
APP_JS = _REPO / "static" / "app.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _portal_src() -> str:
    return PORTAL_JS.read_text(encoding="utf-8")


def _app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


# ===========================================================================
# #25 — modal root adopts .ow-window / .ow-titlebar / .ow-controls kit chrome
# ===========================================================================

def test_modal_root_adopts_ow_window_kit_chrome():
    src = _portal_src()
    # Note: the assignment itself ends with a semicolon; a nearby comment quotes
    # the same literal WITHOUT one (inside backticks) while explaining the
    # pattern, so the trailing `;` disambiguates the real statement from prose.
    assert re.search(r"""modal\.className\s*=\s*['"]modal hidden ow-window['"];""", src), (
        "the Portal modal root should carry .ow-window alongside the legacy .modal class"
    )
    assert re.search(r"""class=["']modal-header ow-titlebar["']""", src), (
        "the modal header should adopt the kit's .ow-titlebar"
    )
    assert re.search(r"""class=["']ow-controls["']""", src), (
        "the header should wrap its window controls in .ow-controls"
    )


def test_close_button_carries_all_three_required_classes_together():
    """Subtlety: `.ow-close` alone would look like kit adoption, but a shared
    mobile-sheet rule hides the desktop close-X via `.modal-close` on phones
    (swipe-to-dismiss takes over there), and `tap-exempt` exempts it from a
    tap-target rule. Losing either while keeping `.ow-close` is a real
    regression this test must catch."""
    src = _portal_src()
    m = re.search(r'<button[^>]*class="([^"]+)"[^>]*id="applicant-portal-close"', src)
    assert m, "could not find the Portal close button markup"
    classes = set(m.group(1).split())
    required = {"ow-close", "modal-close", "tap-exempt"}
    missing = required - classes
    assert not missing, (
        f"Portal close button is missing {sorted(missing)} (has {sorted(classes)}) — "
        "dropping modal-close breaks the mobile swipe-to-dismiss handoff and dropping "
        "tap-exempt breaks the tap-target exemption, even though ow-window kit "
        "adoption alone can look fine"
    )


# ===========================================================================
# Refresh demoted from .cal-btn to an icon-only .memory-toolbar-btn
# ===========================================================================

def test_refresh_button_demoted_to_icon_only_toolbar_btn():
    src = _portal_src()
    m = re.search(r'<button[^>]*class="([^"]+)"[^>]*id="applicant-portal-refresh"', src)
    assert m, "could not find the Portal refresh button markup"
    classes = m.group(1).split()
    assert "memory-toolbar-btn" in classes, (
        "the refresh control should be the icon-only .memory-toolbar-btn"
    )
    assert "cal-btn" not in classes, (
        "the refresh control should no longer carry the heavier .cal-btn treatment"
    )


# ===========================================================================
# Gated (setup-incomplete) empty state: neutral glyph, Semibold left-aligned
# copy, a real "Finish setup" CTA, AND the trust list rendered beneath it
# ===========================================================================

def test_gated_empty_state_renders_neutral_glyph_semibold_copy_and_cta():
    src = _portal_src()
    block = _slice_between(src, "function _renderGated(body, data) {", "function _neverDoesHTML()")
    assert 'd="M9 11l3 3L22 4"' in block, (
        "the gated state should reuse the neutral inbox/check glyph (same mark as the "
        "offline state), not a warning circle+!"
    )
    assert "font-weight:600" in block, "the gated heading copy should be Semibold"
    assert "text-align:left" in block, "the gated copy column should be left-aligned"
    assert 'id="applicant-portal-gated-setup"' in block and "Finish setup" in block, (
        "the gated state should offer a real 'Finish setup' CTA button"
    )
    assert "launchApplicantSetup" in block, (
        "the Finish setup CTA should route to the setup wizard launcher"
    )


def test_gated_empty_state_trust_list_renders_inline_not_just_a_header_toggle():
    """The header's 'What it never does' button (_toggleNeverDoesPanel) is a
    SEPARATE, always-available affordance. The gate additionally renders the
    trust list directly in the gated markup itself, reachable even before the
    header toggle is touched — assert the call site inside _renderGated, not
    merely that _neverDoesHTML/_toggleNeverDoesPanel exist somewhere in the file."""
    src = _portal_src()
    block = _slice_between(src, "function _renderGated(body, data) {", "function _neverDoesHTML()")
    assert "${_neverDoesHTML()}" in block, (
        "_renderGated should splice the trust list HTML directly into the gated "
        "empty-state markup via _neverDoesHTML(), not rely solely on the header toggle"
    )


# ===========================================================================
# Composer dimmed while Portal is open — _setComposerDimmed(), JS-scoped only
# ===========================================================================

def _composer_dimmed_block() -> str:
    src = _portal_src()
    return _slice_between(src, "let _composerDimmed = false;", "function _close() {")


def test_set_composer_dimmed_wired_on_open_and_close():
    src = _portal_src()
    open_block = _slice_between(src, "export async function openApplicantPortal(opts)", "\n}\n")
    assert "_setComposerDimmed(true)" in open_block, (
        "openApplicantPortal should dim the composer while the Portal is open"
    )
    close_block = _slice_between(src, "function _close() {", "// ── Greeting")
    assert "_setComposerDimmed(false)" in close_block, (
        "_close should un-dim the composer when the Portal closes"
    )


def test_set_composer_dimmed_toggles_and_restores_prior_style(node_available):
    """Executes the REAL `_setComposerDimmed` body (extracted from the live file
    at test time) against a fake `.chat-input-bar` element: dimming sets opacity
    + pointer-events, the double-dim guard doesn't re-capture a corrupted "prior"
    style, and un-dimming restores the exact original inline style (or removes
    the attribute entirely when there was none)."""
    block = _composer_dimmed_block()
    script = textwrap.dedent(f"""
        class FakeBar {{
          constructor() {{ this._attrs = {{}}; this.style = {{}}; }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this._attrs, name) ? this._attrs[name] : null;
          }}
          setAttribute(name, val) {{ this._attrs[name] = val; }}
          removeAttribute(name) {{ delete this._attrs[name]; }}
        }}
        const bar = new FakeBar();
        bar.setAttribute('style', 'color:red');
        globalThis.document = {{ querySelector: (sel) => (sel === '.chat-input-bar' ? bar : null) }};

        {block}

        const out = {{}};
        _setComposerDimmed(true);
        out.opacityWhileDimmed = bar.style.opacity;
        out.pointerEventsWhileDimmed = bar.style.pointerEvents;

        // Simulate the bar's style attribute drifting between two dim calls: the
        // guard must not re-capture this as the "prior" style to restore later.
        bar.setAttribute('style', 'color:blue');
        _setComposerDimmed(true); // already dimmed -> must be a no-op
        _setComposerDimmed(false);
        out.restoredStyle = bar.getAttribute('style');

        // A bar with no prior inline style: un-dimming should REMOVE the style
        // attribute entirely, not set it to the literal string "null".
        const bar2 = new FakeBar();
        globalThis.document = {{ querySelector: () => bar2 }};
        _setComposerDimmed(true);
        _setComposerDimmed(false);
        out.noPriorStyleWasRemoved = !Object.prototype.hasOwnProperty.call(bar2._attrs, 'style');

        // A missing composer bar (selector finds nothing) must not throw.
        globalThis.document = {{ querySelector: () => null }};
        let threw = false;
        try {{ _setComposerDimmed(true); }} catch (e) {{ threw = true; }}
        out.missingBarThrew = threw;

        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert out["opacityWhileDimmed"] == "0.35"
    assert out["pointerEventsWhileDimmed"] == "none"
    assert out["restoredStyle"] == "color:red", (
        "un-dimming should restore the ORIGINAL prior inline style captured on the "
        "first dim, not a value that drifted in during a spurious re-dim call"
    )
    assert out["noPriorStyleWasRemoved"] is True
    assert out["missingBarThrew"] is False


# ===========================================================================
# Lock badges (🔒) in app.js's refreshApplicantFeatures for genuinely
# unlockable nav items
# ===========================================================================

def _refresh_applicant_features_block() -> str:
    src = _app_src()
    return _slice_between(
        src,
        "window.refreshApplicantFeatures = function () {",
        "window._applicantFeaturesReady = window.refreshApplicantFeatures();",
    )


def test_lock_badge_marks_genuinely_unlockable_nav_items():
    block = _refresh_applicant_features_block()
    assert "applicant-lock-badge" in block
    assert "🔒" in block
    # The badge-creation gate itself must condition on present_but_disabled (not
    # just some unrelated `!!section.present_but_disabled` elsewhere in the
    # function, e.g. the click handler's `disabledInBuild` flag, which would
    # trivially satisfy a looser substring check).
    assert re.search(
        r"""!section\.present_but_disabled\s*&&\s*!e\.querySelector\(\s*['"]\.applicant-lock-badge['"]\s*\)""",
        block,
    ), (
        "the lock glyph should be reserved for genuinely-unlockable items — a "
        "present-but-disabled-in-this-build item has nothing to unlock and should "
        "not get a 'finish setup to open this' promise"
    )
    assert "launchApplicantSetup" in block, (
        "clicking a locked-but-unlockable nav item should route to the setup wizard"
    )


def test_lock_badge_removed_once_a_section_unlocks():
    block = _refresh_applicant_features_block()
    assert re.search(r"""querySelector\(['"]\.applicant-lock-badge['"]\)""", block), (
        "the active branch should look up any existing lock badge on the element"
    )
    assert "lockBadge.remove()" in block, (
        "the lock badge should be removed once its section goes active, so it doesn't "
        "linger as a stale promise after setup finishes"
    )


# ===========================================================================
# #33 (guard, lower priority) — Portal's modal chrome stays excluded from the
# small-element luminance-flip rule in appkitGlass.js (READ-ONLY reference;
# this file is not edited even temporarily, so this pin is NOT revert-verified
# like the tests above — it documents a real, already-correct invariant).
# ===========================================================================

def test_flip_set_excludes_portal_modal_chrome():
    glass_js = _REPO / "static" / "js" / "appkitGlass.js"
    src = glass_js.read_text(encoding="utf-8")
    m = re.search(r'var FLIP_SET\s*=\s*"([^"]+)"', src)
    assert m, "could not find FLIP_SET in appkitGlass.js"
    flip_selectors = {s.strip() for s in m.group(1).split(",")}
    # Portal's modal chrome (.modal-content / .ow-window) is a large surface that
    # mutes via the adaptive veil rather than flipping ink polarity like the small
    # bars/tiles in FLIP_SET.
    assert ".modal-content" not in flip_selectors
    assert ".ow-window" not in flip_selectors
    assert "#applicant-portal-modal" not in flip_selectors
