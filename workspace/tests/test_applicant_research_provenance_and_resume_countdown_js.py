"""Static-source assertions (no browser) for the JS halves of dark-engine audit
items #76 (research provenance on the redline review card) and #78 (resume-
backoff countdown on Portal toasts) / #77 (notification-ladder line on Portal
cards).

Mirrors ``test_applicant_backlog_jdmatch.py``'s convention: read the actual
static file content and regex-match the function bodies + call sites, so a
later refactor that silently drops the fetch/wiring is caught without a full
browser/DOM harness.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"
PORTAL_JS = JS_DIR / "applicantPortal.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# --- #76: documentLibrary.js --------------------------------------------------


def test_research_provenance_helper_fetches_the_dedicated_proxy_endpoint():
    src = _read(DOCLIB_JS)
    m = re.search(
        r"async function _loadResearchProvenance\(appId, container\) \{(.*?)\n    \}\n",
        src,
        re.S,
    )
    assert m, "expected to find _loadResearchProvenance()"
    body = m.group(1)
    assert "research-provenance/" in body
    assert "_APPLICANT_BASE" in body
    assert "data.used" in body


def test_render_applicant_review_wires_the_research_provenance_slot():
    src = _read(DOCLIB_JS)
    m = re.search(
        r"function _renderApplicantReview\(item, appId, panel, session, card, results\) \{(.*?)\n      // Redline:",
        src,
        re.S,
    )
    assert m, "expected to find _renderApplicantReview() ahead of the redline block"
    body = m.group(1)
    assert "_loadResearchProvenance(appId, researchSlot)" in body


# --- #78: applicantPortal.js resume-backoff countdown -------------------------


def test_resume_countdown_helper_fetches_the_dedicated_proxy_endpoint():
    src = _read(PORTAL_JS)
    m = re.search(
        r"async function _resumeCountdownSuffix\(appId\) \{(.*?)\n\}\n",
        src,
        re.S,
    )
    assert m, "expected to find _resumeCountdownSuffix()"
    body = m.group(1)
    assert "/resume-status" in body
    assert "next_retry_at" in body


def test_send_answer_and_save_missing_use_the_resume_countdown():
    src = _read(PORTAL_JS)
    assert "_toast(`Sent${await _resumeCountdownSuffix(appId)}`)" in src
    assert "_toast(`Saved${await _resumeCountdownSuffix(appId)}`)" in src
    # Both buttons must actually carry the application id the countdown reads.
    assert "applicant-portal-send-answer" in src
    assert 'data-application-id="${esc(_appId(item))}"' in src


# --- #77: applicantPortal.js notification-ladder line -------------------------


def test_ladder_line_helper_reads_the_engines_notification_ladder_field():
    src = _read(PORTAL_JS)
    m = re.search(r"function _ladderLine\(item\) \{(.*?)\n\}\n", src, re.S)
    assert m, "expected to find _ladderLine()"
    body = m.group(1)
    assert "item.notification_ladder" in body
    assert "next_channel" in body
    assert "quiet_hours_held" in body


def test_row_shell_renders_the_ladder_line():
    src = _read(PORTAL_JS)
    m = re.search(r"function _rowShell\(item, inner\) \{(.*?)\n\}\n", src, re.S)
    assert m, "expected to find _rowShell()"
    body = m.group(1)
    assert "_ladderLine(item)" in body
