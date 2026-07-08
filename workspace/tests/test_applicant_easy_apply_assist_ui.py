"""P2-14 -- Easy Apply: assisted mode -- front-door UI regression tests.

Pins the digest row's new "Assisted apply" action (gated on the SAME
server-computed ``row.easy_apply`` flag P1-11 already ships) and the
consent-screen + assisted-mode-brief modal it opens
(``emailLibrary/easyApplyAssist.js``): the stop-boundary consent copy states
what the product WILL and will NEVER do, and the brief only ever opens
elsewhere (a new tab, the Documents library) -- it never submits anything
itself.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

_WORKSPACE = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_DIGEST_JS = _WORKSPACE / "static" / "js" / "emailLibrary" / "applicantDigest.js"
_ASSIST_JS = _WORKSPACE / "static" / "js" / "emailLibrary" / "easyApplyAssist.js"

_HAS_NODE = shutil.which("node") is not None


def _digest_src() -> str:
    return _DIGEST_JS.read_text(encoding="utf-8")


def _assist_src() -> str:
    return _ASSIST_JS.read_text(encoding="utf-8")


# ── digest row: the "Assisted apply" action ─────────────────────────────────


def test_digest_row_offers_assisted_apply_gated_on_easy_apply_and_posting_id():
    src = _digest_src()
    assert re.search(r"if\s*\(\s*row\.easy_apply\s*&&\s*row\.posting_id\s*\)", src), (
        "the Assisted-apply button must be gated on the server-computed "
        "row.easy_apply flag AND a resolvable posting id"
    )
    assert "applicant-digest-easy-apply-assist" in src
    assert "'Assisted apply" in src or ">Assisted apply" in src or "Assisted apply" in src


def test_digest_row_imports_and_calls_the_assist_entry_point():
    src = _digest_src()
    assert "showEasyApplyAssist" in src
    assert "from './easyApplyAssist.js'" in src
    assert re.search(r"showEasyApplyAssist\(getCampaignId\(\),\s*row\)", src)


def test_assist_button_is_disabled_while_the_fetch_is_in_flight():
    """Mirrors _onAlignment's busy pattern (CodeRabbit, PR #769): disable +
    label swap before the await, restore in finally -- a double-click can't
    stack two modals."""
    src = _digest_src()
    m = re.search(
        r"applicant-digest-easy-apply-assist[\s\S]*?actions\.appendChild\(assist\)", src
    )
    assert m, "assist button wiring not found"
    body = m.group(0)
    assert "assist.disabled = true" in body
    assert re.search(r"await showEasyApplyAssist\(getCampaignId\(\),\s*row\)", body)
    assert "finally" in body
    assert "assist.disabled = false" in body


# ── consent screen: a real stop-boundary, not decoration ───────────────────


#: The next top-level declaration, whatever form it takes (``function``,
#: ``async function``, or ``export ... function``) -- anchors a slice on a real
#: function boundary instead of any later occurrence of the substring
#: "function" (which could legitimately appear inside a function's own body/
#: comments and silently mis-scope the slice; mirrors the P1-11 chip test's
#: same anchoring fix).
_NEXT_FN = r"(?=^(?:export\s+)?(?:async\s+)?function\s)"


def test_consent_screen_states_what_it_will_and_will_never_do():
    src = _assist_src()
    assert "_showConsentScreen" in src
    m = re.search(r"function _showConsentScreen[\s\S]*?" + _NEXT_FN, src, re.M)
    assert m, "_showConsentScreen definition not found"
    body = m.group(0)
    assert "never" in body.lower()
    assert "log into the job board" in body or "log into" in body
    assert "submit an application" in body or "submit" in body
    assert "EEO" in body
    assert "work-authorization" in body


def test_consent_acceptance_is_recorded_server_side_before_the_brief_loads():
    src = _assist_src()
    m = re.search(r"function _showConsentScreen[\s\S]*?" + _NEXT_FN, src, re.M)
    assert m
    body = m.group(0)
    # The POST happens before onAccept() -- consent is recorded server-side,
    # never assumed client-side.
    assert re.search(
        r"await _fetchJSON\(`\$\{API_BASE\}/api/applicant/easy-apply/consent`,\s*\{\s*method:\s*'POST'\s*\}\)",
        body,
    )
    assert "await onAccept()" in body


def test_entry_point_checks_server_recorded_consent_not_a_local_flag():
    src = _assist_src()
    m = re.search(r"export async function showEasyApplyAssist[\s\S]*?(?=^export default)", src, re.M)
    assert m, "showEasyApplyAssist definition not found"
    body = m.group(0)
    # Never a client-side/localStorage flag deciding whether consent was given.
    assert "localStorage" not in body
    assert "/api/applicant/easy-apply/consent" in body
    assert "consent.given" in body


def test_stale_responses_never_clobber_a_newer_flow():
    """Staleness guard (CodeRabbit, PR #769): each showEasyApplyAssist call
    claims a module-level request token and every await bails when
    superseded, so posting A's late response can't clobber posting B's
    modal."""
    src = _assist_src()
    assert "let _activeRequestId = 0" in src
    m = re.search(r"export async function showEasyApplyAssist[\s\S]*?(?=^export default)", src, re.M)
    assert m
    body = m.group(0)
    assert "const requestId = ++_activeRequestId" in body
    assert "requestId !== _activeRequestId" in body
    # The brief loader threads the token through and re-checks after ITS await.
    lm = re.search(r"async function _loadAndShowBrief[\s\S]*?" + _NEXT_FN, src, re.M)
    assert lm, "_loadAndShowBrief definition not found"
    assert "requestId !== _activeRequestId" in lm.group(0)


# ── assisted-mode brief: opens elsewhere, never submits ─────────────────────


def test_brief_never_wires_a_submit_action():
    src = _assist_src()
    m = re.search(r"function _showBrief[\s\S]*?" + _NEXT_FN, src, re.M)
    assert m, "_showBrief definition not found"
    body = m.group(0)
    assert "submit" not in body.lower()
    # The posting link only ever opens in a new tab (never same-window nav /
    # form action), and only for a real http(s) URL.
    assert "target=\"_blank\"" in body or "target='_blank'" in body
    assert "isWebUrl" in body


def test_brief_hands_off_to_the_existing_documents_library_not_a_new_picker():
    src = _assist_src()
    assert "_openDocuments" in src
    assert "tool-library-btn" in src
    assert "rail-archive" in src


# ── syntax (no bundler — node --check is the only front-end gate) ──────────


@pytest.mark.skipif(not _HAS_NODE, reason="node is not installed")
@pytest.mark.parametrize("path", [_DIGEST_JS, _ASSIST_JS])
def test_touched_js_parses(path):
    subprocess.run(["node", "--check", str(path)], check=True)
