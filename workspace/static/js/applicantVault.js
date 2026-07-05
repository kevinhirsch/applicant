// static/js/applicantVault.js
//
// Credential vault — the workspace surface for the engine's APPLICANT vault.
// Lets the user save per-site (per-tenant) sign-in credentials up front, lists
// which tenants already have credentials saved (NEVER the secrets themselves),
// and offers to save credentials captured during a live takeover / account
// creation.
//
// This is the engine's applicant vault (/api/applicant/vault/*) — entirely
// separate from the workspace's own password manager. It is ADDITIVE and
// self-contained: it owns its own modal and exposes two global seams:
//
//     window.openApplicantVault(campaignId)
//     window.offerApplicantCredentialCapture({ campaignId, tenantKey, username,
//                                               secret })
//
// The capture seam is what the live-takeover flow calls to offer saving the
// credentials the user just typed during account creation.
//
// SECURITY: secrets are never logged here, never read back from the server
// (the list returns tenant keys only), and the password field is type=password.

import uiModule from './ui.js';
import { esc, _toast, _fetchJSON, _post, errText, loadingHTML, errorHTML, wireRetry } from './applicantCore.js';

const API = '/api/applicant/vault';

// localStorage marker: the campaign (job search) the user last had the vault
// open for, so the picker doesn't reset to the first campaign every time the
// modal reopens without an explicit campaignId — mirrors the `applicant_` key
// convention already used for small UI-state markers (see applicantPortal.js's
// NOTIF_SEEN_KEY / RECAP_SEEN_KEY).
const LAST_CAMPAIGN_KEY = 'applicant_vault_last_campaign_id';

let _modalEl = null;
let _modalA11yCleanup = null;
let _campaignId = '';
let _busy = false;
// True once the user has typed/changed anything in the vault modal since it was
// last opened (or since the last successful save) — i.e. unsaved credential
// input a stray X / Escape / backdrop-click / swipe-dismiss would silently
// discard. Mirrors applicantOnboarding.js's `_formDirty` tracking.
let _vaultDirty = false;





// ── modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-vault-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  // a11y-deep audit #9: name the dialog from its own visible heading
  // (aria-labelledby) instead of a hardcoded string that can drift from the
  // screen — see the id on the h4 below.
  modal.setAttribute('aria-labelledby', 'applicant-vault-title');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:560px;display:flex;flex-direction:column;max-height:90vh;">
      <div class="modal-header">
        <h4 id="applicant-vault-title">Saved sign-ins</h4>
        <button id="applicant-vault-close" class="modal-close" aria-label="Close" title="Close">×</button>
      </div>
      <div class="modal-body" style="display:flex;flex-direction:column;gap:20px;overflow:auto;">
        <p style="margin:0;opacity:0.75;font-size:13px;">
          Save the username and password for a job site so I can sign in for you.
          Passwords are encrypted and are never shown again or sent
          back to this screen.
        </p>

        <!-- #109: lead with the trust payoff (what's already saved), not the
             forms — this card was last, below three forms; move it first. -->
        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <!-- a11y-deep audit #56: this section heading previously outranked
                 the dialog's own h4 title (h3 nested under h4) — dropped to h5
                 so the heading hierarchy nests correctly; the visible size is
                 still controlled entirely by the inline font-size, unchanged. -->
            <h5 style="margin:0;font-size:0.95em;flex:1;font-weight:600;">Sites with a saved sign-in
              <span id="applicant-vault-count" style="font-weight:400;opacity:0.6;"></span></h5>
            <button id="applicant-vault-refresh" class="memory-toolbar-btn" title="Reload the list of saved sign-ins">Refresh</button>
          </div>
          <div id="applicant-vault-list" role="list" style="display:flex;flex-direction:column;gap:6px;"></div>
          <div id="applicant-vault-empty" style="opacity:0.5;font-size:13px;padding:6px 0;">
            No sign-ins saved yet — add one below and the assistant will use it to sign in automatically.
          </div>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:10px;">
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Account sign-ins (used everywhere)</h5>
          <p style="margin:0;opacity:0.7;font-size:12px;">
            Set these once — they apply to every job search. Your Google sign-in
            lets me use “Sign in with Google” on any site; the default
            sign-in is used only if a site requires creating a brand-new account.
          </p>

          <div style="display:flex;flex-direction:column;gap:6px;border-top:1px solid var(--border);padding-top:8px;">
            <div style="font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;">
              Google sign-in
              <span id="applicant-vault-google-set" style="font-weight:400;font-size:11px;opacity:0.6;">not set</span>
            </div>
            <label class="ow-field" style="font-size:12px;opacity:0.8;">Google username or email
              <input id="applicant-vault-google-username" class="applicant-field" type="text" autocomplete="off"
                     placeholder="you@gmail.com" style="width:100%;margin-top:4px;">
            </label>
            <label class="ow-field" style="font-size:12px;opacity:0.8;display:flex;flex-direction:column;">
              Google password
              <span style="display:flex;gap:6px;align-items:center;margin-top:4px;">
                <input id="applicant-vault-google-secret" class="applicant-field" type="password" autocomplete="new-password"
                       placeholder="Google password" style="width:100%;">
                <button type="button" class="applicant-vault-toggle-secret cal-btn" data-target="applicant-vault-google-secret"
                        aria-pressed="false" title="Show/hide the password as you type" style="flex-shrink:0;padding:2px 8px;font-size:11px;">Show</button>
              </span>
            </label>
            <button id="applicant-vault-google-save" class="cal-btn" style="align-self:flex-start;"
                    title="Encrypt and save your Google sign-in">Save Google sign-in</button>
          </div>

          <div style="display:flex;flex-direction:column;gap:6px;border-top:1px solid var(--border);padding-top:8px;">
            <div style="font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px;">
              Default sign-in for new accounts
              <span id="applicant-vault-default-set" style="font-weight:400;font-size:11px;opacity:0.6;">not set</span>
            </div>
            <label class="ow-field" style="font-size:12px;opacity:0.8;">Default username or email
              <input id="applicant-vault-default-username" class="applicant-field" type="text" autocomplete="off"
                     placeholder="you@example.com" style="width:100%;margin-top:4px;">
            </label>
            <label class="ow-field" style="font-size:12px;opacity:0.8;display:flex;flex-direction:column;">
              Default password
              <span style="display:flex;gap:6px;align-items:center;margin-top:4px;">
                <input id="applicant-vault-default-secret" class="applicant-field" type="password" autocomplete="new-password"
                       placeholder="Password to use for new accounts" style="width:100%;">
                <button type="button" class="applicant-vault-toggle-secret cal-btn" data-target="applicant-vault-default-secret"
                        aria-pressed="false" title="Show/hide the password as you type" style="flex-shrink:0;padding:2px 8px;font-size:11px;">Show</button>
              </span>
            </label>
            <button id="applicant-vault-default-save" class="cal-btn" style="align-self:flex-start;"
                    title="Encrypt and save the default sign-in used when a site needs a new account">Save default sign-in</button>
          </div>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Sign-in for a specific site</h5>
          <label class="ow-field" style="font-size:12px;opacity:0.8;">Site / employer
            <input id="applicant-vault-tenant" class="applicant-field" type="text" placeholder="acme.workday.com"
                   title="The job site or employer this sign-in is for"
                   style="width:100%;margin-top:4px;">
          </label>
          <label class="ow-field" style="font-size:12px;opacity:0.8;">Username or email
            <input id="applicant-vault-username" class="applicant-field" type="text" autocomplete="off"
                   placeholder="you@example.com" style="width:100%;margin-top:4px;">
          </label>
          <label class="ow-field" style="font-size:12px;opacity:0.8;display:flex;flex-direction:column;">
            Password
            <span style="display:flex;gap:6px;align-items:center;margin-top:4px;">
              <input id="applicant-vault-secret" class="applicant-field" type="password" autocomplete="new-password"
                     placeholder="••••••••" style="width:100%;">
              <button type="button" class="applicant-vault-toggle-secret cal-btn" data-target="applicant-vault-secret"
                      aria-pressed="false" title="Show/hide the password as you type" style="flex-shrink:0;padding:2px 8px;font-size:11px;">Show</button>
            </span>
          </label>
          <button id="applicant-vault-save" class="cal-btn" style="align-self:flex-start;"
                  title="Encrypt and save this sign-in">Save sign-in</button>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Encryption key</h5>
          <p style="margin:0;opacity:0.7;font-size:12px;">
            Re-encrypt every saved sign-in under a brand-new key. Use this if you
            suspect the key that protects this vault may have been exposed. This
            does not change any username or password — it only replaces the key
            that protects them, and cannot be undone.
          </p>
          <button id="applicant-vault-rotate-key" class="cal-btn" style="align-self:flex-start;"
                  title="Re-encrypt every saved sign-in under a new key">Rotate encryption key</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  _modalEl = modal;
  _wire(modal);
  return modal;
}

function _wire(modal) {
  const on = (id, ev, fn) => {
    const node = modal.querySelector('#' + id);
    if (node) node.addEventListener(ev, fn);
  };
  on('applicant-vault-close', 'click', _maybeCloseVault);
  on('applicant-vault-save', 'click', _onSave);
  on('applicant-vault-google-save', 'click', () => _onSaveAccount('google'));
  on('applicant-vault-default-save', 'click', () => _onSaveAccount('predefined:account'));
  on('applicant-vault-refresh', 'click', () => _onRefreshTenants());
  on('applicant-vault-rotate-key', 'click', _onRotateKey);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) _maybeCloseVault();
  });
  // Track unsaved input so a stray close doesn't silently discard a typed-but-
  // unsaved credential (see _maybeCloseVault / _setVaultDirty below).
  modal.addEventListener('input', () => _setVaultDirty(true));
  modal.addEventListener('change', () => _setVaultDirty(true));
  _wireSaveProminence(modal);
  _wireEnterToSave(modal);
  _wireSecretToggles(modal);
}

// micro-interactions audit #35: Refresh never showed a busy state anywhere —
// a second click while a load is already in flight looked like nothing
// happened. Disable + relabel for the duration, mirroring the pattern
// applicantRemote.js's _setButtonBusy/_clearButtonBusy already use.
async function _onRefreshTenants() {
  const btn = _modalEl && _modalEl.querySelector('#applicant-vault-refresh');
  const prev = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Refreshing…'; }
  try {
    await _loadTenants();
  } catch (e) {
    console.debug('Silent catch in applicantVault:', e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = prev || 'Refresh'; }
  }
}

// micro-interactions audit #18/#15: Enter in any credential field submits its
// group's Save button (the canonical enter-to-submit form), guarded against
// firing on an IME composition-commit Enter (CJK / dead-key input).
function _wireEnterToSave(modal) {
  _SAVE_GROUPS.forEach((g) => {
    g.fields.forEach((fid) => {
      const el = modal.querySelector('#' + fid);
      if (!el) return;
      el.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229) return;
        e.preventDefault();
        const btn = modal.querySelector('#' + g.save);
        if (btn) btn.click();
      });
    });
  });
}

// micro-interactions audit #19: no show/hide toggle existed on any password
// field in the product — a shared kit helper would be the ideal fix (per the
// audit), but applicantCore.js/ui.js are outside this pass's file scope, so
// this is wired locally to the three password fields Vault owns.
function _wireSecretToggles(modal) {
  modal.querySelectorAll('.applicant-vault-toggle-secret').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = modal.querySelector('#' + btn.dataset.target);
      if (!input) return;
      const revealing = input.type === 'password';
      input.type = revealing ? 'text' : 'password';
      btn.textContent = revealing ? 'Hide' : 'Show';
      btn.setAttribute('aria-pressed', String(revealing));
    });
  });
}

// Sets the dirty flag AND toggles `data-no-swipe-dismiss` on the modal-content
// (the same opt-out hook applicantOnboarding.js's overlay uses statically — see
// ui.js's touchstart handler, which only engages swipe-dismiss when the
// attribute is absent). Here it's toggled dynamically: swipe-to-dismiss stays
// available while the form is clean, and is blocked the moment there's unsaved
// input, so a mobile swipe can't bypass the confirm-before-discard below (that
// gesture hides the modal directly via ui.js, never calling closeApplicantVault).
function _setVaultDirty(dirty) {
  _vaultDirty = dirty;
  const content = _modalEl && _modalEl.querySelector('.modal-content');
  if (content) {
    if (dirty) content.setAttribute('data-no-swipe-dismiss', '');
    else content.removeAttribute('data-no-swipe-dismiss');
  }
}

// Same async confirm shape as applicantPortal.js's `_confirm()` / applicantRemote.js's
// `_confirm()`: uiModule.styledConfirm with a window.confirm fallback.
async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

// Confirm-before-discard for the X button / Escape / backdrop click. Closes
// immediately when there's nothing unsaved to lose.
async function _maybeCloseVault() {
  if (!_vaultDirty) { closeApplicantVault(); return; }
  const ok = await _confirm(
    'Discard the sign-in details you just typed? They have not been saved yet.',
    { confirmText: 'Discard', cancelText: 'Keep editing', danger: true });
  if (ok) closeApplicantVault();
}

// #105: three co-equal "Save …" primaries read as competing CTAs. All three
// save buttons start neutral (no `.cal-btn-primary` in the markup); typing
// into a section's fields promotes ONLY that section's save button to
// prominent (and demotes the others), so at most one primary shows at a time
// and it tracks the card the user is actually filling in.
const _SAVE_GROUPS = [
  { save: 'applicant-vault-google-save', fields: ['applicant-vault-google-username', 'applicant-vault-google-secret'] },
  { save: 'applicant-vault-default-save', fields: ['applicant-vault-default-username', 'applicant-vault-default-secret'] },
  { save: 'applicant-vault-save', fields: ['applicant-vault-tenant', 'applicant-vault-username', 'applicant-vault-secret'] },
];

function _promoteSaveGroup(modal, activeSaveId) {
  _SAVE_GROUPS.forEach((g) => {
    const btn = modal.querySelector('#' + g.save);
    if (btn) btn.classList.toggle('cal-btn-primary', g.save === activeSaveId);
  });
}

function _wireSaveProminence(modal) {
  _SAVE_GROUPS.forEach((g) => {
    g.fields.forEach((fid) => {
      const el = modal.querySelector('#' + fid);
      if (el) el.addEventListener('input', () => _promoteSaveGroup(modal, g.save));
    });
  });
}

// ── list / save ─────────────────────────────────────────────────────────────

function _setVaultCount(n) {
  const el = _modalEl && _modalEl.querySelector('#applicant-vault-count');
  if (el) el.textContent = n > 0 ? `(${n})` : '';
}

// Map a kit error (with .kind) to a plain-language line for the retry card,
// mirroring the pattern established in applicantGallery.js / applicantCompare.js
// so 401 (session expired) reads differently from the engine being unreachable.
function _errLine(err) {
  if (err && (err.kind === 'offline' || err.kind === 'network')) {
    return 'The Applicant engine is not reachable right now. Saved sign-ins will load once it is connected.';
  }
  return errText(err);
}

// lens 04 #56: a 401 from any vault call is specifically a workspace-session
// expiry (the vault talks to the engine over the SAME cookie session as
// everything else) — narrower than the shared `.kind === 'auth'` bucket
// (which _fetchJSON also uses for a 403 forbidden, a different, non-expiry
// case), so check `.status` directly rather than `.kind` here.
function _isSessionExpired(err) {
  return !!(err && err.status === 401);
}

// Surfaces a clear, actionable "your session expired" affordance instead of
// the vault just failing generically (previously: a bare toast with the raw
// error message, or — for background calls like _loadAccountStatus — nothing
// at all). Reuses ui.js's showToast action-button mechanism (the same one
// other toasts already use for an Undo button) rather than inventing a new
// banner component; falls back to a plain toast + confirm-free redirect if
// the action-button toast shape isn't available for some reason.
function _offerReauth() {
  try {
    uiModule.showToast('Your session expired — sign in again to continue.', {
      duration: 15000,
      action: 'Sign in',
      onAction: () => { window.location.href = '/login'; },
    });
  } catch {
    _toast('Your session expired — sign in again to continue.');
  }
}

// Inline, in-modal counterpart to _offerReauth() for the "Saved sign-ins" list
// (the one place a stale session is most likely to be visible the moment the
// vault is opened) — a toast alone can be missed/auto-dismissed, so the list
// area itself also gets a persistent "Sign in again" affordance.
function _authExpiredHTML() {
  return `<div class="applicant-error" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">
    <div style="color:var(--red);font-weight:600;">Your session expired — sign in again to continue.</div>
    <div style="margin-top:12px;"><button class="cal-btn" type="button" id="applicant-vault-reauth">Sign in again</button></div>
  </div>`;
}

function _wireReauthButton(hostEl) {
  const btn = hostEl && hostEl.querySelector('#applicant-vault-reauth');
  if (btn) btn.addEventListener('click', () => { window.location.href = '/login'; });
}

// Shared catch-block handler for the vault's write actions (save / rotate-key /
// capture): a 401 gets the re-auth affordance instead of a generic "could not
// save" toast; everything else keeps the existing plain-language toast.
function _handleActionErr(e, fallbackMsg) {
  if (_isSessionExpired(e)) { _offerReauth(); return; }
  _toast(e.message || fallbackMsg);
}

async function _loadTenants() {
  const listEl = _modalEl && _modalEl.querySelector('#applicant-vault-list');
  const emptyEl = _modalEl && _modalEl.querySelector('#applicant-vault-empty');
  if (!listEl) return;
  if (!_campaignId) {
    listEl.innerHTML = '';
    if (emptyEl) {
      emptyEl.textContent = 'No job search yet — sign-ins are saved per job search, so create one first and they will show up here.';
      emptyEl.style.display = '';
    }
    _setVaultCount(0);
    return;
  }
  // Show a loading state while fetching so the list is never ambiguously blank.
  listEl.innerHTML = loadingHTML('Loading…');
  if (emptyEl) emptyEl.style.display = 'none';
  let data;
  try {
    data = await _fetchJSON(`${API}/${encodeURIComponent(_campaignId)}/tenants`);
  } catch (e) {
    if (emptyEl) emptyEl.style.display = 'none';
    if (_isSessionExpired(e)) {
      listEl.innerHTML = _authExpiredHTML();
      _wireReauthButton(listEl);
      _offerReauth();
      _setVaultCount(0);
      return;
    }
    listEl.innerHTML = errorHTML(_errLine(e));
    wireRetry(listEl, _loadTenants);
    _setVaultCount(0);
    return;
  }
  const tenants = (data && Array.isArray(data.tenants)) ? data.tenants : [];
  _setVaultCount(tenants.length);
  if (!tenants.length) {
    listEl.innerHTML = '';
    if (emptyEl) {
      emptyEl.textContent = 'No sign-ins saved yet — add one below and the assistant will use it to sign in automatically.';
      emptyEl.style.display = '';
    }
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  // Tenants may be plain strings or {tenant_key,...} objects — handle both.
  // a11y-deep audit #58: role="listitem" (paired with the container's
  // role="list" above) so SR users get "list, N items" context instead of
  // undifferentiated divs.
  listEl.innerHTML = tenants
    .map((t) => {
      const key = (t && typeof t === 'object') ? (t.tenant_key || t.key || '') : t;
      return `<div role="listitem" style="display:flex;align-items:center;gap:8px;font-size:13px;">
        <span aria-hidden="true" style="opacity:0.6;">🔒</span><span>${esc(key)}</span></div>`;
    })
    .join('');
}

async function _save({ tenantKey, username, secret }) {
  if (!_campaignId) { _toast('Choose a job search first'); return false; }
  if (!tenantKey || !username || !secret) {
    _toast('Fill in the site, username and password');
    return false;
  }
  if (_busy) return false;
  _busy = true;
  try {
    await _post(`${API}/credentials`, {
      campaign_id: _campaignId,
      tenant_key: tenantKey,
      username,
      secret,
    });
    _toast('Sign-in saved');
    _setVaultDirty(false);
    await _loadTenants().catch(e => console.debug('Silent catch in applicantVault:', e));
    return true;
  } catch (e) {
    _handleActionErr(e, 'Could not save the sign-in');
    return false;
  } finally {
    _busy = false;
  }
}

async function _onSave() {
  const tenant = _modalEl.querySelector('#applicant-vault-tenant');
  const username = _modalEl.querySelector('#applicant-vault-username');
  const secret = _modalEl.querySelector('#applicant-vault-secret');
  const ok = await _save({
    tenantKey: tenant ? tenant.value.trim() : '',
    username: username ? username.value.trim() : '',
    secret: secret ? secret.value : '',
  });
  if (ok && secret) secret.value = ''; // clear the password from the DOM after save
}

// ── account sign-ins (global: Google + the default new-account set) ───────────
//
// These are NOT scoped to a job search: the engine banks them under its SYSTEM
// campaign so a single Settings entry applies to every campaign ("sign in to
// Google once, reuse it everywhere"). The status line shows which are set
// WITHOUT ever reading a secret back.

const _ACCOUNT_FIELDS = {
  'google': { user: 'applicant-vault-google-username', secret: 'applicant-vault-google-secret', set: 'applicant-vault-google-set' },
  'predefined:account': { user: 'applicant-vault-default-username', secret: 'applicant-vault-default-secret', set: 'applicant-vault-default-set' },
};

async function _loadAccountStatus() {
  if (!_modalEl) return;
  let data;
  try {
    data = await _fetchJSON(`${API}/account`);
  } catch (e) {
    if (_isSessionExpired(e)) _offerReauth();
    return; /* leave the default "not set" labels */
  }
  // micro-interactions audit #31: the "saved ✓" status span was the only saved
  // signal — the password field itself always read as a plain, generic
  // placeholder, so reopening the vault could look like nothing had been
  // saved. Mirror the ladder's "(saved)" placeholder trick onto the secret
  // field too (a secret is still required every save — this is signal only).
  const mark = (id, on, secretId) => {
    const el = _modalEl.querySelector('#' + id);
    if (el) { el.textContent = on ? 'saved ✓' : 'not set'; el.style.opacity = on ? '0.8' : '0.6'; }
    const secretEl = secretId && _modalEl.querySelector('#' + secretId);
    if (secretEl && !secretEl.value) {
      if (secretEl.dataset.origPlaceholder == null) secretEl.dataset.origPlaceholder = secretEl.placeholder;
      secretEl.placeholder = on ? '•••••••• (already saved)' : secretEl.dataset.origPlaceholder;
    }
  };
  mark('applicant-vault-google-set', !!(data && data.google), 'applicant-vault-google-secret');
  mark('applicant-vault-default-set', !!(data && data.predefined_account), 'applicant-vault-default-secret');
}

async function _onSaveAccount(kind) {
  const f = _ACCOUNT_FIELDS[kind];
  if (!f || !_modalEl) return;
  const userEl = _modalEl.querySelector('#' + f.user);
  const secretEl = _modalEl.querySelector('#' + f.secret);
  const username = userEl ? userEl.value.trim() : '';
  const secret = secretEl ? secretEl.value : '';
  if (!username || !secret) { _toast('Fill in the username and password'); return; }
  if (_busy) return;
  _busy = true;
  try {
    await _post(`${API}/account`, { kind, username, secret });
    _toast('Sign-in saved');
    if (secretEl) secretEl.value = ''; // clear the password from the DOM after save
    _setVaultDirty(false);
    await _loadAccountStatus().catch(e => console.debug('Silent catch in applicantVault:', e));
  } catch (e) {
    _handleActionErr(e, 'Could not save the sign-in');
  } finally {
    _busy = false;
  }
}

// ── master-key rotation ─────────────────────────────────────────────────────
//
// Heavy, destructive-adjacent: it re-seals EVERY saved sign-in (per-site and
// account-level) under a brand-new key in one shot. Requires an explicit,
// danger-styled confirm before it does anything — same async-confirm shape as
// the discard-unsaved-input confirm above.

async function _onRotateKey() {
  const btn = _modalEl && _modalEl.querySelector('#applicant-vault-rotate-key');
  if (_busy) return;
  const ok = await _confirm(
    'Re-encrypt every saved sign-in under a brand-new encryption key? '
    + 'This cannot be undone.',
    { confirmText: 'Rotate key', cancelText: 'Cancel', danger: true });
  if (!ok) return;
  _busy = true;
  const prevLabel = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Rotating…'; }
  try {
    const data = await _post(`${API}/rotate-key`);
    const n = data && typeof data.records === 'number' ? data.records : null;
    _toast(n !== null
      ? `Encryption key rotated — ${n} sign-in${n === 1 ? '' : 's'} re-encrypted.`
      : 'Encryption key rotated.');
  } catch (e) {
    _handleActionErr(e, 'Could not rotate the encryption key');
  } finally {
    _busy = false;
    if (btn) { btn.disabled = false; btn.textContent = prevLabel || 'Rotate encryption key'; }
  }
}

// ── public surface ──────────────────────────────────────────────────────────

// Resolve a default campaign when the vault is opened proactively (e.g. from the
// Settings "Saved sign-ins" entry) without a caller-supplied campaign, so a user
// can add a Workday sign-in upfront. Best-effort; degrades to the existing
// "Choose a job search first" note if none can be found.
async function _resolveDefaultCampaign() {
  if (_campaignId) return _campaignId;
  try {
    const list = await _fetchJSON('/api/applicant/setup/campaigns');
    const arr = Array.isArray(list) ? list : (list && list.campaigns) || [];
    if (arr.length) {
      // Prefer the campaign the user last had the vault open for (persisted
      // across opens/reloads); fall back to the first campaign when nothing is
      // remembered OR the remembered one no longer exists (e.g. deleted).
      let last = null;
      try { last = window.localStorage.getItem(LAST_CAMPAIGN_KEY); } catch { last = null; }
      const match = last && arr.find((c) => c && String(c.id) === last);
      const chosen = match || arr[0];
      if (chosen && chosen.id) _campaignId = String(chosen.id);
    }
  } catch { /* leave unset; UI shows the choose-a-job-search note */ }
  return _campaignId;
}

// Best-effort persistence of the "last used" campaign so the next vault open
// without an explicit campaignId (e.g. the Settings "Saved sign-ins" entry)
// remembers the user's choice instead of always resetting to the first
// campaign in the list.
function _rememberCampaign(id) {
  if (!id) return;
  try { window.localStorage.setItem(LAST_CAMPAIGN_KEY, String(id)); } catch { /* no-op */ }
}

/** Open the vault UI. Account sign-ins (Google / default new-account) are global;
 *  per-site sign-ins are scoped to a job search (campaign). */
export async function openApplicantVault(campaignId, opts) {
  if (campaignId) _campaignId = String(campaignId);
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  // A fresh open starts clean — nothing typed yet this session to lose.
  _setVaultDirty(false);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _maybeCloseVault);
  await _loadAccountStatus().catch(e => console.debug('Silent catch in applicantVault:', e));
  if (!_campaignId) await _resolveDefaultCampaign();
  _rememberCampaign(_campaignId);
  await _loadTenants().catch(e => console.debug('Silent catch in applicantVault:', e));
  // Pre-fill the "add a sign-in" form for a known site — e.g. opened right after
  // the user created an account during a live takeover (FR-VAULT-2), so they only
  // have to type the username + password they just chose.
  const prefillTenant = opts && opts.prefillTenant;
  if (prefillTenant && _modalEl) {
    const tenant = _modalEl.querySelector('#applicant-vault-tenant');
    if (tenant) {
      tenant.value = String(prefillTenant);
      try { tenant.scrollIntoView({ block: 'center' }); } catch { /* no-op */ }
      const username = _modalEl.querySelector('#applicant-vault-username');
      if (username) { try { username.focus(); } catch { /* no-op */ } }
    }
  }
}

export function closeApplicantVault() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) _modalEl.classList.add('hidden');
}

/**
 * Offer to save credentials captured during a live takeover / account creation
 * (the auto-capture hook). Confirms with the user, then saves via the capture
 * endpoint. Returns true iff the credentials were saved.
 *
 * @param {{campaignId:string, tenantKey:string, username:string, secret:string}} c
 */
export async function offerApplicantCredentialCapture(c) {
  c = c || {};
  const campaignId = c.campaignId || _campaignId;
  if (!campaignId || !c.tenantKey || !c.username || !c.secret) return false;

  let proceed = true;
  try {
    if (uiModule.styledConfirm) {
      proceed = await uiModule.styledConfirm(
        `Save the sign-in you just used for “${c.tenantKey}” so I can `
        + 'reuse it next time? Your password is encrypted and never shown again.',
        { confirmText: 'Save it', cancelText: 'Not now' });
    } else {
      proceed = window.confirm(`Save the sign-in for "${c.tenantKey}"?`);
    }
  } catch { proceed = false; }
  if (!proceed) return false;

  if (_busy) return false;
  _busy = true;
  try {
    await _post(`${API}/capture`, {
      campaign_id: campaignId,
      tenant_key: c.tenantKey,
      username: c.username,
      secret: c.secret,
    });
    _toast('Sign-in saved');
    if (_modalEl && !_modalEl.classList.contains('hidden')) {
      await _loadTenants().catch(e => console.debug('Silent catch in applicantVault:', e));
    }
    return true;
  } catch (e) {
    _handleActionErr(e, 'Could not save the sign-in');
    return false;
  } finally {
    _busy = false;
  }
}

const applicantVaultModule = {
  openApplicantVault,
  closeApplicantVault,
  offerApplicantCredentialCapture,
};

try { window.openApplicantVault = openApplicantVault; } catch { /* no-op */ }
try { window.offerApplicantCredentialCapture = offerApplicantCredentialCapture; } catch { /* no-op */ }
try { window.applicantVaultModule = applicantVaultModule; } catch { /* no-op */ }

export default applicantVaultModule;
