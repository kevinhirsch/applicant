"""X-4 (Accessibility pass) — keyboard-operability contract for the golden path.

DoD: "Keyboard-only completes the golden path" (digest -> review -> approve).
This pins the concrete gaps this pass found and fixed, verified against the
real shipped source (regex/text assertions — no browser/DOM, matching the
convention of the other ``test_applicant_round2_*``/``test_applicant_nav_*``
suites in this directory):

  1. Every sidebar nav destination (``applicantNav.js``'s ``.list-item``s,
     ``role="button" tabindex="0"``) is reachable by Enter/Space, not just
     click — including ``tool-library-btn`` ("Documents"), the entry point
     into the review step. Before this pass, only Portal/Gallery (which wire
     their own keydown handler) worked; Documents/Profile/Calendar/Daily
     updates were mouse-only when the sidebar is expanded (where the
     icon-rail is ``display:none`` and the sidebar is the ONLY door in).
  2. ``#doclib-modal`` (the review step's host) has real dialog semantics and
     is wired into the shared focus-trap/restore kit (``initModalA11y``) —
     previously it had none, and Tab escaped straight into the background app.
  3. The redline review pane (the actual diff a user is asked to approve) is
     keyboard-scrollable, not just mouse-scrollable.
  4. A skip-to-content link exists and its target is programmatically
     focusable, so a keyboard user doesn't have to Tab through the entire
     icon rail + sidebar on every page load to reach the golden path.
  5. Hover-revealed card action controls (Library/Documents row actions)
     stay visible when reached by keyboard focus, not just mouse hover.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAV_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantNav.js"
DOCLIB_JS = REPO_ROOT / "workspace" / "static" / "js" / "documentLibrary.js"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ── 1. sidebar nav keyboard activation ───────────────────────────────────────

def test_nav_wires_generic_keydown_activation_for_every_sidebar_item():
    src = _read(NAV_JS)
    assert "function _wireKeyboardActivation" in src, (
        "expected a generic keydown-to-click wiring pass over every rendered "
        "sidebar item — Enter/Space on a role=button div does not fire click "
        "natively"
    )
    # it must actually run as part of the render pipeline, not just be defined.
    assert re.search(r"_wireDelegates\(\);\s*\n\s*_wireKeyboardActivation\(\);", src), (
        "_wireKeyboardActivation must be invoked from renderNav()"
    )
    # the keydown handler must key off Enter/Space, matching the established
    # pattern used elsewhere in this file (_wireDelegates) and in
    # applicantPortal.js's own launcher wiring.
    fn_m = re.search(r"function _wireKeyboardActivation\(\) \{(.*?)\n\}\n", src, re.S)
    assert fn_m, "could not extract the _wireKeyboardActivation function body"
    body = fn_m.group(1)
    assert "'Enter'" in body and ("' '" in body or "'Spacebar'" in body)
    assert "sideEl.click()" in body


def test_documents_nav_item_is_not_excluded_from_keyboard_activation():
    """tool-library-btn (Documents) is the entry point into the review step —
    it must NOT be flagged keydownSelfWired/delegate (those exemptions are
    reserved for items proven to self-wire keydown elsewhere), so the generic
    pass in applicantNav.js actually covers it."""
    src = _read(NAV_JS)
    m = re.search(r"\{[^{}]*side:\s*'tool-library-btn'[^{}]*\}", src, re.S)
    assert m, "expected the tool-library-btn NAV item"
    item_src = m.group(0)
    assert "delegate:" not in item_src
    assert "keydownSelfWired" not in item_src


def test_portal_and_gallery_keydown_self_wired_flag_matches_their_own_wiring():
    """Portal/Gallery are the two items exempted from the generic pass — they
    must actually carry their own keydown wiring elsewhere (applicantPortal.js
    _wireLauncher / _wireKeydownActivation), or the exemption would silently
    strand them keyboard-unreachable again."""
    nav_src = _read(NAV_JS)
    portal_m = re.search(r"\{[^{}]*side:\s*'tool-portal-btn'[^{}]*\}", nav_src, re.S)
    gallery_m = re.search(r"\{[^{}]*side:\s*'tool-applicant-gallery-btn'[^{}]*\}", nav_src, re.S)
    assert portal_m and "keydownSelfWired: true" in portal_m.group(0)
    assert gallery_m and "keydownSelfWired: true" in gallery_m.group(0)

    portal_js = _read(REPO_ROOT / "workspace" / "static" / "js" / "applicantPortal.js")
    assert "_LAUNCHER_IDS = ['rail-portal', 'tool-portal-btn']" in portal_js
    assert "_KEYDOWN_ACTIVATE_ONLY_IDS = ['tool-applicant-gallery-btn']" in portal_js


# ── 2. #doclib-modal dialog semantics ────────────────────────────────────────

def test_doclib_modal_has_dialog_semantics_and_shared_focus_trap():
    src = _read(DOCLIB_JS)
    assert "modal.setAttribute('role', 'dialog')" in src
    assert "modal.setAttribute('aria-modal', 'true')" in src
    assert "modal.setAttribute('aria-labelledby', 'doclib-modal-title')" in src
    assert 'id="doclib-modal-title"' in src, "the visible <h4> must carry the id aria-labelledby points at"
    assert "uiModule.initModalA11y(modal," in src, (
        "the review host must use the shared focus-trap/restore kit, not a "
        "bespoke document-level Escape listener with no Tab trap"
    )
    # the cleanup must actually be invoked on close, or reopening leaks a trap.
    assert "_docLibA11yCleanup();" in src


# ── 3. redline pane keyboard-scrollable ─────────────────────────────────────

def test_redline_pane_is_keyboard_focusable_and_labelled():
    src = _read(DOCLIB_JS)
    m = re.search(
        r"redline\.className = 'doclib-applicant-redline';.*?"
        r"redline\.setAttribute\('tabindex', '0'\);.*?"
        r"redline\.setAttribute\('aria-label', '([^']+)'\);",
        src,
        re.S,
    )
    assert m, (
        "expected the redline scroll box (max-height:200px;overflow:auto) to "
        "be tabindex=0 + labelled — otherwise a keyboard user cannot read past "
        "the first 200px of the diff they're being asked to approve"
    )
    assert "scrollable" in m.group(1).lower()


# ── 4. skip-to-content link ──────────────────────────────────────────────────

def test_skip_link_is_first_in_body_and_targets_a_focusable_main_region():
    html = _read(INDEX_HTML)
    body_m = re.search(r"<body>\s*(<!--.*?-->\s*)*<a[^>]*class=\"skip-link\"[^>]*>", html, re.S)
    assert body_m, "expected <a class=\"skip-link\"> to be the first real element in <body>"
    link_m = re.search(r'<a href="#([\w-]+)" class="skip-link">([^<]+)</a>', html)
    assert link_m, "expected a skip-link anchor with an href fragment target"
    target_id, label = link_m.group(1), link_m.group(2)
    assert "skip" in label.lower()
    # the target must exist and be programmatically focusable (tabindex="-1"
    # — a fragment jump to a non-interactive <main> would otherwise only
    # scroll the viewport without moving keyboard focus there).
    target_m = re.search(rf'id="{re.escape(target_id)}"[^>]*', html)
    assert target_m, f"skip-link target #{target_id} does not exist"
    assert 'tabindex="-1"' in target_m.group(0), (
        f"#{target_id} must be tabindex=\"-1\" so the skip-link actually moves "
        "keyboard focus there, not just the scroll position"
    )

    css = _read(STYLE_CSS)
    assert ".skip-link {" in css and ".skip-link:focus {" in css
    # must not be display:none (fails focus visibility on the fixed audit's
    # own account) — the off-screen technique must use position, not display.
    rule_m = re.search(r"\.skip-link \{([^}]*)\}", css)
    assert rule_m and "display" not in rule_m.group(1)


# ── 5. hover-revealed card actions reachable by focus ───────────────────────

def test_hover_revealed_card_actions_also_reveal_on_focus_within():
    css = _read(STYLE_CSS)
    assert re.search(r"\.memory-item:focus-within \.memory-menu-btn\s*\{", css), (
        "the row's icon-only menu button (opacity:0 until hover) must also "
        "reveal on :focus-within, or a keyboard user tabs onto an invisible "
        "control"
    )
    assert re.search(r"\.memory-item:focus-within \.memory-item-actions\s*\{", css) or re.search(
        r"\.memory-item:hover \.memory-item-actions,\s*\n\.memory-item:focus-within \.memory-item-actions\s*\{",
        css,
    ), "the row action button group must also reveal on :focus-within"


# ── Denylist hygiene (per the standing white-label instruction) ─────────────
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        assert (first + second) not in text
