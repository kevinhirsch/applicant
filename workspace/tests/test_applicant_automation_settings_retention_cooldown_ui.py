"""Regression coverage for the two new Settings > Automation knobs (dark-engine
audit items 87/88): the data-retention window (``pii_retention_days``,
``config.py`` ~line 192, default 0 = keep forever) and the duplicate-
application re-apply cooldown (``presubmit_duplicate_cooldown_days``,
``config.py`` ~line 561/567, default 30). Both were env-only with zero
Settings UI before this change; this phase adds two more cards to the
existing ``applicantAutomationSettings.js`` tab module (purely additive, no
restructuring of the existing three knobs).

Follows ``test_applicant_automation_settings_ui.py``'s convention for this
exact style of module: source-text regex assertions for the browser-only
renderer (no DOM-independent entry point cheap enough to shim here). Each
assertion below was hand-verified to go RED when the corresponding piece of
the new cards is reverted (file-copy backup restored over the edited file,
not ``git stash`` -- shared across sibling worktrees in this session), then
confirmed GREEN again after restoring.
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


# ── the two new knobs are rendered with plain-language, honest copy ────────


def test_renders_the_retention_field_with_plain_honest_language():
    body = _card_html_body()
    assert 'data-as-field="pii_retention_days"' in body
    # White-label + honesty rule: no raw env-var jargon, and the copy must
    # plainly state what "0" means (item 87's core requirement).
    assert "PII_RETENTION_DAYS" not in body
    assert "FR-CRIT-4" not in body
    assert "NFR-PRIV-1" not in body
    assert "keep forever" in body.lower()
    assert "0" in body


def test_renders_the_cooldown_field():
    body = _card_html_body()
    assert 'data-as-field="presubmit_duplicate_cooldown_days"' in body
    assert "PRESUBMIT_DUPLICATE_COOLDOWN_DAYS" not in body
    assert "re-apply" in body.lower() or "reapply" in body.lower()


def test_new_fields_use_the_same_settings_input_pattern_as_existing_knobs():
    body = _card_html_body()
    assert 'class="settings-input" type="number" min="0" step="1"' in body


# ── _readForm reads both new fields ─────────────────────────────────────


def test_read_form_captures_retention_days():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _readForm\(host\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _readForm(host) function"
    body = fn.group(0)
    assert "pii_retention_days" in body


def test_read_form_captures_cooldown_days():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _readForm\(host\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "presubmit_duplicate_cooldown_days" in body


# ── the module still talks only to the owner-scoped proxy, still exported ──


def test_module_still_talks_only_to_the_owner_scoped_setup_proxy():
    src = _read(AUTOMATION_JS)
    assert "const BASE = '/api/applicant/setup/automation';" in src


def test_module_still_exports_the_mount_function():
    src = _read(AUTOMATION_JS)
    assert "export async function mountApplicantAutomationSettings(host)" in src
    assert "window.mountApplicantAutomationSettings = mountApplicantAutomationSettings" in src


# ── syntax smoke ─────────────────────────────────────────────────────────


def test_node_check_applicant_automation_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(AUTOMATION_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
