"""Regression coverage for P0-3b — the shell's TOP-BAR NOTIFICATION BELL.

The 3-pane shell's notification story is exactly three surfaces: the rail's
waiting-on-you area, transient toasts, and — this file — the top-bar bell +
dropdown. The bell is explicitly a NEW LENS over the SAME owner-scoped backing
the rail's waiting area and the Portal already read
(``GET /api/applicant/portal/pending``): it introduces NO new engine endpoint,
duplicates NO Portal/Today resolve logic, and opens Today via the SAME
``window.openApplicantToday`` launcher the rail uses.

"Acting on an item clears it from bell, rail, AND portal at once" is delivered
by a single shared backing read plus one cross-surface signal: the Portal's
authoritative ``_setBadge`` dispatches ``applicant:pending-changed`` on every
count change, and BOTH the bell and the rail listen for it and re-read. These
tests pin those reuse seams at the source level (the module self-boots on import,
so it is not importable under a bare node runtime without a DOM shim — the same
convention ``test_applicant_shell_gadget_rail.py`` uses); the bell's PURE helpers
are exercised for real headlessly in ``tests/js/applicantBell.test.js``.

Each assertion was hand-verified to go RED when the piece it protects is
reverted, then restored to GREEN.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_BELL_JS = _JS_DIR / "applicantBell.js"
_RAIL_JS = _JS_DIR / "applicantRail.js"
_PORTAL_JS = _JS_DIR / "applicantPortal.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_STYLE_CSS = _REPO / "static" / "style.css"


@pytest.fixture(scope="module")
def bell_src() -> str:
    return _BELL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rail_src() -> str:
    return _RAIL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def portal_src() -> str:
    return _PORTAL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_src() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_src() -> str:
    return _STYLE_CSS.read_text(encoding="utf-8")


# ── the module ships and self-boots ──────────────────────────────────────────

def test_bell_module_exists_and_exports_mount(bell_src: str) -> None:
    assert _BELL_JS.is_file(), "applicantBell.js must ship"
    assert "export function mountApplicantBell" in bell_src
    assert "window.mountApplicantBell = mountApplicantBell" in bell_src
    assert "window.applicantBellModule" in bell_src


def test_index_mounts_the_bell_in_the_top_bar_and_loads_the_module(index_src: str) -> None:
    # The bell wrap is inside the chat top bar (the shell's top bar).
    bar = index_src.index('class="chat-top-bar"')
    wrap = index_src.index('id="applicant-bell-wrap"')
    # The chat-top-bar div closes before the welcome screen; assert the bell
    # sits between the bar's opening and the chat history that follows it.
    history = index_src.index('id="chat-history"')
    assert bar < wrap < history, "the bell must live in the chat top bar"
    # The three sub-parts exist: button, count badge, dropdown menu.
    assert 'id="applicant-bell-btn"' in index_src
    assert 'id="applicant-bell-badge"' in index_src
    assert 'id="applicant-bell-dropdown"' in index_src
    # Loaded as an ES module.
    assert "/static/js/applicantBell.js" in index_src


# ── new lens, not a new endpoint / not a rebuild ─────────────────────────────

def test_bell_reuses_the_shared_pending_feed_no_new_endpoint(bell_src: str) -> None:
    # Same backing read as the rail's waiting area and the Portal — no invented
    # engine path.
    assert "/api/applicant/portal" in bell_src
    assert "/pending" in bell_src
    # The only other applicant proxy it may touch is none — assert it does not
    # invent a bespoke resolve/notification endpoint of its own.
    assert "/api/applicant/portal/notifications" not in bell_src
    assert "/api/applicant/bell" not in bell_src


def test_bell_opens_today_via_the_existing_launcher_not_a_window(bell_src: str) -> None:
    # Clicking an item hands off to Today (the run-through) via the SAME launcher
    # the rail uses — the bell never rebuilds Today's resolve/answer/snooze UI.
    assert "window.openApplicantToday" in bell_src
    # Fallback path reuses the Portal module's own opener, not a floating window.
    assert "window.applicantPortalModule" in bell_src
    # It must NOT re-implement the resolve POST (that lives in Today/Portal).
    assert "/resolve" not in bell_src, "the bell routes to Today to act; it does not rebuild resolve"


# ── the "clears everywhere at once" contract ─────────────────────────────────

def test_portal_dispatches_the_shared_pending_changed_signal(portal_src: str) -> None:
    # The Portal's authoritative count setter fans a single cross-surface event
    # out whenever the pending count moves, so a resolve here reaches the other
    # surfaces without waiting out their polls.
    setbadge = portal_src.index("function _setBadge(")
    body = portal_src[setbadge:setbadge + 900]
    assert "applicant:pending-changed" in body, "_setBadge must dispatch the shared signal"
    assert "dispatchEvent" in body


def test_bell_listens_for_the_shared_signal_and_re_reads(bell_src: str) -> None:
    assert "applicant:pending-changed" in bell_src
    assert "addEventListener('applicant:pending-changed'" in bell_src \
        or 'addEventListener("applicant:pending-changed"' in bell_src \
        or "addEventListener(PENDING_CHANGED_EVENT" in bell_src


def test_rail_also_listens_for_the_shared_signal(rail_src: str) -> None:
    # The third surface (rail waiting area) clears in lockstep too.
    assert "applicant:pending-changed" in rail_src
    assert "addEventListener('applicant:pending-changed'" in rail_src


# ── owner-only by construction, no dead UI ───────────────────────────────────

def test_bell_hides_when_the_feed_is_unreachable_or_gated(bell_src: str) -> None:
    # A non-owner / down / gated engine yields no bell at all (the wrap ships
    # display:none and is only unhidden on a real, reachable feed).
    assert "engine_available === false" in bell_src
    assert "gated === true" in bell_src
    assert "style.display = 'none'" in bell_src
    # The static markup starts hidden so it never flashes before the first read.
    idx = _INDEX_HTML.read_text(encoding="utf-8")
    wrap = idx.index('id="applicant-bell-wrap"')
    assert "display:none" in idx[wrap - 200:wrap + 200], "the bell wrap must ship hidden"


# ── styling reuses the design system, hides on mobile ────────────────────────

def test_bell_css_present_and_collapses_on_mobile(css_src: str) -> None:
    assert ".applicant-bell-wrap" in css_src
    assert ".applicant-bell-dropdown" in css_src
    # Mobile keeps the existing Portal bottom-sheet + toasts; the top-bar bell is
    # a desktop shell affordance, so it hides under the same 768px breakpoint the
    # rail uses.
    m = re.search(r"@media \(max-width: 768px\) \{[^}]*\.applicant-bell-wrap[^}]*display:\s*none", css_src, re.S)
    assert m, "the bell must hide on small viewports like the rail"


# ── white-label: no codenames / no FR-jargon in the shipped bell strings ─────

def test_bell_user_facing_strings_are_plain_language(bell_src: str, index_src: str) -> None:
    for token in ("FR-", "NFR-"):
        assert token not in bell_src, f"no spec jargon in the bell module ({token})"
    # The visible labels read as product language.
    assert "Notifications" in index_src
    assert "waiting on you" in bell_src.lower()
