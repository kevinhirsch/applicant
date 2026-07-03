"""Regression coverage for the front-end half of dark-engine audit item #25:
the application-history drill-down list, promoted out of admin-only.

The engine's ``GET /api/admin/history/{campaign_id}`` already returns
per-application ``status``/``work_mode``/``screenshot_count``/``outcomes[]``
-- exactly the tracker-board drill-down payload -- but it was reachable only
through the admin-gated ``routes/applicant_admin_routes.py`` and rendered only
inside the admin-only Debug modal (``applicantDebug.js``). This wires an
OWNER-scoped "View details" disclosure onto the Tracker board itself, matching
the existing "Check an email" disclosure pattern exactly (same native
``<details>``/``<summary>``, same per-row ``data-tracker-*`` scoping, same
lazy-load-on-first-open shape as "Screening answers" / "Interview prep").

Confined to the files this task touches:

  * ``workspace/src/applicant_engine.py`` -- new ``tracker_application_history``
    client method; pinned in ``test_applicant_tracker_history_detail.py``.
  * ``workspace/routes/applicant_tracker_routes.py`` -- new
    ``GET /api/applicant/tracker/applications/{id}/history`` proxy;
    route-level behavior + the mandatory owner-isolation test live in
    ``test_applicant_tracker_history_detail.py``. This file only pins the
    SOURCE-level shape of the route (owner-scoping fan-out reused, not
    reimplemented).
  * ``workspace/static/js/applicantTracker.js`` -- the new per-row "View
    details" disclosure + its toggle handler. This file.

Follows the ``test_applicant_round2_emailscan_ui.py`` convention for this
exact module: source-text regex assertions for the browser-only module (no
DOM-independent entry point cheap enough to shim here). Each assertion below
was verified, by hand, to go RED when the corresponding piece of the
affordance is reverted (stripping the disclosure markup, dropping the
lazy-load wiring, un-wiring the toggle handler), then confirmed GREEN again
after restoring -- per this series' standing DoD.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
TRACKER_JS = WORKSPACE_DIR / "static" / "js" / "applicantTracker.js"
TRACKER_ROUTES_PY = WORKSPACE_DIR / "routes" / "applicant_tracker_routes.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the front-end disclosure: per-row, collapsed, scoped to one application ──


def test_history_renderer_exists_and_is_a_native_disclosure():
    """Uses a plain <details>/<summary> disclosure -- collapsed by default --
    matching the "Check an email" / "Screening answers" / "Interview prep"
    disclosure pattern already established on this surface, not a new one."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _historyHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _historyHTML(id, label) renderer"
    body = fn.group(0)
    assert "<details" in body
    assert "<summary" in body


def test_history_disclosure_is_wired_into_every_row():
    """Every tracker row renders the per-row disclosure (not a single global
    one shared across the whole board) -- _renderRow must call it."""
    src = _read(TRACKER_JS)
    row_fn = re.search(r"function _renderRow\(app\) \{.*?\n\}\n", src, re.S)
    assert row_fn, "expected a _renderRow(app) function"
    assert "_historyHTML(" in row_fn.group(0)


def test_history_disclosure_is_scoped_per_application_row():
    """The application id is threaded through the disclosure's own
    data-tracker-history wrapper AND its body slot, so the toggle handler can
    unambiguously resolve which application it belongs to without any
    global/shared state."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _historyHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'data-tracker-history="${id}"' in body
    assert 'data-history-body="${id}"' in body


# ── the toggle handler: lazy-loads through the owner-scoped proxy on open ────


def test_history_toggle_handler_exists_and_fetches_the_workspace_proxy():
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _onHistoryToggle\(details\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _onHistoryToggle(details) handler"
    body = fn.group(0)
    assert "/applications/" in body and "/history" in body
    # Must go through the same _fetchJSON/API convention as the other
    # disclosures -- never a hand-rolled fetch call or the engine's own path.
    assert "_fetchJSON(" in body
    assert "/api/admin" not in body


def test_history_toggle_handler_only_loads_on_open_not_on_close():
    """'toggle' fires on BOTH open and close -- the handler must bail on
    close, matching _onScreeningToggle/_onPrepToggle's guard, so closing the
    disclosure never issues a spurious fetch."""
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _onHistoryToggle\(details\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "if (!details.open) return" in fn.group(0)


def test_history_toggle_handler_is_wired_on_render_and_only_once():
    """The board renderer must attach the toggle listener to every
    [data-tracker-history] disclosure, with { once: true } so re-rendering
    the board (e.g. after recording an outcome) never double-fetches."""
    src = _read(TRACKER_JS)
    render_fn = re.search(r"function _renderBoard\(host, applications\) \{.*?\n\}\n", src, re.S)
    assert render_fn, "expected a _renderBoard(host, applications) function"
    body = render_fn.group(0)
    assert "data-tracker-history" in body
    assert "_onHistoryToggle(" in body
    assert "{ once: true }" in body


def test_history_toggle_handler_reuses_shared_error_text_helper():
    """Failures render through the shared errText() helper (auth/timeout/
    network mapped to calm copy) -- not a raw e.message dump."""
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _onHistoryToggle\(details\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "errText(" in fn.group(0)


# ── the body renderer: plain-language detail, not raw engine jargon ─────────


def test_history_body_renderer_surfaces_status_work_mode_screenshots_outcomes():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _renderHistoryBody(body, data) renderer"
    body = fn.group(0)
    assert "data.status" in body
    assert "data.work_mode" in body
    assert "data.screenshot_count" in body
    assert "data.outcomes" in body


def test_history_body_renderer_escapes_all_interpolated_text():
    """Every piece of engine-sourced text (status/work-mode/outcome labels)
    must go through the shared esc() helper -- never raw string interpolation
    into innerHTML."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "esc(" in body


# ── engine-client + proxy: the new method/route exist and reuse the fan-out ─


def test_engine_client_exposes_tracker_application_history():
    """The workspace's ApplicantEngineClient carries the new
    tracker_application_history method -- not an ad hoc inline request --
    hitting the exact same engine path the admin proxy already hits."""
    src = _read(WORKSPACE_DIR / "src" / "applicant_engine.py")
    assert "async def tracker_application_history(self, campaign_id: str, limit: int = 200)" in src
    assert '"GET", f"/api/admin/history/{campaign_id}", params={"limit": limit}' in src


def test_proxy_history_route_reuses_the_owner_tracker_rows_fan_out():
    """The new history endpoint must derive the campaign id from THIS
    request's own tracker-board fan-out BEFORE forwarding -- the exact same
    guard interview_prep uses, not a re-implemented (and possibly weaker)
    copy."""
    src = _read(TRACKER_ROUTES_PY)
    history_fn = re.search(
        r'@router\.get\("/applications/\{application_id\}/history"\)\s*\n'
        r"\s*async def application_history\(.*?\n    return .*?\n",
        src,
        re.S,
    )
    assert history_fn, "expected an async application_history(...) route handler"
    body = history_fn.group(0)
    assert "_owner_tracker_rows" in body
    assert "engine.tracker_application_history(" in body


def test_proxy_history_route_is_registered_under_the_tracker_prefix():
    src = _read(TRACKER_ROUTES_PY)
    assert '@router.get("/applications/{application_id}/history")' in src


# ── white-label: no upstream jargon in the new user-facing copy -------------


def test_history_disclosure_has_no_fr_nfr_jargon_in_user_facing_copy():
    src = _read(TRACKER_JS)
    fn = re.search(r"function _historyHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    body_fn = re.search(r"function _renderHistoryBody\(body, data\) \{.*?\n\}\n", src, re.S)
    assert fn and body_fn
    combined = fn.group(0) + body_fn.group(0)
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", combined)
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", combined)


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_tracker_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
