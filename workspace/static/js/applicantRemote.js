// static/js/applicantRemote.js
//
// "Watch / Take over live session" — the workspace surface for the engine's live
// browser session. It embeds the running session in an iframe (via the engine's
// own view-url; provider URLs are NEVER hardcoded), lets the user take live
// control, and — at the final-submit step — either submit the application
// themselves or explicitly authorize the engine to click the final submit. It
// also offers the resume actions for the human-only steps (account creation,
// detection challenge) and shows the honest best-effort caveat.
//
// This module is ADDITIVE and self-contained: it owns its own modal, talks to
// the workspace proxy at /api/applicant/remote/*, and exposes a single global
// seam so another lane's portal can open the live session for an application:
//
//     window.openApplicantRemoteSession(applicationId, sessionUrl)
//
// SECURITY: the "Authorize the assistant to finish" and "I submitted it myself"
// controls call the engine's explicit authorize endpoints through the proxy. The
// assistant can never click the final submit without the user's explicit action
// — there is no client path that bypasses that.

import uiModule from './ui.js';
import { openApplicantVault } from './applicantVault.js';
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';

const API = '/api/applicant/remote';

let _modalEl = null;
let _modalA11yCleanup = null;
let _activeSession = null;   // { session_id, application_id, view_url }
let _busy = false;

// ── tiny helpers ────────────────────────────────────────────────────────────





// ── modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-remote-modal';
  // FR-UIKIT-2 (#481): the real dialog root composes the vendored Window kit's
  // `ow-window` alongside the legacy `.modal` (mirrors appkitChatHint.js, which
  // composes the kit `ow-`/`on-` classes onto its real rendered element). The class
  // lands on the actual painted dialog (role=dialog, aria-modal) so the responsive
  // kit window (no 480px cap) applies; existing `.modal hidden`/`.modal-content`
  // rules, handlers and the focus trap are preserved.
  modal.className = 'modal hidden ow-window';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Live application session');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:980px;display:flex;flex-direction:column;max-height:92vh;">
      <div class="modal-header" style="gap:10px;">
        <h4>Live application session</h4>
        <select id="applicant-remote-picker" class="settings-select" title="Choose which live session to watch"
                style="flex:0 1 auto;max-width:46%;display:none;"></select>
        <button id="applicant-remote-close" class="modal-close" aria-label="Close" title="Close">×</button>
      </div>
      <div class="modal-body" style="display:flex;flex-direction:column;gap:12px;overflow:auto;">
        <p style="margin:0;opacity:0.75;font-size:13px;" id="applicant-remote-intro">
          Watch the assistant fill out your application in real time. You can take
          over at any moment to do the parts only you should do — creating an
          account, clearing a verification, and the final submit.
        </p>

        <div id="applicant-remote-frame-wrap"
             style="position:relative;border:1px solid var(--border-color,#3334);border-radius:8px;overflow:hidden;background:#0b0b0b;min-height:40dvh;max-height:72dvh;">
          <iframe id="applicant-remote-frame" title="Live session"
                  style="width:100%;height:40dvh;max-height:72dvh;border:0;display:block;background:#0b0b0b;"
                  sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"
                  referrerpolicy="no-referrer"></iframe>
          <div id="applicant-remote-empty"
               style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;opacity:0.7;color:#f2f5f7;">
            No live session is open yet.
          </div>
        </div>

        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <button id="applicant-remote-takeover" class="cal-btn cal-btn-primary"
                  title="Take live control of the browser to do a step yourself">Take control</button>
          <button id="applicant-remote-open-tab" class="memory-toolbar-btn"
                  title="Open the live session full-screen in a new tab">Open in new tab</button>
          <button id="applicant-remote-refresh" class="memory-toolbar-btn"
                  title="Reload the list of live sessions">Refresh sessions</button>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <h3 style="margin:0;font-size:0.95em;">Resume after a step you did yourself</h3>
          <p style="margin:0;opacity:0.7;font-size:12px;">
            Use these once you have finished a step the assistant can't do on its own.
          </p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
            <button id="applicant-remote-resume-account" class="memory-toolbar-btn"
                    title="Continue after you created the account">I created the account — continue</button>
            <button id="applicant-remote-resume-detection" class="memory-toolbar-btn"
                    title="Continue after you cleared a verification / CAPTCHA">I cleared the verification — continue</button>
          </div>
        </div>

        <div id="applicant-remote-desktop" class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <h3 style="margin:0;font-size:0.95em;flex:1 1 auto;">Let the assistant help on the desktop</h3>
            <button id="applicant-remote-desktop-toggle" class="cal-btn" disabled
                    title="Let the assistant handle desktop steps the browser can't reach, like a file-upload dialog. You stay in control and approve each action.">
              Turn on</button>
          </div>
          <p style="margin:0;opacity:0.7;font-size:12px;">
            For the parts that live outside the web page — a file-upload dialog or
            another desktop window. You stay in control: it never creates accounts,
            clears verifications, or submits, and it asks before each step.
          </p>
          <p id="applicant-remote-desktop-note" style="margin:0;opacity:0.6;font-size:11px;">
            Coming in a future update — desktop help isn't set up on this sandbox yet.
          </p>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:10px;border-color:var(--accent-color,#5b8def);">
          <h3 style="margin:0;font-size:0.95em;">Finish the application</h3>
          <p style="margin:0;opacity:0.75;font-size:12px;">
            The assistant has pre-filled everything and stopped before the final
            submit. Choose how to finish — nothing is submitted until you decide.
          </p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
            <button id="applicant-remote-submit-self" class="cal-btn"
                    title="You will click submit yourself in the live session">I'll submit it myself</button>
            <button id="applicant-remote-authorize" class="cal-btn cal-btn-primary"
                    title="Let the assistant click the final submit, just this once">Authorize the assistant to finish</button>
          </div>
          <p style="margin:0;opacity:0.55;font-size:11px;">
            The assistant can only click the final submit when you authorize it
            here — it never submits on its own.
          </p>
        </div>

        <div id="applicant-remote-caveat" class="admin-card"
             style="font-size:12px;opacity:0.85;display:none;"></div>
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
  on('applicant-remote-close', 'click', closeRemoteSession);
  on('applicant-remote-takeover', 'click', _onTakeover);
  on('applicant-remote-open-tab', 'click', _onOpenTab);
  on('applicant-remote-refresh', 'click', () => _loadSessions().catch(e => console.error('Silent catch in applicantRemote:', e)));
  on('applicant-remote-resume-account', 'click', () => _resume('resume-account-step'));
  on('applicant-remote-resume-detection', 'click', () => _resume('resume-detection-step'));
  on('applicant-remote-submit-self', 'click', _onSubmitSelf);
  on('applicant-remote-authorize', 'click', _onAuthorizeFinish);
  on('applicant-remote-desktop-toggle', 'click', _onToggleDesktopAssist);

  const picker = modal.querySelector('#applicant-remote-picker');
  if (picker) {
    picker.addEventListener('change', () => {
      const sid = picker.value;
      const found = (_sessionList || []).find((s) => s.session_id === sid);
      if (found) _setActiveSession(found);
    });
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeRemoteSession();
  });
}

// ── session state / picker ──────────────────────────────────────────────────

let _sessionList = [];

function _setActiveSession(session) {
  _activeSession = session || null;
  const frame = _modalEl && _modalEl.querySelector('#applicant-remote-frame');
  const empty = _modalEl && _modalEl.querySelector('#applicant-remote-empty');
  if (frame) {
    if (session && session.view_url) {
      frame.src = session.view_url;
      if (empty) empty.style.display = 'none';
    } else {
      frame.removeAttribute('src');
      if (empty) empty.style.display = 'flex';
    }
  }
  // Reflect the selection in the picker if present.
  const picker = _modalEl && _modalEl.querySelector('#applicant-remote-picker');
  if (picker && session) picker.value = session.session_id;
  // Desktop-assist opt-in is per-session — refresh it whenever the session changes.
  _loadDesktopAssist().catch(e => console.error('Silent catch in applicantRemote:', e));
}

// ── desktop assist (opt-in, per-session; ships dormant/grayed) ───────────────
//
// "Let the assistant help on the desktop" — an opt-in, revocable toggle for the
// CURRENT live session that lets the assistant handle native desktop steps the
// browser can't reach (a file-upload dialog, an OS window). It reuses the engine's
// safety machinery (the assistant never creates accounts, clears verifications, or
// submits — and it asks before each step), so this control adds no bypass. While
// the desktop helper isn't baked into the sandbox image yet the engine reports it
// dormant and the toggle renders locked with honest "future update" copy. No dead UI.

let _desktopState = null; // { enabled, available, dormant }

function _renderDesktopAssist() {
  const card = _modalEl && _modalEl.querySelector('#applicant-remote-desktop');
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-desktop-toggle');
  const note = _modalEl && _modalEl.querySelector('#applicant-remote-desktop-note');
  if (!card || !btn || !note) return;
  const st = _desktopState || {};
  const available = !!st.available;
  const enabled = !!st.enabled;
  btn.disabled = !available || !_activeSession || !_activeSession.session_id;
  if (!available) {
    // Locked / grayed: honest "available in a future update" copy (no codenames).
    btn.textContent = 'Turn on';
    btn.classList.remove('cal-btn-primary');
    note.textContent = 'Coming in a future update — desktop help isn’t set up on this sandbox yet.';
    note.style.display = '';
    return;
  }
  btn.textContent = enabled ? 'Turn off' : 'Turn on';
  btn.classList.toggle('cal-btn-primary', !enabled);
  note.textContent = enabled
    ? 'On for this session. The assistant asks before each desktop step and never submits on its own.'
    : 'Off. Turn it on to let the assistant help with desktop steps for this session only.';
  note.style.display = '';
}

async function _loadDesktopAssist() {
  // Default to the locked state so the card is never accidentally interactive.
  _desktopState = { enabled: false, available: false, dormant: true };
  const sid = _activeSession && _activeSession.session_id;
  try {
    const data = sid
      ? await _fetchJSON(`${API}/sessions/${encodeURIComponent(sid)}/desktop`)
      : await _fetchJSON(`${API}/desktop/health`);
    if (data) _desktopState = data;
  } catch { /* best-effort; stays locked */ }
  _renderDesktopAssist();
}

async function _onToggleDesktopAssist() {
  if (_busy) return;
  if (!_activeSession || !_activeSession.session_id) {
    _toast('Open a live session first');
    return;
  }
  const sid = _activeSession.session_id;
  const turningOn = !(_desktopState && _desktopState.enabled);
  _busy = true;
  try {
    const data = await _post(
      `${API}/sessions/${encodeURIComponent(sid)}/desktop/${turningOn ? 'enable' : 'disable'}`,
    );
    if (data) _desktopState = { ..._desktopState, ...data };
    _toast(turningOn
      ? 'Desktop help is on for this session'
      : 'Desktop help is off for this session');
  } catch (e) {
    _toast(e.message || 'Could not change desktop help');
  } finally {
    _busy = false;
    _renderDesktopAssist();
  }
}

function _renderPicker() {
  const picker = _modalEl && _modalEl.querySelector('#applicant-remote-picker');
  if (!picker) return;
  if (_sessionList.length <= 1) {
    picker.style.display = 'none';
    return;
  }
  picker.style.display = '';
  picker.innerHTML = _sessionList
    .map((s) => {
      const label = `Application ${esc(s.application_id)}${s.has_takeover ? ' (you are in control)' : ''}`;
      return `<option value="${esc(s.session_id)}">${label}</option>`;
    })
    .join('');
}

async function _loadSessions() {
  let data;
  try {
    data = await _fetchJSON(`${API}/sessions`);
  } catch (e) {
    _toast(e.message || 'Could not load live sessions');
    return;
  }
  _sessionList = (data && Array.isArray(data.sessions)) ? data.sessions : [];
  _renderPicker();
  // Keep the current session if it still exists; otherwise pick the first.
  const keep = _activeSession
    && _sessionList.find((s) => s.session_id === _activeSession.session_id);
  if (keep) {
    _setActiveSession(keep);
  } else if (_sessionList.length) {
    _setActiveSession(_sessionList[0]);
  } else {
    _setActiveSession(null);
  }
}

async function _loadCaveat() {
  const box = _modalEl && _modalEl.querySelector('#applicant-remote-caveat');
  if (!box) return;
  let data;
  try {
    data = await _fetchJSON(`${API}/caveat`);
  } catch {
    return; // caveat is best-effort; never block the surface
  }
  const parts = [];
  if (data && data.caveat) parts.push(esc(data.caveat));
  if (data && data.egress_caveat) parts.push(esc(data.egress_caveat));
  if (!parts.length) return;
  box.innerHTML =
    '<strong>How this works (honestly):</strong><br>' +
    parts.map((p) => `<span>${p}</span>`).join('<br><br>');
  box.style.display = '';
}

// ── actions ─────────────────────────────────────────────────────────────────

function _needSession() {
  if (!_activeSession) {
    _toast('Open a live session first');
    return false;
  }
  return true;
}

async function _onTakeover() {
  if (_busy || !_needSession()) return;
  _busy = true;
  try {
    await _post(`${API}/sessions/${encodeURIComponent(_activeSession.session_id)}/takeover`);
    _toast('You now have control of the session');
    _loadSessions().catch(e => console.error('Silent catch in applicantRemote:', e));
  } catch (e) {
    _toast(e.message || 'Could not take control');
  } finally {
    _busy = false;
  }
}

function _onOpenTab() {
  if (!_needSession()) return;
  if (_activeSession.view_url) {
    try { window.open(_activeSession.view_url, '_blank', 'noopener'); } catch { /* no-op */ }
  }
}

async function _resume(step) {
  if (_busy || !_needSession()) return;
  const appId = _activeSession.application_id;
  _busy = true;
  let resp = null;
  try {
    resp = await _post(`${API}/applications/${encodeURIComponent(appId)}/${step}`);
    _toast('Continuing the application');
  } catch (e) {
    _toast(e.message || 'Could not continue');
  } finally {
    _busy = false;
  }
  // The account step is where the user just signed in / created an account in the
  // live session. Offer to SAVE that sign-in so the engine can reuse it next time
  // (FR-VAULT-2). Outside the busy guard so the offer never blocks the resume.
  if (resp && step === 'resume-account-step') _offerSaveSignIn(resp);
}

// FR-VAULT-2 auto-capture trigger. We can't read the password out of the sandboxed
// live session, so accepting opens the vault's add-a-sign-in form pre-scoped to this
// job search + site, where the user types the username + password they just chose —
// reusing the existing, tested capture UI (no new credential form). Non-blocking;
// declining is silent.
async function _offerSaveSignIn(resp) {
  const tenantKey = (resp && resp.tenant_key) || '';
  const campaignId = (resp && resp.campaign_id) || '';
  if (!tenantKey && !campaignId) return;
  const site = tenantKey ? tenantKey.split(':').pop() : 'this site';
  const proceed = await _confirm(
    `Save the sign-in you just used for ${site} so the assistant can reuse it next `
    + 'time? Your password is encrypted and never shown again.',
    { confirmText: 'Save it', cancelText: 'Not now' });
  if (!proceed) return;
  try {
    await openApplicantVault(campaignId, { prefillTenant: tenantKey });
  } catch { /* vault open is best-effort */ }
}

async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

// ── shared engine calls + confirm copy (reused by the Portal lane) ───────────
//
// The Portal's inline final-approval affordance (D2) calls the SAME engine
// endpoints as this modal. Rather than duplicate the fetch + the irreversible
// confirm wording, we expose thin helpers and the confirm-message builders here
// and the Portal imports them. There is still exactly one client path to each
// stop-boundary endpoint.

/** Submit-self: the user finished the submit themselves. Terminal. */
export function submitSelf(applicationId) {
  return _post(`${API}/applications/${encodeURIComponent(applicationId)}/submit-self`);
}

/** Authorize the engine to click the final submit, just this once. Terminal. */
export function authorizeEngineFinish(applicationId) {
  return _post(`${API}/applications/${encodeURIComponent(applicationId)}/authorize-engine-finish`);
}

/** Continue a Google 2FA hand-off: trigger the push, wait up to 60s for the
 *  on-device approval, then continue pre-fill (or the engine re-notifies for a
 *  retry on timeout). Returns the resulting application state. */
export function continueTwoFactor(applicationId) {
  return _post(`${API}/applications/${encodeURIComponent(applicationId)}/continue-two-factor`);
}

/** The honest best-effort / egress caveat copy (best-effort; never throws). */
export async function fetchCaveat() {
  try { return await _fetchJSON(`${API}/caveat`); }
  catch { return null; }
}

// D5: the authorize confirm must echo the role/company and a "materials
// approved ✓" reminder before the irreversible submit. `ctx` carries the human
// label (role/company) when the caller has it.
function _authorizeConfirmMessage(ctx) {
  const who = ctx && ctx.label ? `“${ctx.label}”` : 'this application';
  return (
    `Authorize the assistant to click the final submit for ${who}, just this once?\n\n`
    + 'Materials approved ✓ — this submits immediately and cannot be undone.'
  );
}

function _submitSelfConfirmMessage(ctx) {
  const who = ctx && ctx.label ? `“${ctx.label}”` : 'this application';
  return (
    `Open the live session to submit ${who} yourself. Mark it submitted only `
    + 'after you have clicked submit there.'
  );
}

async function _onSubmitSelf() {
  if (_busy || !_needSession()) return;
  const ok = await _confirm(
    'Mark this application as submitted by you? Do this after you have clicked '
    + 'submit in the live session.',
    { confirmText: 'Yes, I submitted it', cancelText: 'Not yet' });
  if (!ok) return;
  const appId = _activeSession.application_id;
  _busy = true;
  try {
    await submitSelf(appId);
    _toast('Recorded — thanks for finishing it yourself');
  } catch (e) {
    _toast(e.message || 'Could not record the submission');
  } finally {
    _busy = false;
  }
}

async function _onAuthorizeFinish() {
  if (_busy || !_needSession()) return;
  const ok = await _confirm(
    _authorizeConfirmMessage(_activeSession),
    { confirmText: 'Authorize & submit', cancelText: 'Cancel', danger: true });
  if (!ok) return;
  const appId = _activeSession.application_id;
  _busy = true;
  try {
    await authorizeEngineFinish(appId);
    _toast('Authorized — the assistant submitted the application');
  } catch (e) {
    _toast(e.message || 'Could not authorize the submission');
  } finally {
    _busy = false;
  }
}

// ── public surface ──────────────────────────────────────────────────────────

/**
 * Open the live-session takeover surface.
 *
 * The global seam another lane calls: `window.openApplicantRemoteSession(id, url)`.
 *
 * @param {string} [applicationId]  application to focus (matched in the session list)
 * @param {string} [sessionUrl]     optional engine view-url to embed immediately
 *                                   (so the portal can hand off without a round-trip)
 */
export async function openApplicantRemoteSession(applicationId, sessionUrl) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, closeRemoteSession);

  // If the caller handed us a URL, show it right away; the list refresh then
  // reconciles/identifies the session for the action buttons.
  if (applicationId || sessionUrl) {
    _setActiveSession({
      session_id: '',
      application_id: applicationId || '',
      view_url: sessionUrl || '',
    });
  }

  _loadCaveat().catch(e => console.error('Silent catch in applicantRemote:', e));
  await _loadSessions().catch(e => console.error('Silent catch in applicantRemote:', e));

  // Prefer the session that matches the requested application, if any.
  if (applicationId) {
    const match = _sessionList.find((s) => String(s.application_id) === String(applicationId));
    if (match) _setActiveSession(match);
  }
}

export function closeRemoteSession() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  const frame = _modalEl.querySelector('#applicant-remote-frame');
  if (frame) frame.removeAttribute('src'); // stop the stream when closed
}

// Expose the confirm-copy builders so the Portal lane echoes the SAME
// role/company + "materials approved ✓" reminder (D5) it would see here.
export function authorizeConfirmMessage(ctx) { return _authorizeConfirmMessage(ctx); }
export function submitSelfConfirmMessage(ctx) { return _submitSelfConfirmMessage(ctx); }

const applicantRemoteModule = {
  openApplicantRemoteSession,
  closeRemoteSession,
  submitSelf,
  authorizeEngineFinish,
  continueTwoFactor,
  fetchCaveat,
  authorizeConfirmMessage,
  submitSelfConfirmMessage,
};

// The cross-lane portal seam: open the live session for a given application.
try { window.openApplicantRemoteSession = openApplicantRemoteSession; } catch { /* no-op */ }
try { window.applicantRemoteModule = applicantRemoteModule; } catch { /* no-op */ }

export default applicantRemoteModule;
