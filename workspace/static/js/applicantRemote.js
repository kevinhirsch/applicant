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
// SECURITY: the "Submit it for me" and "I submitted it myself"
// controls call the engine's explicit authorize endpoints through the proxy. The
// assistant can never click the final submit without the user's explicit action
// — there is no client path that bypasses that.

import uiModule from './ui.js';
import { openApplicantVault } from './applicantVault.js';
import {
  esc, _toast, _fetchJSON, _post,
  errText, loadingHTML, errorHTML, wireRetry,
} from './applicantCore.js';

const API = '/api/applicant/remote';
const SNAPSHOT_API = '/api/applicant/snapshot';

let _modalEl = null;
let _modalA11yCleanup = null;
let _activeSession = null;   // { session_id, application_id, view_url }
let _busy = false;

// ── first-open explainer card (help/self-explain audit lens 12, #21) ───────
//
// The permanent intro paragraph above is good copy but is easy to skim past
// the first time someone opens this surface. Mirrors the digest's first-open
// feedback-loop card (emailLibrary/applicantDigest.js LOOP_INTRO_SEEN_KEY /
// _loopIntroHTML / _dismissLoopIntro): a localStorage "seen" flag under this
// session's established `applicant-` / `applicant_` key-naming convention
// (NOTIF_SEEN_KEY / RECAP_SEEN_KEY in applicantPortal.js), a small dismissible
// card reusing the `admin-card` look, and a `memory-toolbar-btn` "Got it"
// dismiss — no new plumbing. Shown exactly once, ever, per browser.
const REMOTE_INTRO_SEEN_KEY = 'applicant-remote-intro-seen';

function _isFirstOpenSeen() {
  try { return localStorage.getItem(REMOTE_INTRO_SEEN_KEY) === '1'; } catch (_) { return false; }
}

function _dismissFirstOpenCard(modal) {
  try { localStorage.setItem(REMOTE_INTRO_SEEN_KEY, '1'); } catch (_) { /* no-op */ }
  const el = modal && modal.querySelector('#applicant-remote-first-open');
  if (el) el.remove();
}

// Rendered once into the modal's static innerHTML (the modal element itself is
// memoized in `_modalEl` and only ever built once per page load), so this
// reflects the seen-flag at BUILD time — once dismissed it never reappears
// without a fresh page load, and a fresh load re-checks the persisted flag.
function _firstOpenCardHTML() {
  if (_isFirstOpenSeen()) return '';
  return `
    <div class="admin-card" id="applicant-remote-first-open" style="margin:0;padding:8px 10px;display:flex;align-items:flex-start;gap:8px;">
      <span style="flex:1;font-size:11px;opacity:0.85;line-height:1.4;">
        <strong>What live takeover is for:</strong> I work in a real browser and always stop
        before the steps only you should do — creating an account, clearing a verification,
        or the final submit. Click "Take control" any time to drive it yourself; when you're
        done, use the matching "Continue" button and I pick up right where you left off.
        Closing this window only stops you watching — it doesn't end the session.
      </span>
      <button type="button" class="memory-toolbar-btn" id="applicant-remote-first-open-dismiss">Got it</button>
    </div>`;
}

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
  // a11y-deep audit #9: name the dialog from its own visible heading
  // (aria-labelledby) instead of a hardcoded string that can drift from the
  // screen — see the id on the h4 below.
  modal.setAttribute('aria-labelledby', 'applicant-remote-title');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:980px;display:flex;flex-direction:column;max-height:92vh;">
      <div class="modal-header" style="gap:10px;">
        <h4 id="applicant-remote-title">Live application session</h4>
        <select id="applicant-remote-picker" class="settings-select" title="Choose which live session to watch"
                aria-label="Choose which live session to watch"
                style="flex:0 1 auto;max-width:46%;display:none;"></select>
        <button id="applicant-remote-close" class="modal-close" aria-label="Close" title="Close">×</button>
      </div>
      <div class="modal-body" style="display:flex;flex-direction:column;gap:12px;overflow:auto;">
        <p style="margin:0;opacity:0.75;font-size:13px;" id="applicant-remote-intro">
          Watch me fill out your application in real time. Take over at any
          moment to do the parts only you should do — creating an
          account, clearing a verification, and the final submit. When
          you're done, use the matching "Continue" button below and I'll
          pick up right where you left off — closing this window just
          stops you watching; it doesn't end the session.
        </p>
        ${_firstOpenCardHTML()}
        <!-- a11y-deep audit #22: the phase arc (launching/ready/took-control/
             continuing/submitted) was only visible pixels — this one polite
             live region mirrors it in words, updated by _announcePhase(). -->
        <div id="applicant-remote-phase" role="status" aria-live="polite"
             style="font-size:11px;opacity:0.7;min-height:14px;"></div>

        <div id="applicant-remote-frame-wrap"
             style="position:relative;border-radius:8px;overflow:hidden;background:#0b0b0b;box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--fg) 10%, transparent);min-height:40dvh;max-height:72dvh;">
          <iframe id="applicant-remote-frame" title="Live session"
                  style="width:100%;height:40dvh;max-height:72dvh;border:0;display:block;background:#0b0b0b;"
                  sandbox="allow-scripts allow-same-origin allow-forms allow-pointer-lock"
                  referrerpolicy="no-referrer"></iframe>
          <div id="applicant-remote-empty"
               style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;opacity:0.7;color:#f2f5f7;">
            No live session is open yet — when I'm working in a browser, it appears here.
          </div>
        </div>

        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
          <button id="applicant-remote-takeover" class="cal-btn"
                  title="Take live control of the browser to do a step yourself">Take control</button>
          <button id="applicant-remote-open-tab" class="cal-btn"
                  title="Open the live session full-screen in a new tab">Open in new tab</button>
          <button id="applicant-remote-refresh" class="cal-btn"
                  title="Reload the list of live sessions">Refresh list</button>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <!-- a11y-deep audit #56: dropped from h3 to h5 — this section
               heading previously outranked the dialog's own h4 title (h3
               nested under h4); the visible size is controlled entirely by
               the inline font-size, unchanged. -->
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Resume after a step you did yourself</h5>
          <p style="margin:0;opacity:0.7;font-size:12px;">
            Use these once you've finished a step I can't do on my own.
          </p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
            <button id="applicant-remote-resume-account" class="memory-toolbar-btn"
                    title="Continue after you created the account — I'll pick up right where I left off">I created the account — continue</button>
            <button id="applicant-remote-resume-detection" class="memory-toolbar-btn"
                    title="Continue after you cleared a verification / CAPTCHA — I'll pick up right where I left off">I cleared the verification — continue</button>
          </div>
        </div>

        <div id="applicant-remote-handoff" class="admin-card" style="display:none;flex-direction:column;gap:8px;">
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Fill these in yourself</h5>
          <p id="applicant-remote-handoff-note" style="margin:0;opacity:0.75;font-size:12px;">
            The assistant couldn't fill this form automatically. Copy each answer below
            into the live session, then submit it there and come back to mark it submitted.
          </p>
          <div id="applicant-remote-handoff-body" style="display:flex;flex-direction:column;gap:4px;"></div>
          <div>
            <button id="applicant-remote-handoff-copy-all" class="memory-toolbar-btn"
                    title="Copy every field and value below, one per line">Copy all</button>
          </div>
        </div>

        <div id="applicant-remote-desktop" class="admin-card" style="display:flex;flex-direction:column;gap:8px;">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <h5 style="margin:0;font-size:0.95em;font-weight:600;flex:1 1 auto;">Let me help on the desktop</h5>
            <button id="applicant-remote-desktop-toggle" class="cal-btn" disabled
                    title="Let me handle desktop steps the browser can't reach, like a file-upload dialog. You stay in control and approve each action.">
              Turn on</button>
          </div>
          <p id="applicant-remote-desktop-desc" style="margin:0;opacity:0.7;font-size:12px;">
            For the parts that live outside the web page — a file-upload dialog or
            another desktop window. You stay in control: I never create accounts,
            clear verifications, or submit, and I ask before each step.
          </p>
          <p id="applicant-remote-desktop-note" style="margin:0;opacity:0.6;font-size:11px;">
            Coming in a future update — desktop help isn’t set up on this computer yet.
          </p>
        </div>

        <div class="admin-card" style="display:flex;flex-direction:column;gap:10px;">
          <h5 style="margin:0;font-size:0.95em;font-weight:600;">Finish the application</h5>
          <p style="margin:0;opacity:0.75;font-size:12px;">
            I've filled in everything and stopped before the final
            submit. Choose how to finish — nothing is submitted until you decide.
          </p>
          <div>
            <button id="applicant-remote-preview-toggle" class="memory-toolbar-btn"
                    aria-expanded="false" aria-controls="applicant-remote-preview"
                    title="See the exact answers, documents, and posting that will be submitted before you authorize">
              Review exactly what will be sent</button>
          </div>
          <div id="applicant-remote-finish-actions" style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;">
            <button id="applicant-remote-submit-self" class="cal-btn"
                    title="You will click submit yourself in the live session">I'll submit it myself</button>
            <span aria-hidden="true" style="opacity:0.5;font-size:11px;font-style:italic;">or</span>
            <button id="applicant-remote-authorize" class="cal-btn cal-btn-danger"
                    title="I'll click the final submit — only after you confirm here">Submit it for me</button>
          </div>
          <div id="applicant-remote-authorize-hold" hidden
               style="display:none;flex-wrap:wrap;align-items:center;gap:12px;border:1px solid color-mix(in srgb, var(--danger, #e5484d) 45%, transparent);
                      background:color-mix(in srgb, var(--danger, #e5484d) 10%, transparent);border-radius:8px;padding:10px 12px;">
            <span id="applicant-remote-authorize-hold-text" role="status" aria-live="assertive"
                  style="font-weight:600;font-size:13px;"></span>
            <button id="applicant-remote-authorize-hold-cancel" type="button" class="memory-toolbar-btn"
                    title="Stop now — nothing has been sent yet">Cancel</button>
          </div>
          <p style="margin:0;opacity:0.55;font-size:11px;">
            I can only click the final submit when you authorize it
            here — I never submit on my own.
          </p>
          <div id="applicant-remote-preview" class="applicant-snapshot-preview" hidden
               style="display:none;flex-direction:column;gap:8px;border-top:1px solid var(--border,#3334);padding-top:10px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <strong style="font-size:12px;">Exactly what will be sent</strong>
              <span style="opacity:0.55;font-size:11px;flex:1 1 auto;">The exact, unchangeable record for this application — review it before you authorize.</span>
            </div>
            <div id="applicant-remote-preview-body" style="font-size:12px;color:var(--fg,#f2f5f7);"></div>
          </div>
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
  on('applicant-remote-refresh', 'click', () => _onRefreshSessions());
  on('applicant-remote-resume-account', 'click', () => _resume('resume-account-step'));
  on('applicant-remote-resume-detection', 'click', () => _resume('resume-detection-step'));
  on('applicant-remote-submit-self', 'click', _onSubmitSelf);
  on('applicant-remote-authorize', 'click', _onAuthorizeFinish);
  on('applicant-remote-preview-toggle', 'click', _onTogglePreview);
  on('applicant-remote-desktop-toggle', 'click', _onToggleDesktopAssist);
  on('applicant-remote-handoff-copy-all', 'click', _onCopyAllHandoff);
  on('applicant-remote-first-open-dismiss', 'click', () => _dismissFirstOpenCard(modal));

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

// a11y-deep audit #22: mirrors the phase arc (launching/ready/took-control/
// continuing/submitted) into the `#applicant-remote-phase` polite live region
// declared in the modal scaffold, so a screen-reader user gets the same
// signal a sighted user reads off the frame/buttons.
function _announcePhase(text) {
  const el = _modalEl && _modalEl.querySelector('#applicant-remote-phase');
  if (el) el.textContent = text || '';
}

function _setActiveSession(session) {
  _activeSession = session || null;
  const frame = _modalEl && _modalEl.querySelector('#applicant-remote-frame');
  const empty = _modalEl && _modalEl.querySelector('#applicant-remote-empty');
  if (frame) {
    if (session && session.view_url) {
      frame.src = session.view_url;
      if (empty) empty.style.display = 'none';
      _announcePhase('Live session ready to watch.');
    } else {
      frame.removeAttribute('src');
      if (empty) empty.style.display = 'flex';
      _announcePhase('No live session is open yet.');
    }
  }
  // Reflect the selection in the picker if present.
  const picker = _modalEl && _modalEl.querySelector('#applicant-remote-picker');
  if (picker && session) picker.value = session.session_id;
  // Desktop-assist opt-in is per-session — refresh it whenever the session changes.
  _loadDesktopAssist().catch(e => console.debug('Silent catch in applicantRemote:', e));
  // The "fill these in yourself" handoff is per-application — refresh it too.
  _loadHandoff().catch(e => console.debug('Silent catch in applicantRemote:', e));
  // The "what will be sent" preview is per-application — collapse it (and drop the
  // previous application's snapshot) whenever the active session changes so a stale
  // preview can never sit under a different application's decision pair.
  _collapsePreview();
  // micro-interactions audit #7: a new/switched session must never inherit a
  // previous application's "Submitted ✓" terminal lock on the finish buttons.
  _clearFinishTerminal();
}

// micro-interactions audit #7: after a successful submit-self/authorize, the
// "Finish the application" card used to stay fully active — nothing stopped
// a second tap on Authorize. Lock the decision pair and show a status line;
// cleared again in `_setActiveSession` when a different session is picked.
function _markFinishTerminal(statusText) {
  const selfBtn = _modalEl && _modalEl.querySelector('#applicant-remote-submit-self');
  const authBtn = _modalEl && _modalEl.querySelector('#applicant-remote-authorize');
  [selfBtn, authBtn].forEach((b) => {
    if (!b) return;
    b.disabled = true;
    b.setAttribute('aria-disabled', 'true');
    b.style.opacity = '0.55';
    b.style.cursor = 'not-allowed';
  });
  const actions = _modalEl && _modalEl.querySelector('#applicant-remote-finish-actions');
  if (actions) {
    let status = actions.querySelector('.applicant-remote-finish-status');
    if (!status) {
      status = document.createElement('span');
      status.className = 'applicant-remote-finish-status';
      status.setAttribute('role', 'status');
      status.style.cssText = 'font-weight:600;font-size:12px;color:var(--success,#3a8a3a);';
      actions.appendChild(status);
    }
    status.textContent = statusText;
  }
  _announcePhase(statusText);
}

function _clearFinishTerminal() {
  const selfBtn = _modalEl && _modalEl.querySelector('#applicant-remote-submit-self');
  const authBtn = _modalEl && _modalEl.querySelector('#applicant-remote-authorize');
  [selfBtn, authBtn].forEach((b) => {
    if (!b) return;
    b.disabled = false;
    b.removeAttribute('aria-disabled');
    b.style.opacity = '';
    b.style.cursor = '';
  });
  const actions = _modalEl && _modalEl.querySelector('#applicant-remote-finish-actions');
  const status = actions && actions.querySelector('.applicant-remote-finish-status');
  if (status) status.remove();
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
  const desc = _modalEl && _modalEl.querySelector('#applicant-remote-desktop-desc');
  if (!card || !btn || !note) return;
  const st = _desktopState || {};
  const available = !!st.available;
  const enabled = !!st.enabled;
  btn.disabled = !available || !_activeSession || !_activeSession.session_id;
  if (!available) {
    // Locked / grayed: honest "available in a future update" copy (no codenames).
    // #116: while dormant, collapse to a single disabled row (hide the
    // descriptive paragraph) so this card doesn't push the irreversible
    // "Finish the application" action further below the fold.
    if (desc) desc.style.display = 'none';
    if (card) { card.style.paddingTop = '8px'; card.style.paddingBottom = '8px'; }
    btn.textContent = 'Turn on';
    btn.classList.remove('cal-btn-primary');
    btn.setAttribute('aria-pressed', 'false');
    note.textContent = 'Coming in a future update — desktop help isn’t set up on this computer yet.';
    note.style.display = '';
    return;
  }
  if (desc) desc.style.display = '';
  if (card) { card.style.paddingTop = ''; card.style.paddingBottom = ''; }
  btn.textContent = enabled ? 'Turn off' : 'Turn on';
  btn.classList.toggle('cal-btn-primary', !enabled);
  // a11y-deep audit #30 (toggle-state inventory): reflect the on/off state
  // programmatically, not just in the button's own changing label.
  btn.setAttribute('aria-pressed', String(enabled));
  note.textContent = enabled
    ? "On for this session. I'll ask before each desktop step and never submit on my own."
    : "Off. Turn it on and I'll help with desktop steps for this session only.";
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
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-desktop-toggle');
  if (btn && btn.disabled) return; // already in flight — can't double-fire
  const sid = _activeSession.session_id;
  const turningOn = !(_desktopState && _desktopState.enabled);
  _busy = true;
  const orig = _setButtonBusy(btn, turningOn ? 'Turning on…' : 'Turning off…');
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
    // `orig` is discarded: `_renderDesktopAssist()` recomputes the correct
    // label/disabled state from the (possibly just-changed) desktop state.
    _clearButtonBusy(btn, orig);
    _renderDesktopAssist();
  }
}

// ── "Fill these in yourself" emergency copy/paste handoff (FR-PREFILL-7) ────
//
// A last-resort fallback for when automated pre-fill tried the form and failed
// (a hard fill error, or the assistant didn't recognize the form well enough to
// map more than a few fields). The engine hands back whatever it WOULD have
// filled in; this panel surfaces those field/value pairs so the user can paste
// them into the live session by hand, then finish and mark it submitted with
// the existing "I'll submit it myself" control below. Hidden entirely (no dead
// UI) unless this application actually has an open handoff.

let _handoffData = null; // { available, handoff_values, ... } | null

function _handoffEls() {
  const card = _modalEl && _modalEl.querySelector('#applicant-remote-handoff');
  const body = _modalEl && _modalEl.querySelector('#applicant-remote-handoff-body');
  const note = _modalEl && _modalEl.querySelector('#applicant-remote-handoff-note');
  const copyAllBtn = _modalEl && _modalEl.querySelector('#applicant-remote-handoff-copy-all');
  return { card, body, note, copyAllBtn };
}

function _renderHandoff() {
  const { card, body, note, copyAllBtn } = _handoffEls();
  if (!card || !body) return;
  const values = (_handoffData && _handoffData.available && _handoffData.handoff_values)
    ? _handoffData.handoff_values
    : null;
  const fields = values ? Object.keys(values) : [];
  if (!fields.length) {
    card.style.display = 'none';
    body.innerHTML = '';
    return;
  }
  card.style.display = 'flex';
  if (note) {
    note.textContent = _handoffData.kind === 'wrong_ats'
      ? 'The assistant didn’t recognize this form well enough to fill it in '
        + 'automatically. Copy each answer below into the live session, then submit '
        + 'it there and come back to mark it submitted.'
      : 'The assistant tried to fill this form and ran into a problem. Copy each '
        + 'answer below into the live session, then submit it there and come back '
        + 'to mark it submitted.';
  }
  body.innerHTML = fields.map((label) => (
    `<div style="display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px solid var(--border,#3334);">`
    + `<div style="flex:0 0 40%;max-width:40%;opacity:0.75;word-break:break-word;font-size:12px;">${esc(label)}</div>`
    + `<div style="flex:1 1 auto;white-space:pre-wrap;word-break:break-word;font-size:12px;">${esc(String(values[label]))}</div>`
    + `<button type="button" class="memory-toolbar-btn applicant-remote-handoff-copy-one" `
    + `data-label="${esc(label)}" title="Copy this value" style="flex:0 0 auto;padding:2px 8px;">Copy</button>`
    + `</div>`
  )).join('');
  body.querySelectorAll('.applicant-remote-handoff-copy-one').forEach((btn) => {
    btn.addEventListener('click', () => {
      const label = btn.getAttribute('data-label');
      const value = values[label];
      uiModule.copyToClipboard(value == null ? '' : String(value));
    });
  });
  if (copyAllBtn) copyAllBtn.disabled = false;
}

async function _loadHandoff() {
  _handoffData = null;
  const appId = _activeSession && _activeSession.application_id;
  if (!appId) { _renderHandoff(); return; }
  try {
    const data = await _fetchJSON(`${API}/applications/${encodeURIComponent(appId)}/emergency-handoff`);
    if (data) _handoffData = data;
  } catch { /* best-effort; panel simply stays hidden */ }
  _renderHandoff();
}

function _onCopyAllHandoff() {
  const values = (_handoffData && _handoffData.available && _handoffData.handoff_values) || {};
  const lines = Object.keys(values).map((label) => `${label}: ${values[label]}`);
  if (!lines.length) return;
  uiModule.copyToClipboard(lines.join('\n'));
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

// micro-interactions audit #35: Refresh sessions never showed a busy state —
// a second click while a load was in flight looked like nothing happened.
async function _onRefreshSessions() {
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-refresh');
  const orig = _setButtonBusy(btn, 'Refreshing…');
  try {
    await _loadSessions();
  } catch (e) {
    console.debug('Silent catch in applicantRemote:', e);
  } finally {
    _clearButtonBusy(btn, orig);
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

// ── busy-button guard ──────────────────────────────────────────────────────
//
// Bug fix: the shared `_busy` module flag alone doesn't stop a fast double-click,
// because the DOM buttons themselves were never disabled — and any handler that
// threw before its `finally` could strand `_busy=true` forever. Every consequential
// button now (a) disables itself SYNCHRONOUSLY at click time, before any `await`
// (including a confirm dialog), so a second click physically cannot fire the
// request again, and (b) is always re-enabled in a `finally`, so a thrown error
// can never leave it permanently stuck. Mirrors the disable/restore-on-error
// pattern already used for the Portal's row buttons (applicantPortal.js `_wireRows`).
function _setButtonBusy(btn, busyText) {
  if (!btn) return null;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.style.opacity = '0.6';
  btn.style.cursor = 'wait';
  if (busyText) btn.textContent = busyText;
  return orig;
}

function _clearButtonBusy(btn, orig) {
  if (!btn) return;
  btn.disabled = false;
  btn.removeAttribute('aria-busy');
  btn.style.opacity = '';
  btn.style.cursor = '';
  if (orig != null) btn.textContent = orig;
}

async function _onTakeover() {
  if (_busy || !_needSession()) return;
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-takeover');
  if (btn && btn.disabled) return; // already in flight — can't double-fire
  _busy = true;
  const orig = _setButtonBusy(btn, 'Taking control…');
  try {
    await _post(`${API}/sessions/${encodeURIComponent(_activeSession.session_id)}/takeover`);
    _toast('You now have control of the session');
    _announcePhase('You now have control of the session.');
    _loadSessions().catch(e => console.debug('Silent catch in applicantRemote:', e));
  } catch (e) {
    _toast(e.message || 'Could not take control');
  } finally {
    _busy = false;
    _clearButtonBusy(btn, orig);
  }
}

function _onOpenTab() {
  if (!_needSession()) return;
  if (_activeSession.view_url) {
    try { window.open(_activeSession.view_url, '_blank', 'noopener'); } catch { /* no-op */ }
  }
}

// Maps each resume step to its DOM button, so the busy-button guard can disable
// the specific control the user clicked.
const _RESUME_BUTTON_IDS = {
  'resume-account-step': 'applicant-remote-resume-account',
  'resume-detection-step': 'applicant-remote-resume-detection',
};

async function _resume(step) {
  if (_busy || !_needSession()) return;
  const btnId = _RESUME_BUTTON_IDS[step];
  const btn = btnId && _modalEl && _modalEl.querySelector('#' + btnId);
  if (btn && btn.disabled) return; // already in flight — can't double-fire
  const appId = _activeSession.application_id;
  _busy = true;
  const orig = _setButtonBusy(btn, 'Continuing…');
  let resp = null;
  try {
    resp = await _post(`${API}/applications/${encodeURIComponent(appId)}/${step}`);
    _toast('Continuing the application');
    _announcePhase('Continuing the application.');
  } catch (e) {
    _toast(e.message || 'Could not continue');
  } finally {
    _busy = false;
    _clearButtonBusy(btn, orig);
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
    `Save the sign-in you just used for ${site} so I can reuse it next `
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
    `Let me click the final submit for ${who}, just this once?\n\n`
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
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-submit-self');
  if (btn && btn.disabled) return; // already in flight — can't double-fire
  // Bug fix: disable the button (and claim `_busy`) BEFORE the confirm dialog, not
  // after — a fast double-click could otherwise open two confirms and, if both were
  // accepted, fire two POSTs before either `finally` ran.
  _busy = true;
  const orig = _setButtonBusy(btn);
  let submitted = false;
  try {
    // micro-interactions audit #87: reuse the SAME confirm-copy builder Portal
    // does for this stop-boundary, instead of a hand-written string that had
    // drifted from it — one source of truth for the wording.
    const ok = await _confirm(
      _submitSelfConfirmMessage(_activeSession),
      { confirmText: 'Yes, I submitted it', cancelText: 'Not yet' });
    if (!ok) return;
    if (btn) btn.textContent = 'Recording…';
    const appId = _activeSession.application_id;
    await submitSelf(appId);
    _toast('Recorded — thanks for finishing it yourself');
    submitted = true;
  } catch (e) {
    _toast(e.message || 'Could not record the submission');
  } finally {
    _busy = false;
    _clearButtonBusy(btn, orig);
  }
  // micro-interactions audit #7: lock the "Finish the application" decision
  // pair AFTER the busy-clear above (which re-enables both buttons) so the
  // terminal disabled state is the one that actually sticks.
  if (submitted) _markFinishTerminal('Submitted ✓ — thanks for finishing it yourself.');
}

// ── authorize hold/cancel window (Top-25 #12) ────────────────────────────
//
// The text-confirm dialog above is the user's explicit decision; this is an
// ADDITIONAL layer that sits strictly BETWEEN that decision and the guarded
// call to `authorizeEngineFinish` — the single most irreversible action in
// the product (it physically clicks a real employer's submit button). After
// the user confirms, nothing is sent to the engine yet: a visible
// "Submitting in N… [Cancel]" hold runs for AUTHORIZE_HOLD_SECONDS, during
// which a keyboard-reachable Cancel aborts the whole action with zero side
// effects. Only when the hold completes uncanceled does the existing
// double-click-guarded flow proceed to call the engine, exactly as before.
const AUTHORIZE_HOLD_SECONDS = 5;

// Set only while a hold window is in flight; `closeRemoteSession()` calls it
// to cancel a pending hold if the modal is torn down mid-countdown, so the
// timer can never fire the engine call after the surface it belongs to is
// gone (no detached/orphaned timer survives modal teardown).
let _holdCancelResolve = null;
let _holdTimerId = null;
let _holdCancelBtnHandler = null; // wired via addEventListener, removed on every teardown

function _holdEls() {
  const row = _modalEl && _modalEl.querySelector('#applicant-remote-authorize-hold');
  const text = _modalEl && _modalEl.querySelector('#applicant-remote-authorize-hold-text');
  const cancelBtn = _modalEl && _modalEl.querySelector('#applicant-remote-authorize-hold-cancel');
  const actions = _modalEl && _modalEl.querySelector('#applicant-remote-finish-actions');
  return { row, text, cancelBtn, actions };
}

function _clearHold() {
  if (_holdTimerId != null) { clearTimeout(_holdTimerId); _holdTimerId = null; }
  const { row, cancelBtn, actions } = _holdEls();
  if (row) { row.hidden = true; row.style.display = 'none'; }
  if (cancelBtn && _holdCancelBtnHandler) cancelBtn.removeEventListener('click', _holdCancelBtnHandler);
  _holdCancelBtnHandler = null;
  if (actions) actions.style.display = '';
  _holdCancelResolve = null;
}

/** Cancel any hold window in flight (called on modal teardown). Resolves the
 *  pending `_holdBeforeAuthorize()` promise to `false` — the caller reads
 *  that as "don't proceed" and returns before ever calling the engine. */
function _cancelPendingHold() {
  if (!_holdCancelResolve) return;
  const resolve = _holdCancelResolve;
  _clearHold();
  resolve(false);
}

// Renders the "Submitting in N… [Cancel]" hold and resolves once it either
// completes (true — proceed) or is canceled/torn down (false — abort).
// Text-only countdown (no color/motion animation), so there is nothing that
// needs to respect prefers-reduced-motion; the Cancel button is a real,
// focusable `<button type="button">` reachable by keyboard, and is focused
// as soon as the hold appears.
function _holdBeforeAuthorize() {
  return new Promise((resolve) => {
    const { row, text, cancelBtn, actions } = _holdEls();
    if (!row || !text || !cancelBtn) { resolve(true); return; } // defensive: markup missing
    let remaining = AUTHORIZE_HOLD_SECONDS;
    _holdCancelResolve = resolve;
    const render = () => {
      text.textContent = `Submitting in ${remaining}… `
        + 'Nothing has been sent yet — you can still cancel.';
    };
    if (actions) actions.style.display = 'none';
    row.hidden = false;
    row.style.display = 'flex';
    render();
    const finish = (proceed) => {
      _clearHold();
      resolve(proceed);
    };
    _holdCancelBtnHandler = () => finish(false);
    cancelBtn.addEventListener('click', _holdCancelBtnHandler);
    cancelBtn.focus();
    const tick = () => {
      remaining -= 1;
      if (remaining <= 0) { finish(true); return; }
      render();
      _holdTimerId = setTimeout(tick, 1000);
    };
    _holdTimerId = setTimeout(tick, 1000);
  });
}

async function _onAuthorizeFinish() {
  if (_busy || !_needSession()) return;
  const btn = _modalEl && _modalEl.querySelector('#applicant-remote-authorize');
  if (btn && btn.disabled) return; // already in flight — can't double-fire
  // Bug fix: disable the button (and claim `_busy`) BEFORE the confirm dialog — see
  // `_onSubmitSelf` above. This is the control that authorizes the engine to click
  // the employer's real final-submit button, so closing this race matters most.
  _busy = true;
  const orig = _setButtonBusy(btn);
  let submitted = false;
  try {
    const ok = await _confirm(
      _authorizeConfirmMessage(_activeSession),
      { confirmText: 'Authorize & submit', cancelText: 'Cancel', danger: true });
    if (!ok) return;
    // Hold/cancel window: one more, undoable pause before anything is sent to
    // the engine. Canceling here returns to the pre-confirm state with no
    // side effects — `authorizeEngineFinish` below is simply never reached.
    const proceed = await _holdBeforeAuthorize();
    if (!proceed) { _toast('Canceled — nothing was submitted'); return; }
    if (btn) btn.textContent = 'Authorizing…';
    const appId = _activeSession.application_id;
    await authorizeEngineFinish(appId);
    _toast('Done — I submitted the application for you');
    submitted = true;
  } catch (e) {
    _toast(e.message || 'Could not authorize the submission');
  } finally {
    _busy = false;
    _clearButtonBusy(btn, orig);
  }
  // micro-interactions audit #7: lock the decision pair AFTER the busy-clear
  // above so the terminal disabled state is the one that sticks — the
  // employer's real submit button was just physically clicked; a second tap
  // on Authorize must not be possible.
  if (submitted) _markFinishTerminal('Submitted ✓ — I finished it for you.');
}

// ── "Review exactly what will be sent" — the pre-submit snapshot preview ─────
//
// Before the owner authorizes the irreversible submit, they can open an in-flow
// panel that shows the engine's immutable submission snapshot for THIS application
// — the exact answers, the document/material versions, the posting, and the
// timestamp. It renders whatever the engine has recorded and NEVER fabricates: the
// pre-submit state (no snapshot yet) reads as an honest "nothing recorded to send
// yet" empty state via the shared kit. The panel lives BELOW the decision pair so
// opening it never pushes "I'll submit it myself" / "Submit it for me"
// below the fold.

let _previewOpen = false;

function _previewEls() {
  const wrap = _modalEl && _modalEl.querySelector('#applicant-remote-preview');
  const body = _modalEl && _modalEl.querySelector('#applicant-remote-preview-body');
  const toggle = _modalEl && _modalEl.querySelector('#applicant-remote-preview-toggle');
  return { wrap, body, toggle };
}

function _collapsePreview() {
  _previewOpen = false;
  const { wrap, body, toggle } = _previewEls();
  if (wrap) { wrap.hidden = true; wrap.style.display = 'none'; }
  if (body) body.innerHTML = '';
  if (toggle) {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.textContent = 'Review exactly what will be sent';
  }
}

async function _onTogglePreview() {
  const { wrap, toggle } = _previewEls();
  if (!wrap || !toggle) return;
  if (_previewOpen) { _collapsePreview(); return; }
  if (!_needSession()) return;
  _previewOpen = true;
  wrap.hidden = false;
  wrap.style.display = 'flex';
  toggle.setAttribute('aria-expanded', 'true');
  toggle.textContent = 'Hide what will be sent';
  await _loadSnapshotPreview();
}

async function _loadSnapshotPreview() {
  const { body } = _previewEls();
  if (!body) return;
  const appId = _activeSession && _activeSession.application_id;
  if (!appId) { body.innerHTML = _snapshotEmptyHTML(); return; }
  body.innerHTML = loadingHTML('Loading what will be sent…');
  let data;
  try {
    data = await _fetchJSON(`${SNAPSHOT_API}/${encodeURIComponent(appId)}`);
  } catch (e) {
    body.innerHTML = errorHTML(errText(e));
    wireRetry(body, () => _loadSnapshotPreview());
    return;
  }
  if (data && data.engine_available === false) {
    body.innerHTML = errorHTML("I can't load what will be sent right now — try again in a moment.");
    wireRetry(body, () => _loadSnapshotPreview());
    return;
  }
  body.innerHTML = _renderSnapshot(data || {});
}

// Honest empty state — the snapshot is recorded at the final-submit stop-boundary,
// so before you authorize there may be nothing recorded yet. Never fabricated.
function _snapshotEmptyHTML() {
  return `<div class="applicant-empty" style="text-align:left;color:var(--fg-muted);padding:10px 2px;">`
    + `<div style="font-weight:600;color:var(--fg,#f2f5f7);">Nothing recorded to send yet</div>`
    + `<div style="margin-top:4px;opacity:0.75;">The exact answers, documents, and posting appear here once `
    + `I've filled everything in and stopped before the final submit. If this stays empty, open the live session above to review the filled form directly.</div>`
    + `</div>`;
}

function _kvRows(obj) {
  const keys = Object.keys(obj || {});
  if (!keys.length) return '';
  return keys.map((k) => (
    `<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--border,#3334);">`
    + `<div style="flex:0 0 40%;max-width:40%;opacity:0.7;word-break:break-word;">${esc(k)}</div>`
    + `<div style="flex:1 1 auto;white-space:pre-wrap;word-break:break-word;">${esc(_scalar(obj[k]))}</div>`
    + `</div>`
  )).join('');
}

function _scalar(v) {
  if (v == null) return '';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

function _renderSnapshot(data) {
  if (!data || data.has_snapshot === false) return _snapshotEmptyHTML();
  const answers = (data.answers && typeof data.answers === 'object') ? data.answers : {};
  const versions = (data.material_versions && typeof data.material_versions === 'object') ? data.material_versions : {};
  const materials = Array.isArray(data.materials) ? data.materials : [];
  const posting = data.posting_url || '';
  const ts = data.timestamp || '';

  const sections = [];

  // Answers — the exact field values that will be submitted.
  const answerRows = _kvRows(answers);
  sections.push(
    `<div style="margin-top:2px;"><div style="font-weight:600;margin-bottom:2px;">Answers</div>`
    + (answerRows || `<div style="opacity:0.6;">No individual answers were recorded.</div>`)
    + `</div>`
  );

  // Documents / material versions.
  const matLabels = materials
    .map((m) => (m && (m.name || m.kind || m.id)) ? esc(String(m.name || m.kind || m.id)) : '')
    .filter(Boolean);
  const versionRows = _kvRows(versions);
  const docBits = [];
  if (matLabels.length) docBits.push(`<div style="opacity:0.9;">${matLabels.join(', ')}</div>`);
  if (versionRows) docBits.push(versionRows);
  sections.push(
    `<div style="margin-top:8px;"><div style="font-weight:600;margin-bottom:2px;">Documents</div>`
    + (docBits.length ? docBits.join('') : `<div style="opacity:0.6;">No document versions were recorded.</div>`)
    + `</div>`
  );

  // Posting + when it was recorded.
  const meta = [];
  if (posting) {
    meta.push(`<div style="display:flex;gap:10px;padding:6px 0;"><div style="flex:0 0 40%;opacity:0.7;">Posting</div>`
      + `<div style="flex:1 1 auto;word-break:break-all;"><a href="${esc(posting)}" target="_blank" rel="noopener noreferrer">${esc(posting)}</a></div></div>`);
  }
  if (ts) {
    meta.push(`<div style="display:flex;gap:10px;padding:6px 0;"><div style="flex:0 0 40%;opacity:0.7;">Recorded</div>`
      + `<div style="flex:1 1 auto;">${esc(_fmtTs(ts))}</div></div>`);
  }
  if (meta.length) {
    sections.push(`<div style="margin-top:8px;"><div style="font-weight:600;margin-bottom:2px;">Posting</div>${meta.join('')}</div>`);
  }

  return sections.join('');
}

function _fmtTs(ts) {
  try {
    const d = new Date(ts);
    if (!isNaN(d.getTime())) return d.toLocaleString();
  } catch { /* fall through */ }
  return String(ts);
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

  _loadCaveat().catch(e => console.debug('Silent catch in applicantRemote:', e));
  await _loadSessions().catch(e => console.debug('Silent catch in applicantRemote:', e));

  // Prefer the session that matches the requested application, if any.
  if (applicationId) {
    const match = _sessionList.find((s) => String(s.application_id) === String(applicationId));
    if (match) _setActiveSession(match);
  }
}

export function closeRemoteSession() {
  // A pending "Submitting in N… [Cancel]" hold must never survive the modal
  // being dismissed mid-countdown — cancel it before anything else so its
  // timer is cleared and the guarded `authorizeEngineFinish` call it was
  // waiting on is never reached.
  _cancelPendingHold();
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
