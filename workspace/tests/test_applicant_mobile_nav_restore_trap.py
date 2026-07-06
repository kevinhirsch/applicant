"""Regression coverage for the mobile navigation trap + cross-device
window-state restore bug (audit ledger #113 P0 / #114 P1):

  #113: after login on a 390x844 phone, a leftover desktop session's "New
  Email" compose window was restored FULL-SCREEN; once any modal in front of
  it was dismissed, the user was trapped — no nav, no hamburger, only a tiny
  bottom-left close control on the restored panel itself.

  #114: open-window UI state persisted across sessions AND devices — a
  compose window opened on desktop reappeared on a fresh mobile login —
  because the restore path is driven by session data that is genuinely
  cross-device (the "most-recently-active session" and its
  server-tracked `has_documents`/active-document rows), not by anything
  scoped to the browser/viewport that is loading it.

Root cause (two cooperating bugs):

  1. `static/js/sessions.js` `loadSessions()` auto-selects the account's
     most-recently-active NON-transient session whenever the loading
     browser has no session pointer of its own (no `#hash`, no
     `currentSessionId`, no `lastSessionId` in *this* browser's
     localStorage) — exactly the state of a brand-new device/login. That
     selection is server-side data, so it is the same on every device.
  2. `static/js/document.js` `loadSessionDocs()` then unconditionally
     opened the doc/email panel whenever the selected session had any
     active document row (`d.is_active`) — regardless of viewport, and
     regardless of whether this exact browser had ever chosen to leave
     that panel open (the "Always open when there are docs" comment
     removed the prior, more conservative gate). On a narrow viewport
     that panel is a FULL-SCREEN sheet (`.doc-editor-pane` mobile media
     query in style.css), and that same query used to also hide the only
     hamburger/nav entry point whenever the sheet was showing
     (`body.doc-view .hamburger-btn { display: none !important; }`) — so
     a surprise full-screen restore left no way back to nav at all.

Fix (both landed in this change):

  (a)/(b) `document.js` `loadSessionDocs()` now treats a `restoreMode`
      load on a mobile viewport (`window.innerWidth <= 768`) the same way
      it already treats an explicit per-device "user minimized it" choice:
      surface a dock chip instead of forcing the full-screen sheet open.
      `app.js`'s own boot-time "reopen if it was open before refresh" path
      gets the same `window.innerWidth > 768` guard. Together these mean
      desktop window state is never auto-restored into a mobile viewport;
      explicit user actions (toolbar button, slash command, `forceOpen`)
      are untouched on every viewport since they never pass `restoreMode`.
  (c) `style.css` no longer hides `.hamburger-btn` when `body.doc-view` is
      set on mobile. The hamburger's z-index (210) already sits above both
      the full-screen doc pane (170) and the mobile sidebar it opens (200),
      so nav stays reachable even if a doc/email panel is showing full
      screen for any other reason — belt-and-suspenders against ever
      trapping the user with literally no way back to nav.

There is no jsdom/DOM shim rich enough in this repo to safely execute
`loadSessionDocs()` for real without also faking out its large rendering
side (tab bar, indicator badges, etc.) — see `test_applicant_round1_
missingkits.py`'s docstring for the precedent on why that trade-off is
made deliberately elsewhere. Since the two invariants this bug is about —
"the mobile restore branch runs and returns *before* the unconditional
open", and "the hamburger's stacking order beats the doc pane and the
sidebar it opens" — are both structural/ordering facts rather than
dynamic computed values, this file source-pins them directly (the same
style `frontend/tests/test_0752_persistent_surface_stability.py` uses for
CSS layering policy), and additionally regex-parses the actual z-index
integers out of their rule blocks so a future edit that changes the
numbers (rather than deleting the rule) still fails loudly.

Every assertion below was checked against the pre-fix source (the state
before this change) and confirmed to fail there:
  - the mobile `restoreMode` gate didn't exist, so `test_mobile_restore_
    gate_runs_before_unconditional_open` failed (pattern not found).
  - `app.js`'s boot restore had no viewport guard, so `test_boot_time_
    restore_is_gated_to_non_mobile_viewports` failed.
  - `body.doc-view .hamburger-btn { display: none !important; }` was
    present, so `test_hamburger_is_never_hidden_for_doc_view_on_mobile`
    failed.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_DOCUMENT_JS = _REPO / "static" / "js" / "document.js"
_APP_JS = _REPO / "static" / "app.js"
_STYLE_CSS = _REPO / "static" / "style.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── (a)/(b) document.js: mobile restoreMode gate ──────────────────────────

def test_mobile_restore_gate_runs_before_unconditional_open():
    """`loadSessionDocs` must check `restoreMode && window.innerWidth <= 768`
    and `return` (via the dock-chip path, mirroring the existing explicit
    "user minimized it" branch) strictly BEFORE the unconditional
    `openPanel()` / `switchToDoc(target.id)` fallthrough — otherwise a
    session auto-selected at boot/login (a cross-device, server-driven
    choice) still force-opens a full-screen sheet on a phone."""
    src = _read(_DOCUMENT_JS)

    gate_match = re.search(
        r"if\s*\(\s*restoreMode\s*&&\s*window\.innerWidth\s*<=\s*768\s*\)\s*\{"
        r"(?P<body>.*?)\n\s*\}",
        src,
        re.DOTALL,
    )
    assert gate_match, (
        "loadSessionDocs is missing the `restoreMode && window.innerWidth <= 768` "
        "mobile-restore gate in static/js/document.js"
    )
    gate_body = gate_match.group("body")
    assert "Modals.minimize('doc-panel')" in gate_body, (
        "the mobile-restore gate must surface a dock chip (Modals.minimize), "
        "not silently drop the document"
    )
    assert re.search(r"\breturn\s*;", gate_body), (
        "the mobile-restore gate must return before falling through to the "
        "unconditional open below it"
    )

    # The unconditional open this gate exists to guard.
    open_match = re.search(
        r"if\s*\(!isOpen\)\s*openPanel\(\);\s*\n\s*switchToDoc\(target\.id\);",
        src,
    )
    assert open_match, (
        "expected the unconditional `if (!isOpen) openPanel(); switchToDoc(target.id);` "
        "fallthrough in loadSessionDocs to still exist for desktop/explicit opens"
    )
    assert gate_match.start() < open_match.start(), (
        "the mobile-restore gate must appear BEFORE the unconditional open in "
        "loadSessionDocs, or it can never prevent the full-screen restore"
    )


def test_mobile_restore_gate_is_scoped_to_restoreMode_only():
    """Explicit opens (toolbar button/slash-command/forceOpen) never pass
    `restoreMode`, so the gate's condition must require `restoreMode` — a
    bare `window.innerWidth <= 768` check would also block a user's own
    explicit "open the document" tap on mobile, which is not the bug."""
    src = _read(_DOCUMENT_JS)
    assert "if (restoreMode && window.innerWidth <= 768) {" in src


# ── (b) app.js: boot-time per-device restore also viewport-gated ─────────

def test_boot_time_restore_is_gated_to_non_mobile_viewports():
    """The "reopen the doc panel if it was left open before refresh" boot
    path in app.js must not fire on a mobile viewport either — even though
    that flag is per-browser (not cross-device), forcing the full-screen
    sheet open on a phone is the same trap regardless of why it fired."""
    src = _read(_APP_JS)
    assert re.search(
        r"if\s*\(\s*_curSession\s*&&\s*window\.innerWidth\s*>\s*768\s*&&\s*"
        r"localStorage\.getItem\(\s*['\"]applicant-doc-open-['\"]\s*\+\s*_curSession\s*\)"
        r"\s*===\s*['\"]1['\"]\s*\)",
        src,
    ), "app.js boot-time doc-panel restore is missing the `window.innerWidth > 768` guard"


# ── (c) style.css: hamburger must never be hidden by doc-view on mobile ──

def _extract_block(css: str, needle: str) -> str:
    """Return the `{ ... }` body of the first rule whose selector text
    contains `needle` (brace-balance walk — the file has nested @media
    blocks, so a naive `}` search would truncate early)."""
    start = css.index(needle)
    open_brace = css.index("{", start)
    depth = 0
    for i in range(open_brace, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1:i]
    raise AssertionError(f"unbalanced braces looking for block after {needle!r}")


def _z_index_of(css: str, needle: str) -> int:
    body = _extract_block(css, needle)
    m = re.search(r"z-index:\s*(\d+)", body)
    assert m, f"no z-index found in the rule block containing {needle!r}"
    return int(m.group(1))


def test_hamburger_is_never_hidden_for_doc_view_on_mobile():
    """The exact regression pattern from ledger #113: hiding the ONLY nav
    entry point whenever a document/email panel happens to be showing on
    mobile. A restored/auto-opened panel must never be able to take the
    hamburger down with it."""
    css = _read(_STYLE_CSS)
    assert "body.doc-view .hamburger-btn" not in css, (
        "style.css still hides .hamburger-btn for body.doc-view on mobile — "
        "this is the mobile-nav-trap regression (ledger #113)"
    )
    # The notes-pane hiding rule is a deliberate, separate design choice
    # (its own close control) and is explicitly out of scope for this fix —
    # confirm it's still there so this test isn't silently matching a
    # wholesale deletion of the block instead of the targeted removal.
    assert "body:has(#notes-pane) .hamburger-btn" in css


def test_hamburger_stacking_beats_the_full_screen_doc_pane_and_its_sidebar():
    """Even setting aside the explicit hide rule above: the hamburger must
    out-rank (higher z-index than) both the full-screen doc/email pane and
    the mobile sidebar it opens, so tapping it always visibly brings nav to
    the front no matter what full-screen sheet is currently showing."""
    css = _read(_STYLE_CSS)

    hamburger_z = _z_index_of(css, "/* Fixed hamburger")
    doc_pane_z = _z_index_of(css, "body.doc-view .doc-editor-pane {")
    sidebar_z = _z_index_of(css, "/* Sidebar overlays chat on mobile */")

    assert hamburger_z > sidebar_z > doc_pane_z, (
        f"expected hamburger ({hamburger_z}) > mobile sidebar ({sidebar_z}) > "
        f"full-screen doc pane ({doc_pane_z}) so the hamburger (and the sidebar "
        f"it opens) always render above a restored full-screen panel"
    )
