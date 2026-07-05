"""Regression coverage for exhaustive-audit-pass lens 04 (failure paths)
findings #56 (``applicantVault.js``) and #61 (``applicantDebug.js``).

Follows the convention of ``test_applicant_debug_help_lens12.py`` /
``test_applicant_chatstream_guard_lens04.py``: every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket. Each assertion below was hand-verified to go red when the
underlying fix is reverted (``cp`` the file to a backup, revert the change,
rerun to see a real ``AssertionError``, then restore from the backup) per the
project's revert-verify convention.

Findings covered:
  * #56 — a 401 from any vault call (session expired) just failed generically
    (a bare toast with the raw error message, or — for background calls —
    nothing at all) with no way back in. ``applicantVault.js`` now detects a
    401 specifically (``_isSessionExpired``, narrower than the shared
    ``.kind === 'auth'`` bucket which also covers a 403 forbidden) and
    surfaces a clear "session expired" affordance with a one-click way to
    re-authenticate (a toast action button and, for the main list view, an
    inline "Sign in again" button), instead of the generic failure path.
  * #61 — the Debug "Run now" control fired with no progress indication
    beyond a plain text swap and no way to stop it. It now shows a real busy
    state (the design system's existing, previously-unused ``.btn-spinner``
    inline spinner + ``aria-busy``) and reveals a Cancel button wired to a
    real ``AbortController`` that can interrupt the in-flight request.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
VAULT_JS = JS_DIR / "applicantVault.js"
DEBUG_JS = JS_DIR / "applicantDebug.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #56: applicantVault.js re-auth-on-401 affordance ────────────────────────


def test_vault_detects_401_specifically_not_the_shared_auth_kind():
    """A 401 must be distinguished from a 403 (a different, non-expiry case
    that the shared _fetchJSON error also tags .kind === 'auth') by checking
    .status directly, so only a genuine session expiry triggers re-auth."""
    js = _read(VAULT_JS)
    assert re.search(r"function _isSessionExpired\(err\)\s*\{", js), (
        "expected a dedicated _isSessionExpired(err) helper in applicantVault.js"
    )
    body = js[js.index("function _isSessionExpired(err)") :][:200]
    assert "err.status === 401" in body, (
        "expected _isSessionExpired to check err.status === 401, not the "
        "broader .kind === 'auth' bucket (which also covers 403)"
    )


def test_vault_offers_reauth_with_an_actionable_sign_in_path():
    """The re-auth affordance must be more than a generic error string — it
    needs a concrete way to act (a toast action button that navigates to
    /login), not just a message."""
    js = _read(VAULT_JS)
    assert re.search(r"function _offerReauth\(\s*\)\s*\{", js), (
        "expected an _offerReauth() helper in applicantVault.js"
    )
    body = js[js.index("function _offerReauth(") :][:700]
    assert "session expired" in body.lower()
    assert "/login" in body, "expected the re-auth affordance to link to /login"
    assert "onAction" in body or "window.location.href" in body, (
        "expected the re-auth affordance to be actionable (a toast action "
        "button or a direct redirect), not just a passive message"
    )


def test_vault_load_tenants_renders_inline_reauth_button_on_401():
    """The main "Saved sign-ins" list — the view most likely visible the
    moment a stale session surfaces — must show a persistent in-modal
    "Sign in again" button on a 401, not just a transient toast that could be
    missed."""
    js = _read(VAULT_JS)
    idx = js.index("async function _loadTenants()")
    fn_body = js[idx : idx + 2200]
    assert "_isSessionExpired(e)" in fn_body, (
        "expected _loadTenants's catch block to check for a session-expired "
        "error specifically"
    )
    assert "_authExpiredHTML()" in fn_body or "applicant-vault-reauth" in fn_body, (
        "expected _loadTenants to render the dedicated re-auth affordance "
        "(not the generic errorHTML retry card) when the session has expired"
    )


def test_vault_reauth_button_markup_has_a_click_target():
    js = _read(VAULT_JS)
    assert "id=\"applicant-vault-reauth\"" in js, (
        "expected a concrete #applicant-vault-reauth button in the re-auth markup"
    )
    assert "_wireReauthButton" in js, (
        "expected the re-auth button to be wired to actually navigate on click"
    )


def test_vault_write_actions_route_401_through_the_reauth_handler():
    """Save / save-account / rotate-key / capture — every vault write action's
    catch block — must route a 401 through the shared re-auth handler instead
    of the old bare 'could not save' toast."""
    js = _read(VAULT_JS)
    assert js.count("_handleActionErr(e,") >= 4, (
        "expected the vault's write-action catch blocks (save, save-account, "
        "rotate-key, capture) to all route through _handleActionErr so a 401 "
        "gets the re-auth affordance instead of a generic failure toast"
    )
    # The old blanket pattern must not still be present verbatim for these
    # call sites (it would mean a 401 falls through to a generic message).
    assert "_toast(e.message || 'Could not save the sign-in')" not in js


def test_vault_account_status_load_offers_reauth_instead_of_swallowing_401():
    """_loadAccountStatus's catch used to silently swallow every error
    (including a 401) with no signal to the user at all."""
    js = _read(VAULT_JS)
    idx = js.index("async function _loadAccountStatus()")
    fn_body = js[idx : idx + 500]
    assert "_isSessionExpired(e)" in fn_body and "_offerReauth()" in fn_body, (
        "expected _loadAccountStatus's catch to at least offer re-auth on a "
        "401 instead of swallowing it with no user-visible signal"
    )


# ── #61: applicantDebug.js Run now progress + cancel ────────────────────────


def test_run_now_shows_a_real_busy_state_with_a_visible_spinner():
    js = _read(DEBUG_JS)
    idx = js.index("if (runNowBtn) runNowBtn.addEventListener('click'")
    handler = js[idx : idx + 2200]
    assert "btn-spinner" in handler, (
        "expected Run now's busy state to include the design system's "
        "inline .btn-spinner, not just a plain text swap"
    )
    assert "aria-busy" in handler, (
        "expected the busy button to carry aria-busy for assistive tech"
    )


def test_run_now_reveals_a_cancel_control_wired_to_a_real_abort():
    js = _read(DEBUG_JS)
    assert 'id="applicant-run-cancel"' in js, (
        "expected a concrete #applicant-run-cancel button in the Run controls markup"
    )
    idx = js.index("if (runCancelBtn) runCancelBtn.addEventListener('click'")
    handler = js[idx : idx + 300]
    assert "_runAbortController.abort()" in handler, (
        "expected the Cancel button to call .abort() on a real AbortController, "
        "not just hide the busy state client-side"
    )


def test_run_now_uses_an_abortcontroller_signal_on_the_actual_request():
    js = _read(DEBUG_JS)
    idx = js.index("if (runNowBtn) runNowBtn.addEventListener('click'")
    handler = js[idx : idx + 2200]
    assert "new AbortController()" in handler
    assert "signal: controller.signal" in handler, (
        "expected the Run now fetch to actually be wired to the "
        "AbortController's signal so Cancel can interrupt it"
    )


def test_run_now_distinguishes_user_cancel_from_a_generic_failure():
    """A cancelled run must read as 'cancelled', not a scary generic error —
    _fetchJSON collapses every AbortError into the same shape, so the catch
    block must check the controller's own .aborted flag to tell them apart."""
    js = _read(DEBUG_JS)
    idx = js.index("if (runNowBtn) runNowBtn.addEventListener('click'")
    handler = js[idx : idx + 2200]
    assert "controller.signal.aborted" in handler
    assert "Run cancelled" in handler


def test_run_now_restores_idle_state_and_clears_the_controller_when_done():
    js = _read(DEBUG_JS)
    idx = js.index("if (runNowBtn) runNowBtn.addEventListener('click'")
    handler = js[idx : idx + 2400]
    finally_idx = handler.index("} finally {")
    finally_block = handler[finally_idx : finally_idx + 400]
    assert "_runAbortController = null" in finally_block
    assert "runCancelBtn.style.display = 'none'" in finally_block, (
        "expected the Cancel button to be hidden again once the run settles"
    )


def test_rerender_restores_busy_ui_for_a_run_already_in_flight():
    """Switching tabs and back mid-run must not show a stale idle 'Run now'
    button while a request is still outstanding."""
    js = _read(DEBUG_JS)
    idx = js.index("async function _renderRun()")
    fn_body = js[idx : idx + 2600]
    assert "runInFlight" in fn_body and "_runAbortController" in fn_body, (
        "expected _renderRun to reflect an in-flight run's busy/Cancel state "
        "on re-render instead of always starting from idle"
    )
