"""H3 (full-fidelity review) — front-door reachability pins.

Before every submit the owner must be able to see the LITERAL payload — every
answer verbatim, the exact documents, the posting — not a summary. The engine
records it at the review stop-boundary (``stage: "reviewed"``); these tests pin
the front-door chain that makes it reachable at each place a submit can be
authorized:

* the live-session modal already had "Review exactly what will be sent" — its
  renderer now states the capture stage honestly and is EXPORTED as the single
  shared implementation (``fetchSubmissionSnapshot``/``renderSubmissionSnapshot``);
* the Portal final-approval card ("Let me submit it" lives there) carries a
  "See exactly what will be sent" panel wired to that SAME seam;
* the Today final-approval card (the other authorize path) does too;
* neither surface grows a second, summarized renderer of its own.

Source-composition tests in the established style (they read the shipped JS):
renaming the seam or dropping the affordance turns these red by design.
"""

from __future__ import annotations

import re
from pathlib import Path

JS_DIR = Path(__file__).resolve().parents[1] / "static" / "js"
ROUTES_DIR = Path(__file__).resolve().parents[1] / "routes"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slice_fn(src: str, header: str) -> str:
    """The source from ``header`` to the next top-level ``function`` (composition
    slice, mirroring the sibling copy tests)."""
    start = src.index(header)
    nxt = src.find("\nfunction ", start + 1)
    return src[start:nxt if nxt != -1 else len(src)]


# --- the shared renderer seam (one implementation, exported) -----------------


def test_remote_exports_the_single_snapshot_seam():
    js = _read(JS_DIR / "applicantRemote.js")
    assert "export function fetchSubmissionSnapshot(applicationId)" in js
    assert "export function renderSubmissionSnapshot(data)" in js
    # The export delegates to the SAME private renderer the modal panel uses.
    assert "return _renderSnapshot(data || {});" in js
    # And both land on the module object other lanes consume.
    assert re.search(r"const applicantRemoteModule = \{[\s\S]*?fetchSubmissionSnapshot,", js)
    assert re.search(r"const applicantRemoteModule = \{[\s\S]*?renderSubmissionSnapshot,", js)


def test_remote_renderer_states_the_capture_stage_honestly():
    js = _read(JS_DIR / "applicantRemote.js")
    fn = _slice_fn(js, "function _renderSnapshot(data) {")
    assert "data.stage === 'reviewed'" in fn
    assert "exactly what will be sent" in fn
    assert "data.stage === 'submitted'" in fn
    assert "exactly what was sent" in fn


# --- the Portal final-approval card (authorize path #1) ----------------------


def test_portal_final_card_carries_the_literal_payload_affordance():
    js = _read(JS_DIR / "applicantPortal.js")
    fn = _slice_fn(js, "function _renderFinal(item) {")
    assert "See exactly what will be sent" in fn
    assert "applicant-portal-final-payload-toggle" in fn
    assert "applicant-portal-final-payload" in fn


def test_portal_payload_panel_reuses_the_remote_seam_not_a_second_renderer():
    js = _read(JS_DIR / "applicantPortal.js")
    assert "remoteModule.fetchSubmissionSnapshot(appId)" in js
    assert "remoteModule.renderSubmissionSnapshot(" in js
    # No bespoke sibling renderer sneaks in.
    assert "function _renderSnapshot" not in js


def test_portal_payload_toggle_is_wired():
    js = _read(JS_DIR / "applicantPortal.js")
    assert "querySelectorAll('.applicant-portal-final-payload-toggle')" in js
    assert "_loadFinalPayload(" in js


# --- the Today final-approval card (authorize path #2) -----------------------


def test_today_final_card_carries_the_literal_payload_affordance():
    js = _read(JS_DIR / "applicantToday.js")
    fn = _slice_fn(js, "function _renderFinal(wrap, item) {")
    assert "See exactly what will be sent" in fn
    assert 'data-role="payload-toggle"' in fn
    assert 'data-role="payload"' in fn
    assert "remoteModule.fetchSubmissionSnapshot(appId)" in fn
    assert "remoteModule.renderSubmissionSnapshot(" in fn


# --- the proxy: owner-gated, stage passed through -----------------------------


def test_snapshot_proxy_is_owner_gated_and_passes_stage():
    src = _read(ROUTES_DIR / "applicant_snapshot_routes.py")
    assert "require_engine_owner" in src
    assert "from src.auth_helpers import require_engine_owner" in src
    # No lingering plain require_user import (the weaker gate).
    assert "import require_user" not in src
    assert '"stage"' in src
