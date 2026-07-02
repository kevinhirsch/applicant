"""Regression coverage for the two §C Chat/Mind design-audit follow-ups
(docs/design/audits/APPLE_GENIUS_IMPROVEMENTS.md, items 46 and 64) that PR
#578's chat/mind batch explicitly deferred as too risky to bundle with the
rest of that pass. This file finishes them, confined to
``static/js/applicantChat.js`` and the chat-modal-scoped regions of
``static/style.css``.

Follows the convention established by
``tests/test_applicant_round1_chatmind.py`` (itself following
``tests/bdd/steps/test_enh_uia11y_steps.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket. ``applicantChat.js`` does top-level ``document``/``fetch`` work
on import (it wires launchers via ``document.readyState``), so it is not
importable under a bare ``node --input-type=module`` the way a
dependency-free leaf module is — hence the text/regex approach throughout.

Every assertion below was verified, by hand, to actually go red when the
underlying fix is reverted (temporarily revert the source, rerun, see the
assertion fail with a real AssertionError, restore via ``git checkout``,
rerun green) per the batch's test-coverage discipline.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
CHAT_JS = JS_DIR / "applicantChat.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


# ===========================================================================
# Item #46 — dock the panel to the bottom content plane / real composer band,
# instead of a vertically centered floating slab.
# ===========================================================================

def test_chat_modal_docks_to_bottom_of_content_plane_on_desktop():
    """The assistant panel must anchor to the BOTTOM of the content plane on
    desktop (the real composer's band) rather than floating vertically
    centered mid-screen — a real, verifiable positional move within the
    modal's existing lifecycle. Scoped to #applicant-chat-modal only, inside
    the desktop (min-width:769px) media query, so it overrides the shared
    `.modal { align-items:center }` tool-window rule by id specificity
    without touching that shared rule or any other window's positioning."""
    css = _read(STYLE_CSS)
    m = re.search(r"@media \(min-width:\s*769px\)\s*\{", css)
    assert m, "expected a desktop (min-width:769px) media query in style.css"
    # Walk forward from some point after the item #46 CSS banner to find the
    # scoped #applicant-chat-modal rule nested in ITS OWN desktop media query
    # (the fix's own block, not the pre-existing shared tool-window block).
    banner_idx = css.index("Applicant Chat (applicantChat.js) — item #46")
    tail = css[banner_idx:]
    rule = re.search(
        r"@media \(min-width:\s*769px\)\s*\{\s*(?:/\*.*?\*/\s*)?"
        r"#applicant-chat-modal\s*\{([^}]*)\}",
        tail,
        re.S,
    )
    assert rule, (
        "expected a desktop-scoped '#applicant-chat-modal { ... }' rule near "
        "the item #46 CSS banner"
    )
    block = rule.group(1)
    assert re.search(r"align-items:\s*flex-end\s*;", block), (
        "#applicant-chat-modal must dock to the bottom (align-items: flex-end) "
        "on desktop instead of the shared centered floating-window alignment"
    )


def test_chat_modal_width_matches_real_composer_max_width():
    """The panel's width (`--window-w`) must match the real page composer's
    own max-width (800px, `.chat-input-bar { max-width: 800px; }` in
    style.css) so the docked panel and the real composer band line up
    instead of reading as two differently sized, unrelated elements."""
    css = _read(STYLE_CSS)
    # There are several selectors ending in ".chat-input-bar" (e.g. the
    # welcome-active variant, which only sets a transition) — anchor on the
    # base rule via its preceding "Unified chat input bar" comment banner so
    # this matches the one that actually declares max-width.
    banner_idx = css.index("Unified chat input bar")
    composer_block = re.search(r"\.chat-input-bar\s*\{([^}]*)\}", css[banner_idx:])
    assert composer_block, "expected a base .chat-input-bar rule in style.css"
    composer_max_width = re.search(r"max-width:\s*(\d+px)\s*;", composer_block.group(1))
    assert composer_max_width, "expected .chat-input-bar to declare a max-width"

    src = _read(CHAT_JS)
    m = re.search(r"function _ensureModalEl\(\)\s*\{(.*?)\nfunction _close", src, re.S)
    assert m, "expected to find _ensureModalEl"
    fn_body = m.group(1)
    window_w = re.search(r"--window-w:\s*(\d+px)\s*;", fn_body)
    assert window_w, "expected the chat modal's --window-w to be set inline"
    assert window_w.group(1) == composer_max_width.group(1), (
        f"chat modal --window-w ({window_w.group(1)}) must match the real "
        f"composer's max-width ({composer_max_width.group(1)}) so the docked "
        "panel lines up with the real composer band"
    )


def test_chat_composer_dimming_wired_on_open_and_close():
    """Docking the panel over the real composer's band means the two
    visually overlap while the panel is open. `_setComposerDimmed` (mirroring
    Portal's own composer-dimming, applicantPortal.js audit #32) must be
    called with `true` in `openApplicantChat` and with `false` in `_close`,
    and must target the REAL page composer (`#chat-container > .chat-input-bar`)
    — not this modal's own composer (`#applicant-composer`, which also
    carries the shared `.chat-input-bar` class but lives outside
    `#chat-container`)."""
    src = _read(CHAT_JS)
    assert "function _setComposerDimmed(on)" in src, (
        "expected a _setComposerDimmed helper in applicantChat.js"
    )
    dim_fn = _slice_between(src, "function _setComposerDimmed(on) {", "\n}\n")
    assert "#chat-container > .chat-input-bar" in dim_fn, (
        "_setComposerDimmed must scope its selector to the real page composer "
        "only, not any '.chat-input-bar' in the document (which would also "
        "match this modal's own composer)"
    )

    open_fn = _slice_between(src, "export async function openApplicantChat()", "\nfunction _wireLauncher")
    assert "_setComposerDimmed(true)" in open_fn, (
        "openApplicantChat must dim the real composer while the panel is open"
    )

    close_fn = _slice_between(src, "function _close() {", "\n// ── Empty")
    assert "_setComposerDimmed(false)" in close_fn, (
        "_close must un-dim the real composer when the panel closes"
    )


# ===========================================================================
# Item #64 — assistant modal header adopts .ow-window kit chrome so its
# titlebar matches every other window's traffic-light controls.
# ===========================================================================

def test_chat_modal_adopts_ow_window_kit_chrome():
    """Mirrors the exact pattern applicantPortal.js adopted (audit #25): the
    modal root carries `.ow-window` alongside the legacy `.modal`, the header
    adopts `.ow-titlebar`, and its controls are wrapped in `.ow-controls`."""
    src = _read(CHAT_JS)
    assert re.search(r"""modal\.className\s*=\s*['"]modal hidden ow-window['"];""", src), (
        "the chat modal root should carry .ow-window alongside the legacy .modal class"
    )
    assert re.search(r"""class=["']modal-header ow-titlebar["']""", src), (
        "the modal header should adopt the kit's .ow-titlebar"
    )
    assert re.search(r"""class=["']ow-controls["']""", src), (
        "the header should wrap its window controls in .ow-controls"
    )


def test_chat_close_button_carries_all_three_required_classes_together():
    """Subtlety Portal's batch discovered (and this file must not repeat
    losing): `.ow-close` alone would look like kit adoption, but a shared
    mobile-sheet rule hides the desktop close-X via `.modal-close` on phones
    (swipe-to-dismiss takes over there), and `.tap-exempt` exempts the dense
    titlebar control from the global coarse-pointer 44px tap-target floor.
    Losing either while keeping `.ow-close` is a real regression."""
    src = _read(CHAT_JS)
    m = re.search(r'<button[^>]*class="([^"]+)"[^>]*id="applicant-chat-close"', src)
    assert m, "could not find the chat modal close button markup"
    classes = set(m.group(1).split())
    required = {"ow-close", "modal-close", "tap-exempt"}
    missing = required - classes
    assert not missing, (
        f"chat modal close button is missing {sorted(missing)} (has {sorted(classes)}) — "
        "dropping modal-close breaks the mobile swipe-to-dismiss handoff and dropping "
        "tap-exempt breaks the tap-target exemption, even though ow-close kit adoption "
        "alone can look fine"
    )
