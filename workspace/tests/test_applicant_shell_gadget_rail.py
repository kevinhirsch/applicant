"""Regression coverage for P0-3 — the 3-pane shell's right-hand GADGET RAIL.

The shell is sidebar | chat (permanent center) | gadget rail. This file pins
the RAIL half: the new self-contained ``static/js/applicantRail.js`` surface,
its ``#applicant-gadget-rail`` mount + ``<script>`` reachability wiring in
``static/index.html``, and its CSS shell in ``static/style.css``.

The rail is explicitly a NEW LENS over EXISTING owner-scoped proxies — it
introduces NO new engine endpoints and duplicates NO engine logic. Each gadget
reads the SAME proxy its full-page module already reads, and opens that full
page via the SAME ``window`` launcher (never a floating window). These tests
assert exactly those reuse seams at the source level (the module self-boots on
import, so it is not importable under a bare node runtime without a DOM shim —
the same convention ``test_applicant_loop_health_chip.py`` /
``test_applicant_backlog_todaymode.py`` use for browser-only modules); the
rail's PURE helpers are exercised for real headlessly in
``tests/js/applicantRail.test.js``.

Each assertion was hand-verified to go RED when the piece it protects is
reverted, then restored to GREEN.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_RAIL_JS = _JS_DIR / "applicantRail.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_STYLE_CSS = _REPO / "static" / "style.css"


@pytest.fixture(scope="module")
def rail_src() -> str:
    return _RAIL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_src() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_src() -> str:
    return _STYLE_CSS.read_text(encoding="utf-8")


def test_rail_module_exists_and_exports_mount(rail_src: str) -> None:
    assert _RAIL_JS.is_file(), "applicantRail.js must ship"
    assert "export function mountApplicantRail" in rail_src
    assert "window.mountApplicantRail = mountApplicantRail" in rail_src
    assert "window.applicantRailModule" in rail_src


def test_index_mounts_the_rail_and_loads_the_module(index_src: str) -> None:
    # The mount is a static flex sibling of <main> (the third pane).
    assert 'id="applicant-gadget-rail"' in index_src
    # ...placed AFTER the chat <main> so body's flex row lays it out as the
    # right-hand column.
    main_close = index_src.index("</main>")
    rail_mount = index_src.index('id="applicant-gadget-rail"')
    assert rail_mount > main_close, "the rail must sit after </main> to be the right pane"
    # The module is loaded as an ES module.
    assert "/static/js/applicantRail.js" in index_src


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/applicant/portal/pending",       # 1 waiting on you
        "/api/applicant/tracker",              # 2 pipeline / 5 next interview
        "/api/applicant/activity",             # 3 recent activity
        "/api/applicant/campaigns",            # 4 cost & pace (guardrails)
        "/api/applicant/results",              # 7 momentum
        "/api/applicant/health/capabilities",  # 8 system health
        "/api/applicant/email/digest",         # 6 daily digest
    ],
)
def test_every_gadget_reads_an_existing_owner_scoped_proxy(rail_src: str, endpoint: str) -> None:
    # No gadget invents a new engine path — each reuses a proxy that already
    # exists in the front-door.
    assert endpoint in rail_src, f"gadget data source {endpoint} must be reused, not reinvented"


def test_all_eight_v1_gadgets_are_present(rail_src: str) -> None:
    # Waiting-on-you is the top notification area; the other seven are the
    # pinnable stack. All eight of the owner-confirmed v1 set must be wired.
    assert "applicant-rail-waiting" in rail_src, "1: waiting-on-you notification area"
    for gid in ("pipeline", "activity", "cost", "interview", "digest", "momentum", "health"):
        assert f"id: '{gid}'" in rail_src, f"gadget {gid} must be defined"


def test_gadget_deep_links_reuse_existing_window_launchers_not_windows(rail_src: str) -> None:
    # One click opens the matching FULL PAGE via the same launcher the page's
    # module already exports — never a floating/modal-stack window primitive.
    assert "window.openApplicantTracker" in rail_src
    assert "window.applicantActivityModule" in rail_src
    assert "window.openApplicantToday" in rail_src
    assert "window.openApplicantResults" in rail_src
    # The digest gadget reuses Email's own rail launcher seam, matching how
    # applicantToday.js opens the updates view.
    assert "rail-email" in rail_src


def test_digest_send_now_reuses_the_shared_deliver_helper(rail_src: str) -> None:
    # Send-now must go through applicantReachability.js's deliverDigestNow — the
    # ONE wired manual-digest lane — not a second hand-rolled fetch.
    assert "import { deliverDigestNow } from './applicantReachability.js'" in rail_src
    assert "deliverDigestNow(cid)" in rail_src


def test_notifications_reuse_showtoast_not_a_new_toast_system(rail_src: str) -> None:
    # The third notification surface (transient toasts) reuses ui.js showToast
    # via applicantCore's _toast — the rail must not rebuild a toast stack.
    # Pin the actual IMPORT binding (a locally-defined _toast helper would
    # otherwise satisfy the call-site check below).
    core_import = re.search(
        r"import\s*\{[^}]*\b_toast\b[^}]*\}\s*from\s*'\./applicantCore\.js'", rail_src
    )
    assert core_import, "_toast must be imported from applicantCore.js, not locally defined"
    assert "_toast(" in rail_src
    # Reuse the _toast wrapper; never call ui.js showToast directly or rebuild a
    # toast stack here (a bare `showToast(` call would be the tell).
    assert "showToast(" not in rail_src, "reuse _toast, do not call showToast directly"


def test_rail_layout_state_persists_in_localstorage(rail_src: str) -> None:
    assert "applicant-rail-collapsed" in rail_src, "collapse state persists"
    assert "applicant-rail-pins" in rail_src, "pin set persists"
    assert "localStorage.setItem" in rail_src and "localStorage.getItem" in rail_src


def test_waiting_area_is_the_top_notification_surface(rail_src: str) -> None:
    # The waiting-on-you area sits above the gadget stack and opens Today.
    waiting = rail_src.index("applicant-rail-waiting")
    gadgets = rail_src.index("applicant-rail-gadgets")
    assert waiting < gadgets, "waiting-on-you is the TOP notification area, above the gadgets"


def test_css_reserves_a_column_and_hides_on_mobile(css_src: str) -> None:
    assert ".applicant-gadget-rail" in css_src, "rail shell CSS must ship"
    # Collapsible to a slim badge strip.
    assert ".rail-collapsed" in css_src
    assert "applicant-rail-badges" in css_src
    # Small viewports: rail hides (the mobile bottom-sheet stays the fallback).
    tail = css_src[css_src.index(".applicant-gadget-rail"):]
    assert "@media (max-width: 768px)" in tail
    assert "display: none" in tail


def test_no_floating_window_primitive_in_the_rail(rail_src: str) -> None:
    # P0-3 retires floating windows from the shell surface: the rail must not
    # spawn one (no ow-window / modal scaffolding of its own).
    assert "ow-window" not in rail_src
    assert 'class="modal' not in rail_src
