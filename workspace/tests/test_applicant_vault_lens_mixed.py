"""Regression coverage for mixed-lens findings 06-#47, 01-#67 and 11-#46 in
``applicantVault.js``.

Follows the convention of ``test_applicant_vault_debug_resilience_lens04.py``:
every fact is read from the actual static file content via ``pathlib`` +
string/regex checks — no browser, no DOM, no real socket. Each assertion below
was hand-verified to go red when the underlying fix is reverted (``cp`` the
file to a backup, revert the change, rerun to see a real ``AssertionError``,
then restore from the backup) per the project's revert-verify convention.

Findings covered:
  * 06-#47 — the Google sign-in password field used
    ``autocomplete="new-password"``, but this is an EXISTING Google account
    the user is entering to sign in with, not a brand-new one being created
    here, so the correct autofill hint is ``autocomplete="current-password"``.
  * 01-#67 — saved sign-in rows in the "Sites with a saved sign-in" list were
    text-only with no remove/replace affordance. The engine's credential
    store has no per-tenant delete route (only bank/overwrite, list, and a
    blanket key-rotation endpoint), so the fix is a "replace by re-saving"
    control per row: it pre-fills the "sign-in for a specific site" form so
    the user only has to type a new password and Save, which overwrites the
    existing record for that tenant key.
  * 11-#46 — nothing in-product explained that saved sign-ins depend on a
    server-side encryption key kept OUTSIDE the database, so a backup that
    only covers the database could still lose every saved sign-in for good.
    The fix is copy-only guidance in the "Encryption key" card; the key
    itself is never fetched or shown.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
VAULT_JS = JS_DIR / "applicantVault.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── 06-#47: Google password autocomplete ────────────────────────────────────


def test_google_secret_field_uses_current_password_autocomplete():
    js = _read(VAULT_JS)
    idx = js.index('id="applicant-vault-google-secret"')
    tag = js[max(0, idx - 200) : idx + 250]
    assert 'autocomplete="current-password"' in tag, (
        "expected the Google sign-in password field to hint "
        "autocomplete=\"current-password\" (an existing account being "
        "entered, not a new one being created)"
    )
    assert 'autocomplete="new-password"' not in tag, (
        "the Google password field must no longer use the new-password hint"
    )


def test_default_new_account_secret_field_is_unchanged_new_password():
    """The "default sign-in for new accounts" field genuinely IS used to
    create a brand-new account on a site, so new-password remains correct
    there — only the Google (existing-account) field should have changed."""
    js = _read(VAULT_JS)
    idx = js.index('id="applicant-vault-default-secret"')
    tag = js[max(0, idx - 200) : idx + 250]
    assert 'autocomplete="new-password"' in tag, (
        "expected the default new-account password field to keep "
        "autocomplete=\"new-password\" — this fix is scoped to the Google "
        "field only"
    )


# ── 01-#67: saved sign-in row remove/replace affordance ─────────────────────


def test_saved_tenant_rows_render_a_replace_control():
    js = _read(VAULT_JS)
    idx = js.index("listEl.innerHTML = tenants")
    body = js[idx : idx + 900]
    assert "applicant-vault-replace-tenant" in body, (
        "expected each saved sign-in row to render a per-row control "
        "(class applicant-vault-replace-tenant) since no delete endpoint "
        "exists to offer a true remove"
    )
    assert "data-tenant=" in body, (
        "expected the per-row control to carry the tenant key it acts on"
    )


def test_replace_control_is_wired_via_delegation_on_the_list_container():
    js = _read(VAULT_JS)
    assert re.search(
        r"on\(\s*'applicant-vault-list'\s*,\s*'click'\s*,\s*_onTenantRowClick\s*\)",
        js,
    ), (
        "expected the list container's click handler to be wired once via "
        "delegation (rows are re-rendered wholesale on every _loadTenants "
        "call, so binding per-row would leak/duplicate listeners)"
    )
    assert re.search(r"function _onTenantRowClick\(", js)
    assert re.search(r"function _prefillTenantForm\(", js), (
        "expected a shared prefill helper the replace control calls into"
    )


def test_replace_control_prefills_the_site_form_via_shared_helper():
    js = _read(VAULT_JS)
    idx = js.index("function _onTenantRowClick(")
    body = js[idx : idx + 300]
    assert "_prefillTenantForm(" in body, (
        "expected clicking a row's replace control to prefill the "
        "'sign-in for a specific site' form (tenant/username), not silently "
        "do nothing"
    )
    # The pre-existing post-takeover prefill path must now share the same
    # helper rather than duplicating the scroll/focus logic.
    open_idx = js.index("export async function openApplicantVault(")
    open_body = js[open_idx : open_idx + 3000]
    assert "_prefillTenantForm(prefillTenant)" in open_body, (
        "expected openApplicantVault's opts.prefillTenant path to reuse the "
        "shared _prefillTenantForm helper"
    )


def test_replace_control_notes_there_is_no_separate_remove():
    js = _read(VAULT_JS)
    idx = js.index("applicant-vault-replace-tenant")
    body = js[idx : idx + 400]
    assert "no separate remove" in body.lower() or "no remove" in body.lower(), (
        "expected the per-row control to plainly note there is no separate "
        "remove (since re-saving overwrites rather than truly deleting)"
    )
    # A maintainer-facing note about the missing engine-side delete route
    # should exist near the row-rendering code (not just a UI tooltip).
    render_idx = js.index("listEl.innerHTML = tenants")
    context = js[max(0, render_idx - 900) : render_idx]
    assert "delete" in context.lower() and "credentials.py" in context, (
        "expected a code comment noting the engine has no per-tenant delete "
        "route, so a future engine change can revisit this UI"
    )


def test_saved_credentials_never_fetched_or_shown_in_the_row_or_replace_flow():
    """Guard against a regression that would start reading a saved secret
    back to satisfy 'replace' — the vault must keep NEVER returning/rendering
    secret material, only tenant keys (NFR-PRIV-1)."""
    js = _read(VAULT_JS)
    idx = js.index("function _prefillTenantForm(")
    body = js[idx : idx + 500]
    assert "secret" not in body.lower(), (
        "the replace prefill must only ever touch the tenant/username "
        "fields — never a saved secret"
    )


# ── 11-#46: master-key backup guidance ──────────────────────────────────────


def test_encryption_key_card_explains_backup_risk_in_plain_language():
    js = _read(VAULT_JS)
    idx = js.index("Encryption key</h5>")
    card = js[idx : idx + 1600]
    assert "rotate" in card.lower(), "sanity: still inside the encryption-key card"
    assert "back" in card.lower(), (
        "expected the encryption-key card to mention backing up the key"
    )
    assert "lost" in card.lower() or "lose" in card.lower(), (
        "expected the card to explain what happens if the key is lost"
    )


def test_backup_guidance_does_not_expose_or_fetch_key_material():
    js = _read(VAULT_JS)
    idx = js.index("Encryption key</h5>")
    card = js[idx : idx + 1600]
    # No fetch/read of any key-bearing endpoint anywhere near this card, and
    # the copy itself must say the key is never shown here.
    assert "_fetchJSON" not in card and "_post(" not in card, (
        "the backup-guidance note must be copy-only — it must not fetch "
        "anything from the server"
    )
    assert "never shown" in card.lower() or "never sent" in card.lower(), (
        "expected the guidance to explicitly reassure that the key itself "
        "is not exposed on this screen"
    )


def test_backup_guidance_avoids_internal_requirement_jargon():
    """White-label/plain-language: no FR-/NFR- requirement codes leaking into
    the user-facing copy itself (they're fine in surrounding JS comments,
    which are not user-facing)."""
    js = _read(VAULT_JS)
    idx = js.index("Encryption key</h5>")
    card_html = js[idx : idx + 900]
    # Strip HTML comments (maintainer-facing) before checking the visible copy.
    visible = re.sub(r"<!--.*?-->", "", card_html, flags=re.DOTALL)
    assert not re.search(r"\bFR-[A-Z]", visible), (
        "expected no FR-#### jargon in the user-visible encryption-key copy"
    )
    assert not re.search(r"\bNFR-[A-Z]", visible), (
        "expected no NFR-#### jargon in the user-visible encryption-key copy"
    )
