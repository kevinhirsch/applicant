"""Regression coverage for the accessibility-deep (05) and micro-interactions
(01) exhaustive2 audit findings implemented on the Chat/Mind/Vault/Remote
front-door surfaces only (``static/js/applicantChat.js``,
``static/js/applicantMind.js``, ``static/js/applicantVault.js``,
``static/js/applicantRemote.js``).

Follows the convention of ``test_applicant_round1_chatmind.py`` /
``test_applicant_backlog_mobileremote.py``: every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket (these modules do top-level ``document``/``fetch`` work on
import, so they are not importable under a bare ``node --input-type=module``).

Each assertion here was verified, by hand, to go red when the underlying fix
is reverted (revert the file -> rerun -> see the assertion fail -> restore)
per the batch's test-coverage DoD; the file-copy backups used for that are
NOT committed (only the source fixes + this test file are).

Findings intentionally left unfixed on these four surfaces (documented in the
session report, not re-derived here): ``styledConfirm``/``styledPrompt``
dialog semantics and the focus-trap invisible-focusables hardening (both
live in ``ui.js``, out of this pass's file scope); the shared
``loadingHTML``/``errorHTML`` live-region kit-level fix (``applicantCore.js``,
same reason); Remote's session-picker human-readable labels (needs a backend
payload change to include role/company, out of file scope); and the
iframe-focus-stranding kit fix (``ui.js``, low value / medium effort).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = JS_DIR / "applicantChat.js"
MIND_JS = JS_DIR / "applicantMind.js"
VAULT_JS = JS_DIR / "applicantVault.js"
REMOTE_JS = JS_DIR / "applicantRemote.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _balanced_braces(js: str) -> bool:
    return js.count("{") == js.count("}")


# ── brace-balance sanity (all four files) ───────────────────────────────────


def test_all_four_files_stay_brace_balanced():
    for path in (CHAT_JS, MIND_JS, VAULT_JS, REMOTE_JS):
        js = _read(path)
        assert _balanced_braces(js), f"{path.name} has unbalanced braces"


# ── Chat (applicantChat.js) ─────────────────────────────────────────────────
#
# Chat-unification pass: the Job Assistant no longer opens its own modal — it
# resolves a dedicated engine-backed session and opens it in the NATIVE chat
# surface via selectSession() (the assistant.js pattern). The modal-specific
# a11y contracts (focus trap re-init, aria-labelledby on the dialog, the
# modal's own live-region thread/composer) are therefore owned by the native
# chat plane now; what this section guards is the a11y of the pieces the Job
# Assistant still ADDS to that plane (the job-search bar, starters, create
# form) and that the retired modal really is gone.


def test_chat_no_modal_remains_native_surface_only():
    """Unification: the second, bolted-on chat modal is retired. The module
    must not build its own dialog or wire its own focus trap — the native
    chat surface (selectSession) owns all of that."""
    js = _read(CHAT_JS)
    assert "applicant-chat-modal" not in js, "the retired modal's element id resurfaced"
    assert "initModalA11y" not in js, "no modal => no local focus-trap wiring"
    assert "_ensureModalEl" not in js
    assert "selectSession(" in js, "the launcher must open the NATIVE chat surface"


def test_chat_extras_bar_has_landmark_semantics():
    """The job-search bar the Job Assistant mounts above the native thread is
    a labelled region so SR users can find/skip it."""
    js = _read(CHAT_JS)
    assert "setAttribute('role', 'region')" in js
    assert "setAttribute('aria-label', 'Job assistant controls')" in js


def test_chat_new_campaign_input_and_picker_have_accessible_names():
    """a11y-deep #66 (carried over): the inline new-campaign-name input and
    the job-search picker must not be placeholder-only."""
    js = _read(CHAT_JS)
    m = re.search(r'<input type="text" id="applicant-new-campaign"[^>]*/?>', js)
    assert m and "aria-label=" in m.group(0)
    m2 = re.search(r'<select id="applicant-campaign-pick"[^>]*>', js)
    assert m2 and "aria-label=" in m2.group(0)


def test_chat_starter_prompts_hide_once_the_conversation_starts():
    """micro-interactions #84 (carried over to the unified send path)."""
    js = _read(CHAT_JS)
    m = re.search(r"export async function sendEngineMessage\(rawText\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected sendEngineMessage's body"
    body = m.group(1)
    assert "applicant-starters" in body
    assert "style.display = 'none'" in body


def test_chat_enter_handler_guards_ime_composition():
    """micro-interactions #15 (carried over): an IME composition-commit Enter
    must not fire the create-campaign action. (The composer's own Enter
    handling belongs to the native chat now.)"""
    js = _read(CHAT_JS)
    assert "e.isComposing" in js and "e.keyCode !== 229" in js


def test_chat_pending_refresh_honours_its_seq_guard():
    """micro-interactions #93 (carried over): a slow job-search switch must
    not paint a stale pending-count over a newer one."""
    js = _read(CHAT_JS)
    m = re.search(r"async function _loadPending\(seq\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _loadPending's body"
    assert "if (seq && seq !== _renderSeq) return;" in m.group(1)


# ── Mind (applicantMind.js) ──────────────────────────────────────────────────


def test_mind_modal_named_via_labelledby_not_a_hardcoded_string():
    js = _read(MIND_JS)
    assert "aria-labelledby=\"applicant-mind-title\"" in js
    assert 'id="applicant-mind-title"' in js
    assert 'aria-label="What the assistant remembers"' not in js


def test_mind_curation_actions_remove_the_row_in_place_instead_of_full_reload():
    """micro-interactions #38: approve/deny/forget used to `await
    openApplicantMind()`, re-running all six section fetches and collapsing
    every expanded playbook row."""
    js = _read(MIND_JS)
    m = re.search(r"function _wireCurationButtons\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _wireCurationButtons's body"
    body = m.group(1)
    assert "openApplicantMind()" not in body
    assert "_removeMindRow(btn)" in body


def test_mind_forget_uses_styled_confirm_not_native_confirm():
    """micro-interactions #76."""
    js = _read(MIND_JS)
    m = re.search(r"function _wireForgetButtons\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _wireForgetButtons's body"
    body = m.group(1)
    assert "window.confirm(" not in body
    assert "await _confirm(" in body


def test_mind_skill_rows_expose_expanded_state():
    """micro-interactions #70: nothing communicated open/closed state,
    visually or to AT."""
    js = _read(MIND_JS)
    assert "_setSkillRowExpanded" in js
    assert 'aria-expanded="false"' in js
    assert "applicant-mind-skill-chevron" in js


def test_mind_distinguishes_auth_failure_from_no_model_connected():
    """micro-interactions #79: an expired session must not render the
    connect-a-model gate."""
    js = _read(MIND_JS)
    m = re.search(r"export async function openApplicantMind\(opts\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected openApplicantMind's body"
    body = m.group(1)
    assert "e.kind === 'auth'" in body
    assert "wireRetry(_body()" in body


def test_mind_uses_the_shared_spinner_kit_not_a_bare_loading_div():
    """micro-interactions #81."""
    js = _read(MIND_JS)
    assert "_body().innerHTML = loadingHTML();" in js


# ── Vault (applicantVault.js) ────────────────────────────────────────────────


def test_vault_modal_named_via_labelledby_not_a_hardcoded_string():
    js = _read(VAULT_JS)
    assert "aria-labelledby', 'applicant-vault-title'" in js
    assert 'id="applicant-vault-title"' in js
    assert "modal.setAttribute('aria-label', 'Saved sign-ins')" not in js


def test_vault_heading_hierarchy_no_longer_inverted():
    """a11y-deep #56: section headings must not outrank the dialog's own h4
    title (previously h3 nested under h4)."""
    js = _read(VAULT_JS)
    assert "<h3" not in js
    assert js.count("<h5") == 4


def test_vault_credential_fields_have_real_labels_not_placeholder_only():
    """a11y-deep #50: the Google/default account credential fields were the
    most sensitive fields in the product with no label at all."""
    js = _read(VAULT_JS)
    assert 'for="applicant-vault-google-secret"' in js or (
        "Google password" in js and "<label" in js.split("Google password")[0][-200:]
    )
    assert js.count("<label") >= 5


def test_vault_password_fields_all_get_a_show_hide_toggle():
    """micro-interactions #19."""
    js = _read(VAULT_JS)
    # 3 password fields carry the toggle button markup, plus the one
    # querySelectorAll('.applicant-vault-toggle-secret') that wires them.
    assert js.count("applicant-vault-toggle-secret") == 4
    assert js.count('class="applicant-vault-toggle-secret cal-btn"') == 3
    assert "_wireSecretToggles" in js
    assert "aria-pressed" in js


def test_vault_credential_forms_submit_on_enter():
    """micro-interactions #18/#15."""
    js = _read(VAULT_JS)
    assert "_wireEnterToSave" in js
    m = re.search(r"function _wireEnterToSave\(modal\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m
    body = m.group(1)
    assert "e.isComposing" in body
    assert "e.keyCode === 229" in body


def test_vault_refresh_button_shows_a_busy_state():
    """micro-interactions #35."""
    js = _read(VAULT_JS)
    m = re.search(r"async function _onRefreshTenants\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _onRefreshTenants's body"
    body = m.group(1)
    assert "btn.disabled = true" in body
    assert "Refreshing" in body


def test_vault_tenant_list_has_list_semantics():
    """a11y-deep #58: row collections were div soup with no list semantics."""
    js = _read(VAULT_JS)
    assert 'id="applicant-vault-list" role="list"' in js
    assert 'role="listitem"' in js


def test_vault_no_more_console_error_for_soft_degrades():
    """micro-interactions #78: downgrade routine soft-degrade logging so it
    doesn't bury real errors."""
    js = _read(VAULT_JS)
    assert "console.error(" not in js
    assert js.count("console.debug(") >= 5


# ── Remote (applicantRemote.js) ──────────────────────────────────────────────


def test_remote_modal_named_via_labelledby_not_a_hardcoded_string():
    js = _read(REMOTE_JS)
    assert "aria-labelledby', 'applicant-remote-title'" in js
    assert 'id="applicant-remote-title"' in js
    assert "modal.setAttribute('aria-label', 'Live application session')" not in js


def test_remote_heading_hierarchy_no_longer_inverted():
    """a11y-deep #56."""
    js = _read(REMOTE_JS)
    assert "<h3" not in js
    assert js.count("<h5") == 4


def test_remote_session_picker_has_an_accessible_name():
    """a11y-deep #67: title is not a reliable accessible name."""
    js = _read(REMOTE_JS)
    m = re.search(r'<select id="applicant-remote-picker"[^>]*>', js, re.DOTALL)
    assert m
    assert 'aria-label="Choose which live session to watch"' in m.group(0)


def test_remote_has_a_phase_live_region_and_announces_transitions():
    """a11y-deep #22: the phase arc used to be visible-pixels-only."""
    js = _read(REMOTE_JS)
    m = re.search(r'<div id="applicant-remote-phase"[^>]*>', js)
    assert m
    assert 'role="status"' in m.group(0)
    assert 'aria-live="polite"' in m.group(0)
    assert "_announcePhase" in js
    # Called from more than just its own definition site.
    assert js.count("_announcePhase(") >= 4


def test_remote_finish_buttons_lock_after_a_successful_submit():
    """micro-interactions #7: after success the "Finish the application"
    card used to stay fully active — a second tap on Authorize was possible."""
    js = _read(REMOTE_JS)
    assert "_markFinishTerminal" in js
    assert "_clearFinishTerminal" in js
    m = re.search(r"async function _onSubmitSelf\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m
    assert "_markFinishTerminal(" in m.group(1)
    m2 = re.search(r"async function _onAuthorizeFinish\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m2
    assert "_markFinishTerminal(" in m2.group(1)
    # A newly-selected session must never inherit a stale terminal lock.
    m3 = re.search(r"function _setActiveSession\(session\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m3
    assert "_clearFinishTerminal()" in m3.group(1)


def test_remote_submit_self_confirm_reuses_the_shared_message_builder():
    """micro-interactions #87: the inline confirm copy had drifted from the
    exported builder Portal shares."""
    js = _read(REMOTE_JS)
    m = re.search(r"async function _onSubmitSelf\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m
    body = m.group(1)
    assert "_submitSelfConfirmMessage(_activeSession)" in body
    assert "Mark this application as submitted by you? Do this after" not in body


def test_remote_refresh_sessions_button_shows_a_busy_state():
    """micro-interactions #35."""
    js = _read(REMOTE_JS)
    assert "_onRefreshSessions" in js
    m = re.search(r"async function _onRefreshSessions\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m
    assert "_setButtonBusy(btn, 'Refreshing" in m.group(1)


def test_remote_top_toolbar_uses_one_button_family_not_a_mix():
    """micro-interactions #86: Take control / Open in new tab / Refresh
    sessions used to mix .cal-btn with .memory-toolbar-btn in the same row."""
    js = _read(REMOTE_JS)
    m = re.search(
        r'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">\s*'
        r'<button id="applicant-remote-takeover"[^<]*</button>\s*'
        r'<button id="applicant-remote-open-tab"[^<]*</button>\s*'
        r'<button id="applicant-remote-refresh"[^<]*</button>',
        js,
    )
    assert m, "expected the top toolbar row"
    row = m.group(0)
    assert row.count('class="cal-btn"') == 3
    assert "memory-toolbar-btn" not in row


def test_remote_no_more_console_error_for_soft_degrades():
    """micro-interactions #78."""
    js = _read(REMOTE_JS)
    assert "console.error(" not in js
    assert js.count("console.debug(") >= 6


def test_remote_desktop_toggle_exposes_pressed_state():
    js = _read(REMOTE_JS)
    m = re.search(r"function _renderDesktopAssist\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m
    assert "aria-pressed" in m.group(1)
