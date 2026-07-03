"""Regression coverage for the new Settings > Automation tab (dark-engine audit
items 82/84/85): the workspace Settings surface previously mounted only four
wizard renderers (channels/sandbox/fonts/update) plus the campaign and
model-ladder tabs -- there was no generic engine-preferences tab
(``docs/design/audits/exhaustive2/08_engine_dark_matrix.md`` §B8).

This phase wires the full chain:

  * ``workspace/static/js/applicantAutomationSettings.js`` -- the new
    STANDALONE tab module (mirrors ``applicantCampaignSettings.js`` /
    ``applicantModelLadder.js``'s shape), mounted lazily by settings.js.
  * ``workspace/static/js/settings.js`` -- the new tab is injected into the
    Settings modal's nav/panels at init time (no static markup exists in
    ``static/index.html`` for this phase; that file is outside this task's
    file lane) and wired the same way the Campaign/AI-tab modules are.

Follows the ``test_applicant_campaign_clone_ui.py`` convention for this exact
style of module: source-text regex assertions for the browser-only renderer (no
DOM-independent entry point cheap enough to shim here). Each assertion below was
hand-verified to go RED when the corresponding piece of the tab is reverted
(dropping the tab injection, un-wiring the mount call, dropping the save
handler / PUT call), then confirmed GREEN again after restoring.
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
SETTINGS_JS = WORKSPACE_DIR / "static" / "js" / "settings.js"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── applicantAutomationSettings.js: the module shape ────────────────────────


def test_module_exports_a_mount_function():
    src = _read(AUTOMATION_JS)
    assert "export async function mountApplicantAutomationSettings(host)" in src


def test_module_is_exposed_on_window_for_lazy_mounting():
    """settings.js mounts tab modules via window.mountApplicant*, the same
    convention as mountApplicantCampaignSettings / mountApplicantModelLadder."""
    src = _read(AUTOMATION_JS)
    assert "window.mountApplicantAutomationSettings = mountApplicantAutomationSettings" in src


def test_module_talks_only_to_the_owner_scoped_setup_proxy():
    src = _read(AUTOMATION_JS)
    assert "const BASE = '/api/applicant/setup/automation';" in src
    # Never the bare engine path -- always through the front-door proxy.
    assert "/api/setup/automation" not in src.replace("/api/applicant/setup/automation", "")


def test_module_reuses_the_shared_core_helpers_not_hand_rolled_fetch():
    """CLAUDE.md principle #1: lift-and-shift the established _fetchJSON/_put/
    _toast helpers (applicantCore.js), same as applicantCampaignSettings.js."""
    src = _read(AUTOMATION_JS)
    assert "from './applicantCore.js'" in src
    assert "_fetchJSON" in src
    assert "_put" in src
    assert "_toast" in src


def test_renders_all_three_knobs_with_plain_language_labels():
    """White-label rule: plain language, not the ALLOW_AUTOMATED_ACCOUNTS /
    EGRESS_TIMEZONE / PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY env-key jargon."""
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _cardHTML\(prefs\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _cardHTML(prefs) renderer"
    body = fn.group(0)
    assert 'data-as-field="egress_timezone"' in body
    assert 'data-as-field="egress_locale"' in body
    assert 'data-as-field="allow_automated_accounts"' in body
    assert 'data-as-field="presubmit_max_apps_per_company_per_day"' in body
    # No raw env-var jargon leaks into the rendered copy.
    for jargon in ("EGRESS_TIMEZONE", "EGRESS_LOCALE", "ALLOW_AUTOMATED_ACCOUNTS",
                    "PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY", "FR-STEALTH", "ADR-0004"):
        assert jargon not in body, f"{jargon!r} leaked into user-facing copy"
    assert "Let Applicant create accounts on job sites automatically" in body


def test_account_creation_toggle_reuses_the_admin_switch_design_system():
    """CLAUDE.md principle #4: reuse .admin-switch/.admin-slider (as the
    Teacher Model / Vision toggles already do), not a hand-rolled checkbox."""
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _cardHTML\(prefs\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'class="admin-switch"' in body
    assert 'class="admin-slider"' in body


def test_save_button_reuses_the_shared_button_classes():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _cardHTML\(prefs\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert 'id="as-save"' in body
    assert 'class="cal-btn cal-btn-primary"' in body


def test_save_handler_puts_the_form_values_to_the_proxy():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"async function _save\(\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _save() handler"
    body = fn.group(0)
    assert "_put(BASE" in body


def test_save_button_click_is_wired_to_the_save_handler():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"function _wire\(host\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a _wire(host) function"
    body = fn.group(0)
    assert "'#as-save'" in body
    assert "_save" in body


def test_load_reads_from_the_same_proxy_base():
    src = _read(AUTOMATION_JS)
    fn = re.search(r"async function _load\(\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an async _load() function"
    body = fn.group(0)
    assert "_fetchJSON(BASE)" in body


# ── settings.js: the tab is actually wired into the Settings modal ─────────


def test_settings_js_injects_an_automation_nav_tab():
    src = _read(SETTINGS_JS)
    assert "function injectAutomationTab()" in src
    assert 'dataset.settingsTab = \'automation\';' in src


def test_injected_tab_label_does_not_collide_with_the_existing_sandbox_tab():
    """The existing 'sandbox' tab is already labelled 'Automation' in the
    sidebar (it hosts the automation-SANDBOX config). This new, broader
    engine-preferences tab must use a visibly distinct label so the sidebar
    never shows two entries that both just say 'Automation'."""
    src = _read(SETTINGS_JS)
    fn = re.search(r"function injectAutomationTab\(\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "Automation Preferences" in body


def test_injected_tab_is_admin_gated_like_sandbox_and_update():
    src = _read(SETTINGS_JS)
    fn = re.search(r"function injectAutomationTab\(\) \{.*?\n\}\n", src, re.S)
    assert fn
    body = fn.group(0)
    assert "'settings-nav-item admin-only'" in body


def test_injection_runs_before_tab_click_handlers_are_bound():
    """injectAutomationTab() must run before initTabs() -- initTabs() binds
    click listeners onto whatever [data-settings-tab] elements exist in the
    DOM at that moment via querySelectorAll, so injecting after it would mean
    the new button never gets a click handler."""
    src = _read(SETTINGS_JS)
    fn = re.search(r"function initAll\(\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected an initAll() function"
    body = fn.group(0)
    inject_idx = body.index("injectAutomationTab()")
    tabs_idx = body.index("initTabs()")
    assert inject_idx < tabs_idx


def test_automation_tab_mount_is_wired_in_mount_relocated_setup_step():
    src = _read(SETTINGS_JS)
    fn = re.search(r"function mountRelocatedSetupStep\(tab\) \{.*?\n\}\n", src, re.S)
    assert fn, "expected a mountRelocatedSetupStep(tab) function"
    body = fn.group(0)
    assert "tab === 'automation'" in body
    assert "'ao-settings-automation'" in body
    assert "window.mountApplicantAutomationSettings" in body


def test_automation_panel_host_id_matches_the_module_mount_target():
    """The dynamically-injected panel's host div id must be the SAME id
    mountRelocatedSetupStep looks up, or the module renders into a detached
    element the user never sees."""
    src = _read(SETTINGS_JS)
    inject_fn = re.search(r"function injectAutomationTab\(\) \{.*?\n\}\n", src, re.S)
    mount_fn = re.search(r"function mountRelocatedSetupStep\(tab\) \{.*?\n\}\n", src, re.S)
    assert inject_fn and mount_fn
    assert 'id="ao-settings-automation"' in inject_fn.group(0)
    assert "'ao-settings-automation'" in mount_fn.group(0)


# ── syntax smoke ─────────────────────────────────────────────────────────────


def test_node_check_applicant_automation_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(AUTOMATION_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


def test_node_check_settings_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(SETTINGS_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
