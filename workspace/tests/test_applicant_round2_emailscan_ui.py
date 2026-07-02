"""Regression coverage for round 2 / phase 2 of the "variable reward" outcome
loop (design-audit Top-25 #5, systemic theme #3): the SAFE, manual "close the
loop" affordance.

Phase 1 (already merged) built the ENGINE side only:
``POST /api/post-submission/applications/{id}/scan-email`` --
``PostSubmissionService.scan_email`` -- classifying a pasted email's
subject/body against the rejection/interview/offer keyword detectors and
recording whatever confidently matched. It deliberately stopped short of
automatic inbox-to-application matching (a mis-attributed email risks
recording a fake outcome against the wrong application).

This phase wires that engine endpoint to the front door WITHOUT introducing
that risk: the owner explicitly picks which application an email belongs to
by expanding that SPECIFIC row's own "Check an email" disclosure in the
Tracker surface, so there is never any ambiguity about which application is
being scanned.

Confined to the files this task touches:

  * ``workspace/src/applicant_engine.py`` -- new ``tracker_scan_email`` client
    method.
  * ``workspace/routes/applicant_tracker_routes.py`` -- new
    ``POST /api/applicant/tracker/applications/{id}/scan-email`` proxy;
    route-level behavior + the mandatory owner-isolation test live in
    ``workspace/tests/test_applicant_tracker_routes.py``. This file only
    pins the SOURCE-level shape of the route (owner-scoping guard reused,
    not reimplemented).
  * ``workspace/static/js/applicantTracker.js`` -- the new per-row "Check an
    email" disclosure + its submit handler. This file.

Follows the ``test_applicant_round2_wave3_trackersurface.py`` convention for
this exact module: source-text regex assertions for the browser-only module
(no DOM-independent entry point cheap enough to shim here). Each assertion
below was verified, by hand, to go red when the corresponding piece of the
affordance is reverted (stripping the disclosure markup, dropping the
owner-scoping guard reuse, un-wiring the click handler), then confirmed
green again after restoring -- per this series' standing DoD.
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
ENGINE_CLIENT_PY = WORKSPACE_DIR / "src" / "applicant_engine.py"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── the front-end disclosure: per-row, collapsed, scoped to one application ──


def test_scan_email_renderer_exists_and_is_a_native_disclosure():
    """Uses a plain <details>/<summary> disclosure -- collapsed by default --
    not a giant always-visible textarea on every row, matching the
    onboarding wizard's existing "Advanced" / "What Applicant never does"
    disclosure pattern (applicantOnboarding.js's <details class="ao-adv">)."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _scanEmailHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _scanEmailHTML(id, label) renderer"
    body = fn.group(0)
    assert "<details" in body
    assert "<summary" in body


def test_scan_email_disclosure_is_wired_into_every_row():
    """Every tracker row renders the per-row disclosure (not a single global
    one shared across the whole board) -- _renderRow must call it."""
    src = _read(TRACKER_JS)
    row_fn = re.search(r"function _renderRow\(app\) \{.*?\n\}\n", src, re.S)
    assert row_fn, "expected a _renderRow(app) function"
    assert "_scanEmailHTML(" in row_fn.group(0)


def test_scan_email_disclosure_carries_subject_and_body_fields():
    """A two-field affordance (subject + body), not a single opaque blob --
    matches the engine's ScanEmailIn(subject, body) shape 1:1."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _scanEmailHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "data-scan-subject" in body
    assert "data-scan-body" in body
    assert "<textarea" in body, "expected a textarea for the email body"
    assert "data-scan-submit" in body, "expected a submit affordance"


def test_scan_email_disclosure_reuses_the_shared_input_class_not_a_hand_rolled_one():
    """CLAUDE.md: reuse the workspace design system, don't hand-roll input
    styling. Must use the shared `.cal-input` class already used for every
    other text field/textarea in this app (see calendar.js)."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _scanEmailHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'class="cal-input"' in body
    assert 'class="cal-btn"' in body, "expected the shared button class for the submit action"


def test_scan_email_disclosure_is_scoped_per_application_row():
    """The application id is threaded through the disclosure's own
    data-tracker-scan wrapper AND its subject/body/result/submit fields, so a
    click handler can unambiguously resolve which application it belongs to
    without any global/shared state."""
    src = _read(TRACKER_JS)
    fn = re.search(r"function _scanEmailHTML\(id, label\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "data-tracker-scan=\"${id}\"" in body


# ── the submit handler: posts to the owner-scoped proxy, never the engine ───


def test_scan_email_handler_exists_and_posts_to_the_workspace_proxy():
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _scanEmail\(btn\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _scanEmail(btn) handler"
    body = fn.group(0)
    assert "/applications/" in body and "/scan-email" in body
    assert "subject" in body and "body" in body
    # Must go through the same _post/API convention as the record-outcome
    # write -- never a hand-rolled fetch call or the engine's own path.
    assert "_post(" in body
    assert "/api/post-submission" not in body


def test_scan_email_handler_is_wired_on_render():
    """The board renderer must actually attach the click listener to every
    [data-scan-submit] button -- a renderer that exists but is never wired
    would leave the button dead."""
    src = _read(TRACKER_JS)
    render_fn = re.search(r"function _renderBoard\(host, applications\) \{.*?\n\}\n", src, re.S)
    assert render_fn, "expected a _renderBoard(host, applications) function"
    body = render_fn.group(0)
    assert "data-scan-submit" in body
    assert "_scanEmail(" in body


def test_scan_email_handler_reloads_the_board_only_when_something_was_recorded():
    """A confident detection that gets recorded should refresh the board (the
    new signal/bucket must show up); a non-match or a too-thin match should
    NOT blindly reload -- it shows the plain-language result inline instead."""
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _scanEmail\(btn\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "data.recorded" in body, "expected the handler to branch on the engine's `recorded` flag"
    assert "_load(false)" in body


def test_scan_email_handler_reuses_shared_error_text_helper():
    """Failures render through the shared errText() helper (auth/timeout/
    network mapped to calm copy) -- not a raw e.message dump."""
    src = _read(TRACKER_JS)
    fn = re.search(r"async function _scanEmail\(btn\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "errText(" in fn.group(0)


# ── engine-client + proxy: the new method/route exist and reuse the guard ───


def test_engine_client_exposes_tracker_scan_email():
    """The workspace's ApplicantEngineClient carries the new tracker_scan_email
    method -- not an ad hoc inline request -- mirroring tracker_record_outcome."""
    src = _read(ENGINE_CLIENT_PY)
    assert "async def tracker_scan_email(self, application_id: str, subject: str, body: str)" in src
    assert '"/api/post-submission/applications/{application_id}/scan-email"' in src


def test_proxy_scan_email_route_reuses_the_owner_scoping_guard():
    """The new scan-email endpoint must validate the caller-supplied
    application_id against THIS request's own campaign fan-out BEFORE
    forwarding -- the exact same _owner_application_ids guard the outcome
    write uses, not a re-implemented (and possibly weaker) copy."""
    src = _read(TRACKER_ROUTES_PY)
    scan_fn = re.search(
        r'@router\.post\("/applications/\{application_id\}/scan-email"\)\s*\n\s*async def scan_email\(.*?\n    return .*?\n',
        src,
        re.S,
    )
    assert scan_fn, "expected an async scan_email(...) route handler"
    body = scan_fn.group(0)
    assert "_owner_application_ids" in body
    assert "application_id not in owned" in body
    assert "engine.tracker_scan_email(" in body


def test_proxy_scan_email_route_is_registered_under_the_tracker_prefix():
    src = _read(TRACKER_ROUTES_PY)
    assert '@router.post("/applications/{application_id}/scan-email")' in src


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_tracker_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
