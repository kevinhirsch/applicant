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

const API = '/api/applicant/vault';

let _modalEl = null;
let _campaignId = '';
let _busy = false;

function esc(s) {
  try {
    if (typeof uiModule.esc === 'function') return uiModule.esc(s);
  } catch { /* fall through */ }
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _toast(msg) {
  try { uiModule.showToast(msg); } catch { /* no-op */ }
}

async function _fetchJSON(url, opts = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data || {};
}

function _post(url, body) {
  return _fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ── modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-vault-modal';
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content" style="max-width:560px;width:96%;display:flex;flex-direction:column;max-height:90vh;">
      <div class="modal-header" style="display:flex;align-items:center;gap:10px;">
        <h2 style="margin:0;font-size:1.05em;flex:1;">Saved sign-ins</h2>
        <button id="applicant-vault-close" class="modal-close" title="Close">×</button>
      </div>
      <div class="modal-body" style="display:flex;flex-direction:column;gap:14px;overflow:auto;">
        <p style="margin:0;opacity:0.75;font-size:13px;">
          Save the username and password for a job site so the assistant can sign
          in for you. Passwords are encrypted and are never shown again or sent
          back to this screen.
        </p>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <label style="font-size:12px;opacity:0.8;">Site / employer
            <input id="applicant-vault-tenant" type="text" placeholder="acme.workday.com"
                   title="The job site or employer tenant this sign-in is for"
                   style="width:100%;margin-top:4px;">
          </label>
          <label style="font-size:12px;opacity:0.8;">Username or email
            <input id="applicant-vault-username" type="text" autocomplete="off"
                   placeholder="you@example.com" style="width:100%;margin-top:4px;">
          </label>
          <label style="font-size:12px;opacity:0.8;">Password
            <input id="applicant-vault-secret" type="password" autocomplete="new-password"
                   placeholder="••••••••" style="width:100%;margin-top:4px;">
          </label>
          <button id="applicant-vault-save" class="primary-btn" style="align-self:flex-start;"
                  title="Encrypt and save this sign-in">Save sign-in</button>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <h3 style="margin:0;font-size:0.95em;flex:1;">Sites with a saved sign-in</h3>
            <button id="applicant-vault-refresh" class="memory-toolbar-btn" title="Reload">Refresh</button>
          </div>
          <div id="applicant-vault-list" style="display:flex;flex-direction:column;gap:6px;"></div>
          <div id="applicant-vault-empty" style="opacity:0.5;font-size:13px;padding:6px 0;">
            No sign-ins saved yet.
          </div>
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
  on('applicant-vault-close', 'click', closeApplicantVault);
  on('applicant-vault-save', 'click', _onSave);
  on('applicant-vault-refresh', 'click', () => _loadTenants().catch(() => {}));
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeApplicantVault();
  });
}

// ── list / save ─────────────────────────────────────────────────────────────

async function _loadTenants() {
  const listEl = _modalEl && _modalEl.querySelector('#applicant-vault-list');
  const emptyEl = _modalEl && _modalEl.querySelector('#applicant-vault-empty');
  if (!listEl) return;
  if (!_campaignId) {
    listEl.innerHTML = '';
    if (emptyEl) { emptyEl.textContent = 'Choose a job search first.'; emptyEl.style.display = ''; }
    return;
  }
  let data;
  try {
    data = await _fetchJSON(`${API}/${encodeURIComponent(_campaignId)}/tenants`);
  } catch (e) {
    listEl.innerHTML = '';
    if (emptyEl) { emptyEl.textContent = e.message || 'Could not load saved sign-ins.'; emptyEl.style.display = ''; }
    return;
  }
  const tenants = (data && Array.isArray(data.tenants)) ? data.tenants : [];
  if (!tenants.length) {
    listEl.innerHTML = '';
    if (emptyEl) { emptyEl.textContent = 'No sign-ins saved yet.'; emptyEl.style.display = ''; }
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  // Tenants may be plain strings or {tenant_key,...} objects — handle both.
  listEl.innerHTML = tenants
    .map((t) => {
      const key = (t && typeof t === 'object') ? (t.tenant_key || t.key || '') : t;
      return `<div style="display:flex;align-items:center;gap:8px;font-size:13px;">
        <span style="opacity:0.6;">🔒</span><span>${esc(key)}</span></div>`;
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
    await _loadTenants().catch(() => {});
    return true;
  } catch (e) {
    _toast(e.message || 'Could not save the sign-in');
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
    if (arr.length && arr[0] && arr[0].id) _campaignId = String(arr[0].id);
  } catch { /* leave unset; UI shows the choose-a-job-search note */ }
  return _campaignId;
}

/** Open the vault UI, scoped to a job search (campaign). */
export async function openApplicantVault(campaignId) {
  if (campaignId) _campaignId = String(campaignId);
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  if (!_campaignId) await _resolveDefaultCampaign();
  await _loadTenants().catch(() => {});
}

export function closeApplicantVault() {
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
        `Save the sign-in you just used for "${c.tenantKey}" so the assistant can `
        + 'reuse it next time? Your password will be encrypted.',
        { confirmText: 'Save it', cancelText: 'No thanks' });
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
      await _loadTenants().catch(() => {});
    }
    return true;
  } catch (e) {
    _toast(e.message || 'Could not save the sign-in');
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
