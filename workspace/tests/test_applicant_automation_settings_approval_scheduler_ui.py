"""Regression coverage for the Settings > Automation tab's approval-timeout and
scheduler-interval fields (dark-engine audit items 86/90):
``workspace/static/js/applicantAutomationSettings.js`` gains two more cards on
top of the 82/84/85 foundation (``test_applicant_automation_settings_ui.py``)
-- no new tab, no new mechanism, just two more ``data-as-field`` inputs on the
existing standalone module.

Follows the same source-text regex convention as the foundation UI test (no
DOM-independent entry point cheap enough to shim here). Each assertion below
was hand-verified to go RED when the corresponding card / field / read-form
wiring is reverted, then confirmed GREEN again after restoring
(revert-verification per the task's definition of done, via file-copy
backups -- not ``git stash``, which is shared across worktrees in this
session).
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKSPACE_DIR = REPO_ROOT / "workspace"
AUTOMATION_JS = WORKSPACE_DIR / "static" / "js" / "applicantAutomationSettings.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _card_html_body() -> str:
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _cardHTML\(prefs\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _cardHTML(prefs) renderer"
    return fn.group(0)


def _read_form_body() -> str:
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _readForm\(host\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _readForm(host) function"
    return fn.group(0)


# ── the two new fields are rendered with plain-language labels ─────────────


def test_renders_the_approval_timeout_and_scheduler_fields():
    body = _card_html_body()
    assert 'data-as-field="approval_timeout_days"' in body
    assert 'data-as-field="approval_wait_seconds"' in body
    assert 'data-as-field="scheduler_interval_seconds"' in body


def test_no_raw_env_jargon_leaks_into_the_new_cards():
    """White-label rule: plain language, not APPROVAL_TIMEOUT_DAYS /
    APPROVAL_WAIT_SECONDS / SCHEDULER_INTERVAL_SECONDS env-key jargon, and no
    FR-/audit-item jargon in the rendered copy."""
    body = _card_html_body()
    for jargon in (
        "APPROVAL_TIMEOUT_DAYS",
        "APPROVAL_WAIT_SECONDS",
        "SCHEDULER_INTERVAL_SECONDS",
        "FR-DUR-3",
        "FR-DIG-1",
        "item 86",
        "item 90",
    ):
        assert jargon not in body, f"{jargon!r} leaked into user-facing copy"
    assert "Approval timeout" in body
    assert "How often Applicant checks for work" in body


def test_approval_timeout_card_uses_the_shared_design_system():
    body = _card_html_body()
    assert 'class="admin-card"' in body
    assert 'class="settings-input"' in body


# ── the read-form actually wires the two new fields into the PUT body ──────


def test_read_form_reads_the_approval_timeout_days_field():
    body = _read_form_body()
    assert "get('approval_timeout_days')" in body
    assert "body.approval_timeout_days" in body


def test_read_form_reads_the_approval_wait_seconds_field():
    body = _read_form_body()
    assert "get('approval_wait_seconds')" in body
    assert "body.approval_wait_seconds" in body


def test_read_form_reads_the_scheduler_interval_seconds_field():
    body = _read_form_body()
    assert "get('scheduler_interval_seconds')" in body
    assert "body.scheduler_interval_seconds" in body


def test_blank_approval_wait_seconds_is_omitted_not_sent_as_a_value():
    """A blank precise-override field must not send an empty-string/NaN value
    that would clobber the persisted override -- the field must be entirely
    absent from the PUT body when left blank."""
    body = _read_form_body()
    assert "approvalSecondsEl.value.trim() !== ''" in body


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_automation_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(AUTOMATION_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
