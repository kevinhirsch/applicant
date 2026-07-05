// static/js/applicantToday.js
//
// "Today" — a focus-mode run-through of the Pending Portal's own data, one
// decision at a time instead of a wall of rows (design-audit §4E/§5). This is
// a NEW LENS over EXISTING data/endpoints: it introduces no new engine
// endpoints, and it does not duplicate Portal's or Digest's logic — it reads
// the SAME owner-scoped front-door proxy Portal already reads
// (`/api/applicant/portal/pending`) and, for the two irreversible
// stop-boundary actions (Google 2FA continue, "authorize the assistant to
// submit"), calls the SAME exported helpers `applicantRemote.js` already
// exposes for exactly this reuse (its own header comment: "There is still
// exactly one client path to each stop-boundary endpoint" — Today must not
// grow a second one). Deep-link affordances (open the redline review, open
// today's digest) reuse the same cross-module seams Portal itself uses
// (`window.documentModule.openLibrary`, the `#rail-email` click) rather than
// rebuilding either surface.
//
// UX: open → fetch the pending queue → walk it as a stepped sequence, one
// card at a time, with a "N of M" progress indicator and Previous/Skip/Next
// navigation. Acting on a card's own affordance (approve/decline/answer/
// save/confirm/etc.) resolves it server-side (through the very same
// `/api/applicant/portal/actions/*` calls Portal's rows use) and the deck
// auto-advances to the next card. Reaching the end shows a warm completion
// state. This is ADDITIVE and self-contained — its own modal, its own hash
// token (`#today`) — and reuses ONLY the shared kit (.admin-card/.cal-btn/
// .ow-window) plus applicantCore.js's loading/error/empty/gated helpers, no
// new visual system.

import uiModule from './ui.js';
import remoteModule from './applicantRemote.js';
import {
  esc, _toast, _fetchJSON, _post,
  errText, loadingHTML, errorHTML, emptyHTML, gatedHTML, wireRetry,
} from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

// The exact same owner-scoped proxy the Pending Portal reads from — Today is
// a read-only alternate VIEW over it, never a second data path.
const API = '/api/applicant/portal';

let _modalEl = null;
let _modalA11yCleanup = null;
let _loading = false;

// The walkthrough deck: the pending items returned by the SAME `/pending`
// fetch Portal uses, and the current position within it.
let _items = [];
let _idx = 0;
let _state = 'loading'; // 'loading' | 'gated' | 'offline' | 'error' | 'ready'
let _errMsg = '';

// ── Plain-language per-kind copy ────────────────────────────────────────────
//
// A small, display-only mirror of the label/affordance mapping Portal keeps
// for its own rows (it is not exported, so this reproduces only the UI copy —
// not any engine logic — for the same kind identifiers the engine already
// emits). `affordance` selects which card body renderer runs below.

const KINDS = {
  agent_question: { label: 'I have a question for you', affordance: 'answer' },
  material_review: { label: 'A tailored document is ready for your review', hint: 'Open the side-by-side review before anything is sent.', affordance: 'review' },
  missing_attr: { label: 'I need one detail before I can continue', affordance: 'missing' },
  missing_attribute: { label: 'I need one detail before I can continue', affordance: 'missing' },
  emergency_handoff: { label: 'Needs you to take over in the live view', affordance: 'session' },
  account_human_step: { label: 'I need you to create an account — then I can continue', affordance: 'session' },
  account_creation: { label: 'I need you to create an account — then I can continue', affordance: 'session' },
  two_factor: { label: 'Google needs a two-factor sign-in to continue', hint: 'Tap ‘Continue Google sign-in’, then approve the prompt on your phone within 60 seconds.', affordance: 'two_factor' },
  detection_blocker: { label: 'Paused on a verification check', affordance: 'session' },
  detection_clear: { label: 'Paused on a verification check', affordance: 'session' },
  digest_approval: { label: 'New roles are waiting for your decision', affordance: 'digest' },
  final_approval: { label: 'Ready for your final approval', hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.', affordance: 'final' },
  'request-final-approval': { label: 'Ready for your final approval', hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.', affordance: 'final' },
  request_final_approval: { label: 'Ready for your final approval', hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.', affordance: 'final' },
  error: { label: 'I hit a snag and need your help', affordance: 'answer' },
  integral_change: { label: 'I think one of your core details changed — OK it before I use it', hint: 'Confirm the change to apply it, or keep your current value.', affordance: 'confirm_change' },
  onboarding_incomplete: { label: 'A few profile steps are left before your search can run', hint: 'Finish these to switch on your automated job search.', affordance: 'complete' },
};

function _meta(kind) {
  return KINDS[kind] || { label: 'Needs your attention', affordance: 'answer' };
}

function _appId(item) {
  return (item && (item.application_id || (item.payload && item.payload.application_id))) || '';
}

function _roleCompany(item) {
  const p = (item && item.payload) || {};
  const role = item.role || p.role || item.job_title || p.job_title || p.title || '';
  const company = item.company || p.company || p.company_name || p.employer || '';
  if (role && company) return `${role} · ${company}`;
  return role || company || item.title || '';
}

function _sessionUrl(payload) {
  if (!payload) return '';
  return payload.session_url || payload.live_session_url || payload.sessionUrl || '';
}

function _ageLabel(item) {
  return (item && item.age_label) ? ` · ${esc(item.age_label)}` : '';
}

function _urgencyBadge(item) {
  const u = item && item.urgency;
  if (u === 'overdue') {
    return ` <span style="background:var(--color-danger,#e06c6c);color:#fff;font-size:10px;font-weight:600;padding:1px 6px;border-radius:8px;margin-left:6px;">Overdue</span>`;
  }
  if (u === 'due_soon') {
    return ` <span style="background:var(--color-warning,#e0a96c);color:#000;font-size:10px;font-weight:600;padding:1px 6px;border-radius:8px;margin-left:6px;">Due soon</span>`;
  }
  return '';
}

// ── Modal scaffold ───────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-today-modal';
  modal.className = 'modal hidden ow-window';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'applicant-today-title');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:560px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header ow-titlebar">
        <div class="ow-controls">
          <button type="button" class="ow-close modal-close tap-exempt" id="applicant-today-close" aria-label="Close" title="Close">&times;</button>
        </div>
        <h4 class="ow-title" id="applicant-today-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          Today
        </h4>
        <div style="display:flex;gap:8px;align-items:center;">
          <span id="applicant-today-progress" style="font-size:11px;opacity:0.65;" aria-live="polite"></span>
          <button type="button" class="memory-toolbar-btn" id="applicant-today-refresh" aria-label="Refresh" title="Refresh today's items" style="width:26px;height:26px;padding:0;flex-shrink:0;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
      </div>
      <div class="modal-body" id="applicant-today-body" style="flex:1;overflow-y:auto;" aria-live="polite" aria-busy="false">
        <div class="hwfit-loading">Loading today's items…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  // initModalA11y (focus trap + Escape arbiter + focus restore) is (re-)wired
  // from openApplicantToday() on every open, not here — this element is
  // created once and reused across opens, so wiring it only at creation time
  // would leave every reopen after the first with no focus management at all
  // (a11y-deep audit item #1's "six modals lose focus mgmt after first
  // close" class of bug, mirrored here even though Today postdates that
  // audit — Portal/Vault/Mind/Remote re-init on every open; Today now does
  // too).
  modal.querySelector('#applicant-today-close').addEventListener('click', () => _requestClose());
  modal.querySelector('#applicant-today-refresh').addEventListener('click', () => _load(true));
  modal.addEventListener('click', (e) => { if (e.target === modal) _requestClose(); });
  _modalEl = modal;
  return modal;
}

// Does the current card carry unsent typed input? Mirrors the Portal/micro-
// interactions audit's #8 finding ("Backdrop-click closes the Portal over
// dirty inputs") — Today walks one card at a time so the check is scoped to
// whatever's on screen right now: the answer textarea, or either half of the
// missing-detail pair.
function _hasUnsavedInput() {
  const host = _body();
  if (!host) return false;
  const ta = host.querySelector('.applicant-today-answer');
  if (ta && (ta.value || '').trim()) return true;
  const val = host.querySelector('[data-role="value"]');
  if (val && (val.value || '').trim()) return true;
  return false;
}

// Backdrop-click and Escape both route through this instead of calling
// _close() directly, so a card with unsent typed input asks first rather
// than silently discarding it (same hazard class as micro-interactions #8).
async function _requestClose() {
  if (_hasUnsavedInput()) {
    const ok = await _confirm('Discard what you just typed and close Today?', {
      confirmText: 'Discard & close', cancelText: 'Keep editing', danger: true,
    });
    if (!ok) return;
  }
  _close();
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  clearHash('today');
}

export function closeApplicantToday() {
  _close();
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-today-body'); }
function _progressSlot() { return _modalEl && _modalEl.querySelector('#applicant-today-progress'); }

async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

// ── Deck navigation (the behavior worth testing for real) ──────────────────
//
// Pure-ish index arithmetic kept separate from rendering so it's easy to
// exercise directly: clamps to the deck's current bounds, never throws on an
// empty deck.

export function _clampIndex(idx, len) {
  if (!Number.isFinite(len) || len <= 0) return 0;
  if (!Number.isFinite(idx)) return 0;
  if (idx < 0) return 0;
  if (idx > len - 1) return len - 1;
  return idx;
}

function _goto(idx) {
  _idx = _clampIndex(idx, _items.length);
  _renderCurrent();
}

function _next() { _goto(_idx + 1); }
function _previous() { _goto(_idx - 1); }

// Removes the resolved/no-longer-relevant item at `id` from the deck and
// settles the index so the "next" card is whatever now sits at the same
// position (or the new last card, if the resolved item was last).
function _removeItem(id) {
  const removedAt = _items.findIndex((it) => String(it.id) === String(id));
  _items = _items.filter((it) => String(it.id) !== String(id));
  if (removedAt >= 0 && removedAt < _idx) _idx -= 1;
  _idx = _clampIndex(_idx, _items.length);
  _renderCurrent();
}

// ── Card body renderers, one per affordance ─────────────────────────────────
//
// Each renders into a detached wrapper and wires its own controls; every
// control that changes server state calls the SAME `/api/applicant/portal/*`
// endpoints (or the SAME exported `applicantRemote.js` helpers) the Pending
// Portal's own rows call — Today never invents a second path to engine state.

function _busyBtn(btn, label) {
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = label;
  return () => { btn.disabled = false; btn.textContent = orig; };
}

function _renderAnswer(wrap, item) {
  wrap.innerHTML = `
    <textarea class="applicant-today-answer" rows="3" placeholder="Type your answer…" aria-label="Your answer"
              style="width:100%;resize:vertical;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:13px;box-sizing:border-box;"></textarea>
    <div style="display:flex;justify-content:flex-end;margin-top:8px;">
      <button type="button" class="cal-btn cal-btn-primary" data-role="send">Send</button>
    </div>`;
  const sendBtn = wrap.querySelector('[data-role="send"]');
  const send = async () => {
    const btn = sendBtn;
    const ta = wrap.querySelector('.applicant-today-answer');
    const text = (ta && ta.value || '').trim();
    if (!text) { if (ta) ta.focus(); _toast('Type an answer first'); return; }
    const restore = _busyBtn(btn, '…');
    try {
      await _post(`${API}/actions/${encodeURIComponent(item.id)}/resolve`, { answer: text });
      _toast('Sent');
      _removeItem(item.id);
    } catch (err) {
      restore();
      _toast(errText(err));
    }
  };
  sendBtn.addEventListener('click', send);
  // Cmd/Ctrl+Enter submits, mirroring the chat composer's chord (a11y-deep
  // audit #16: "Portal answer textarea has no Cmd/Ctrl+Enter submit").
  wrap.querySelector('.applicant-today-answer').addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      send();
    }
  });
}

function _renderReview(wrap, item) {
  const hint = _meta(item.kind).hint || 'See exactly what I changed, side by side, before anything goes out.';
  wrap.innerHTML = `
    <div style="font-size:12px;opacity:0.8;margin-bottom:10px;">${esc(hint)}</div>
    <button type="button" class="cal-btn cal-btn-primary" data-role="review">Review the document</button>`;
  wrap.querySelector('[data-role="review"]').addEventListener('click', () => {
    const appId = _appId(item);
    try {
      if (window.documentModule && typeof window.documentModule.openLibrary === 'function') {
        window.documentModule.openLibrary({ tab: 'applicant', appId: appId || '' });
        _close();
        return;
      }
    } catch { /* fall through */ }
    _toast('Open Library to review this document');
  });
}

function _renderMissing(wrap, item) {
  const p = item.payload || {};
  const name = p.attribute_name || p.name || '';
  const cid = item.campaign_id || '';
  // When the engine already knows which attribute it needs, render that name
  // read-only instead of editable free text — a stray edit here would rename
  // the attribute and the engine would acquire the wrong key (micro-
  // interactions audit #30). Only fall back to an editable field when the
  // engine sent no name at all.
  const nameReadonly = !!name;
  wrap.innerHTML = `
    <div style="font-size:12px;opacity:0.8;margin-bottom:8px;">
      Give me this one detail and I’ll pick the application up where it left off.
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <input type="text" data-role="name" value="${esc(name)}" placeholder="What’s missing (e.g. desired salary)" aria-label="Field name"
             ${nameReadonly ? 'readonly title="Provided by me"' : ''}
             style="flex:1;min-width:120px;padding:7px 9px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;${nameReadonly ? 'opacity:0.75;' : ''}" />
      <input type="text" data-role="value" placeholder="Your answer" aria-label="Value"
             style="flex:2;min-width:140px;padding:7px 9px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;" />
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:8px;">
      <button type="button" class="cal-btn cal-btn-primary" data-role="save">Save &amp; continue</button>
    </div>`;
  const saveBtn = wrap.querySelector('[data-role="save"]');
  const save = async () => {
    const btn = saveBtn;
    const nameEl = wrap.querySelector('[data-role="name"]');
    const valEl = wrap.querySelector('[data-role="value"]');
    const nm = (nameEl && nameEl.value || '').trim();
    const val = (valEl && valEl.value || '').trim();
    if (!nm) { if (nameEl) nameEl.focus(); _toast('Name the field first'); return; }
    if (!val) { if (valEl) valEl.focus(); _toast('Type a value first'); return; }
    const restore = _busyBtn(btn, 'Saving…');
    try {
      await _post(`${API}/missing-attribute`, { name: nm, value: val, campaign_id: cid, action_id: item.id });
      _toast('Saved — the application will continue');
      _removeItem(item.id);
    } catch (err) {
      restore();
      _toast(errText(err));
    }
  };
  saveBtn.addEventListener('click', save);
  // Enter-to-save from the value field (a11y-deep audit #17: "Missing-detail
  // row: no Enter-to-save").
  wrap.querySelector('[data-role="value"]').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      save();
    }
  });
}

function _renderSession(wrap, item) {
  const url = _sessionUrl(item.payload);
  const appId = _appId(item);
  let handoff = '';
  const hv = item.payload && item.payload.handoff_values;
  if (hv && (Array.isArray(hv) ? hv.length : Object.keys(hv).length)) {
    const pairs = Array.isArray(hv)
      ? hv.map((v) => ({ k: v && v.label != null ? v.label : '', v: v && v.value != null ? v.value : v }))
      : Object.keys(hv).map((k) => ({ k, v: hv[k] }));
    const rows = pairs.map((pr) => `
      <div style="display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--border);padding:4px 0;font-size:12px;">
        <span style="opacity:0.7;">${esc(pr.k)}</span>
        <code style="user-select:all;word-break:break-all;text-align:right;">${esc(pr.v)}</code>
      </div>`).join('');
    handoff = `
      <div style="margin-bottom:10px;border:1px solid var(--border);border-radius:6px;padding:6px 10px;">
        <div style="font-size:11px;opacity:0.7;margin-bottom:2px;">Details to paste in</div>
        ${rows}
      </div>`;
  }
  wrap.innerHTML = handoff + ((url || appId)
    ? `<button type="button" class="cal-btn cal-btn-primary" data-role="session">Watch live</button>`
    : `<div style="font-size:12px;opacity:0.7;">When the live view is ready, the link will appear here.</div>`);
  const btn = wrap.querySelector('[data-role="session"]');
  if (btn) {
    btn.addEventListener('click', () => {
      try {
        if (typeof window.openApplicantRemoteSession === 'function') {
          window.openApplicantRemoteSession(appId, url);
          return;
        }
      } catch { /* fall through */ }
      if (url) { try { window.open(url, '_blank', 'noopener'); return; } catch { /* fall through */ } }
      _toast('No live view is available yet');
    });
  }
}

function _renderTwoFactor(wrap, item) {
  const meta = _meta(item.kind);
  const appId = _appId(item);
  const retry = !!(item.payload && item.payload.retry);
  const hint = retry
    ? 'The last attempt timed out. Tap ‘Try Google again’ and approve the prompt on your phone within 60 seconds.'
    : (meta.hint || 'Tap ‘Continue Google sign-in’, then approve the prompt on your phone within 60 seconds.');
  wrap.innerHTML = `
    <div style="font-size:12px;opacity:0.8;margin-bottom:10px;">${esc(hint)}</div>
    <button type="button" class="cal-btn cal-btn-primary" data-role="two-factor">${retry ? 'Try Google again' : 'Continue Google sign-in'}</button>`;
  const twoFactorBtn = wrap.querySelector('[data-role="two-factor"]');
  twoFactorBtn.addEventListener('click', async () => {
    const btn = twoFactorBtn;
    if (!appId) { _toast('No application is linked to this item yet'); return; }
    // A ticking countdown instead of a frozen "Waiting…" label for the up-to-
    // 60s wait (micro-interactions audit #46: "Two-factor wait: 60 seconds of
    // frozen label with no countdown or cancel") — the copy already promises
    // "within 60 seconds", so the label now counts down to match it and
    // signals the wait is still alive rather than possibly stuck.
    const orig = btn.textContent;
    btn.disabled = true;
    let remaining = 60;
    const tick = () => { btn.textContent = `Waiting for your phone… (${remaining}s)`; };
    tick();
    const countdown = setInterval(() => {
      remaining -= 1;
      if (remaining > 0) tick();
      else clearInterval(countdown);
    }, 1000);
    const restore = () => { clearInterval(countdown); btn.disabled = false; btn.textContent = orig; };
    try {
      const data = await remoteModule.continueTwoFactor(appId);
      const state = String((data && data.state) || '').toUpperCase();
      if (state && state !== 'AWAITING_ACCOUNT_HUMAN_STEP') {
        clearInterval(countdown);
        _toast('Signed in — the application is continuing');
        _removeItem(item.id);
      } else {
        restore();
        btn.textContent = 'Try Google again';
        _toast('That timed out — approve the prompt on your phone, then try again');
      }
    } catch (err) {
      restore();
      _toast(errText(err));
    }
  });
}

function _renderDigest(wrap) {
  wrap.innerHTML = `
    <div style="font-size:12px;opacity:0.8;margin-bottom:10px;">Review the matched roles and approve or skip each one.</div>
    <button type="button" class="cal-btn cal-btn-primary" data-role="digest">Review today's roles</button>`;
  wrap.querySelector('[data-role="digest"]').addEventListener('click', () => {
    try {
      const railEmail = document.getElementById('rail-email');
      if (railEmail) { railEmail.click(); _close(); return; }
    } catch { /* fall through */ }
    _toast('Your matched roles are in Email');
  });
}

function _renderConfirmChange(wrap, item) {
  const p = item.payload || {};
  const name = p.attribute_name || p.name || 'this detail';
  const current = (p.current_value == null || p.current_value === '') ? '(not set)' : p.current_value;
  const proposed = p.proposed_value || '';
  const reason = p.reason || _meta(item.kind).hint || '';
  wrap.innerHTML = `
    ${reason ? `<div style="font-size:12px;opacity:0.8;margin-bottom:8px;">${esc(reason)}</div>` : ''}
    <div style="font-size:12px;margin-bottom:10px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;">
      <div style="opacity:0.6;margin-bottom:2px;">${esc(name)}</div>
      <div>${esc(current)} &rarr; <strong>${esc(proposed)}</strong></div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" class="cal-btn cal-btn-primary" data-role="confirm">Confirm change</button>
      <button type="button" class="cal-btn" data-role="reject">Keep current</button>
    </div>`;
  const resolve = async (btn, apply, okToast) => {
    const restore = _busyBtn(btn, '…');
    try {
      await _post(`${API}/actions/${encodeURIComponent(item.id)}/resolve`, { apply });
      _toast(okToast);
      _removeItem(item.id);
    } catch (err) {
      restore();
      _toast(errText(err));
    }
  };
  const confirmBtn = wrap.querySelector('[data-role="confirm"]');
  const rejectBtn = wrap.querySelector('[data-role="reject"]');
  confirmBtn.addEventListener('click', () => resolve(confirmBtn, true, 'Change applied'));
  rejectBtn.addEventListener('click', () => resolve(rejectBtn, false, 'Kept your current value'));
}

function _renderFinal(wrap, item) {
  const hint = _meta(item.kind).hint || 'Choose how to submit — nothing is sent until you do.';
  const label = _roleCompany(item);
  const appId = _appId(item);
  wrap.innerHTML = `
    ${label ? `<div style="font-weight:600;margin-bottom:4px;">${esc(label)}</div>` : ''}
    <div style="font-size:12px;opacity:0.85;margin-bottom:4px;">
      <span style="color:var(--color-success,#4caf50);">Materials approved ✓</span>
    </div>
    <div style="font-size:12px;opacity:0.8;margin-bottom:8px;">${esc(hint)}</div>
    <div data-role="caveat" style="font-size:11px;opacity:0.7;margin-bottom:8px;"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" class="cal-btn" data-role="self" title="Open the live view and click submit yourself">I’ll submit it myself</button>
      <button type="button" class="cal-btn cal-btn-primary" data-role="authorize" title="I’ll click the final submit for you — just this once, only after you confirm">Let me submit it</button>
    </div>`;
  remoteModule.fetchCaveat().then((data) => {
    const line = data && (data.caveat || data.egress_caveat);
    if (!line) return;
    const slot = wrap.querySelector('[data-role="caveat"]');
    if (slot) slot.textContent = String(line);
  }).catch(() => { /* best-effort */ });
  wrap.querySelector('[data-role="self"]').addEventListener('click', () => {
    try {
      if (typeof window.openApplicantRemoteSession === 'function') { window.openApplicantRemoteSession(appId, ''); }
    } catch { /* fall through */ }
    _toast('Open the live view and click submit when you’re ready');
  });
  const authorizeBtn = wrap.querySelector('[data-role="authorize"]');
  authorizeBtn.addEventListener('click', async () => {
    const btn = authorizeBtn;
    if (!appId) { _toast('No application is linked to this item yet'); return; }
    let message;
    try { message = remoteModule.authorizeConfirmMessage({ label }); }
    catch { message = `Send ${label || 'this application'} now? You’ve approved everything in it. Once it’s submitted, I can’t take it back.`; }
    const ok = await _confirm(message, { confirmText: 'Authorize & submit', cancelText: 'Cancel', danger: true });
    if (!ok) return;
    const restore = _busyBtn(btn, 'Submitting…');
    try {
      await remoteModule.authorizeEngineFinish(appId);
      try { await _post(`${API}/actions/${encodeURIComponent(item.id)}/resolve`, {}); } catch { /* row clears anyway */ }
      _toast('Done — I submitted it. It’s on its way.');
      _removeItem(item.id);
    } catch (err) {
      restore();
      _toast(errText(err));
    }
  });
}

function _renderComplete(wrap, item) {
  const hint = _meta(item.kind).hint || 'Finish these to switch on your automated job search.';
  const missing = Array.isArray(item.missing) ? item.missing.filter(Boolean) : [];
  const list = missing.length
    ? `<ul style="margin:0 0 8px;padding-left:16px;font-size:12px;opacity:0.85;line-height:1.6;">${missing.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>`
    : '';
  wrap.innerHTML = `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">${esc(hint)}</div>
    ${list}
    <button type="button" class="cal-btn cal-btn-primary" data-role="finish">Finish your profile</button>`;
  wrap.querySelector('[data-role="finish"]').addEventListener('click', () => {
    try {
      if (typeof window.launchApplicantSetup === 'function') {
        window.launchApplicantSetup();
        _close();
        return;
      }
    } catch { /* fall through */ }
    _toast('Open Settings to finish setting up your profile');
  });
}

const _AFFORDANCE_RENDERERS = {
  answer: _renderAnswer,
  review: _renderReview,
  missing: _renderMissing,
  session: _renderSession,
  two_factor: _renderTwoFactor,
  digest: _renderDigest,
  confirm_change: _renderConfirmChange,
  final: _renderFinal,
  complete: _renderComplete,
};

// ── Card shell + generic controls (Done / Snooze) ───────────────────────────

function _renderCardShell(item) {
  const meta = _meta(item.kind);
  const title = item.title || meta.label;
  const where = item.campaign_name ? ` · ${esc(item.campaign_name)}` : '';
  const resolvable = meta.affordance !== 'complete';
  // Only show the generic per-kind label as a subtitle when the engine sent
  // its own distinct title — otherwise the same sentence would render twice
  // (the h3 title already fell back to meta.label above).
  const subtitleLabel = title === meta.label ? '' : esc(meta.label);
  const card = document.createElement('div');
  card.className = 'admin-card';
  card.style.padding = '16px';
  card.innerHTML = `
    <h3 id="applicant-today-card-title" tabindex="-1" style="font-size:15px;font-weight:600;word-break:break-word;margin:0;">${esc(title)}${_urgencyBadge(item)}</h3>
    <div style="opacity:0.6;font-size:11.5px;margin-top:2px;margin-bottom:14px;">${subtitleLabel}${_ageLabel(item)}${where}</div>
    <div data-role="card-body"></div>
    ${resolvable ? `
      <div style="display:flex;gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border);">
        <button type="button" class="cal-btn" data-role="snooze" title="Hide this until tomorrow morning">Snooze</button>
        <button type="button" class="cal-btn" data-role="done" title="Mark this as handled">Done</button>
      </div>` : ''}`;
  const bodySlot = card.querySelector('[data-role="card-body"]');
  const renderFn = _AFFORDANCE_RENDERERS[meta.affordance] || _renderAnswer;
  renderFn(bodySlot, item);
  if (resolvable) {
    const snoozeBtn = card.querySelector('[data-role="snooze"]');
    const doneBtn = card.querySelector('[data-role="done"]');
    snoozeBtn.addEventListener('click', async () => {
      const btn = snoozeBtn;
      const restore = _busyBtn(btn, '…');
      try {
        await _post(`${API}/actions/${encodeURIComponent(item.id)}/snooze`, {});
        _toast('Snoozed — I’ll bring it back tomorrow morning.');
        _removeItem(item.id);
      } catch (err) {
        restore();
        _toast(errText(err));
      }
    });
    doneBtn.addEventListener('click', async () => {
      const btn = doneBtn;
      const restore = _busyBtn(btn, '…');
      try {
        await _post(`${API}/actions/${encodeURIComponent(item.id)}/resolve`, {});
        _toast('Marked as handled');
        _removeItem(item.id);
      } catch (err) {
        restore();
        _toast(errText(err));
      }
    });
  }
  return card;
}

// ── Deck-level chrome (progress + Previous/Skip/Next) ───────────────────────

function _renderNav(host) {
  const nav = document.createElement('div');
  nav.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-top:14px;gap:8px;';
  nav.innerHTML = `
    <button type="button" class="cal-btn" data-role="prev">&larr; Previous</button>
    <button type="button" class="cal-btn" data-role="skip">Skip for now</button>
    <button type="button" class="cal-btn" data-role="next">Next &rarr;</button>`;
  const prevBtn = nav.querySelector('[data-role="prev"]');
  const skipBtn = nav.querySelector('[data-role="skip"]');
  const nextBtn = nav.querySelector('[data-role="next"]');
  prevBtn.disabled = _idx <= 0;
  nextBtn.disabled = _idx >= _items.length - 1;
  skipBtn.disabled = _items.length <= 1;
  prevBtn.addEventListener('click', _previous);
  nextBtn.addEventListener('click', _next);
  skipBtn.addEventListener('click', _next);
  host.appendChild(nav);
}

function _renderDone(host) {
  host.innerHTML = emptyHTML(
    "That's everything for today — nicely done.",
    'Come back tomorrow — anything new that needs you will show up right here.',
  );
}

// Every card/step swaps the body's entire innerHTML, which destroys whatever
// element held keyboard focus and drops it silently to <body> (a11y-deep
// audit #6: "Refresh/step/tab re-renders destroy the focused element").
// Re-anchor focus on a stable, always-present element after every such swap
// — the new card's own heading when one exists, otherwise the rendered
// empty/error/gated region — so a keyboard/AT user is never stranded.
function _focusRenderedRegion(host) {
  if (!host) return;
  const target = host.querySelector('#applicant-today-card-title')
    || host.querySelector('.applicant-empty')
    || host.querySelector('.applicant-error')
    || host.querySelector('.applicant-gated');
  if (!target) return;
  if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
  try { target.focus({ preventScroll: true }); } catch { try { target.focus(); } catch { /* no-op */ } }
}

function _renderCurrent() {
  const host = _body();
  if (!host) return;
  const slot = _progressSlot();
  if (!_items.length) {
    if (slot) slot.textContent = '';
    _renderDone(host);
    _focusRenderedRegion(host);
    return;
  }
  _idx = _clampIndex(_idx, _items.length);
  if (slot) slot.textContent = `${_idx + 1} of ${_items.length}`;
  host.innerHTML = '';
  host.appendChild(_renderCardShell(_items[_idx]));
  _renderNav(host);
  _focusRenderedRegion(host);
}

// ── Load / open ──────────────────────────────────────────────────────────────

function _renderOffline(host) {
  host.innerHTML = emptyHTML(
    "I can’t check in right now",
    "I’ve lost my connection. I’ll keep trying — anything that needs you will appear here as soon as I’m back.",
  );
}

function _renderGated(host, data) {
  const msg = (data && data.message)
    || "Finish setup — connect a model and fill in your profile — and I can start working for you.";
  host.innerHTML = gatedHTML(msg,
    '<button type="button" class="cal-btn cal-btn-primary" id="applicant-today-gated-setup">Finish setup</button>');
  const btn = host.querySelector('#applicant-today-gated-setup');
  if (btn) {
    btn.addEventListener('click', () => {
      try {
        if (typeof window.launchApplicantSetup === 'function') { window.launchApplicantSetup(); _close(); return; }
      } catch { /* fall through */ }
      _toast('Open Settings to finish setting up Applicant');
    });
  }
}

async function _load(showSpinner) {
  if (_loading) return;
  _loading = true;
  const host = _body();
  const slot = _progressSlot();
  if (slot) slot.textContent = '';
  if (host) host.setAttribute('aria-busy', 'true');
  if (host && showSpinner) host.innerHTML = loadingHTML("Loading today's items…");
  try {
    const data = await _fetchJSON(`${API}/pending`);
    if (!host) return;
    if (data && data.gated === true) {
      _state = 'gated';
      _items = []; _idx = 0;
      _renderGated(host, data);
      _focusRenderedRegion(host);
      return;
    }
    if (data && data.engine_available === false) {
      _state = 'offline';
      _items = []; _idx = 0;
      _renderOffline(host);
      _focusRenderedRegion(host);
      return;
    }
    _state = 'ready';
    _items = (data && data.items) || [];
    _idx = 0;
    _renderCurrent();
  } catch (e) {
    _state = 'error';
    _errMsg = errText(e);
    if (host) {
      host.innerHTML = errorHTML(_errMsg);
      wireRetry(host, () => _load(true));
      _focusRenderedRegion(host);
    }
  } finally {
    if (host) host.setAttribute('aria-busy', 'false');
    _loading = false;
  }
}

export async function openApplicantToday(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('today');
  // Keyboard a11y: trap focus, Escape to close, restore on close — re-wired
  // on every open (not just the first), the fix for a11y-deep audit #1.
  // Escape routes through _requestClose so it asks first when the current
  // card has unsent typed input (micro-interactions audit #8's hazard).
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _requestClose);
  await _load(true);
}

// ── Launcher + boot ──────────────────────────────────────────────────────────
//
// Wires #rail-today when present (added alongside this file's <script> tag in
// index.html — see that file's own comment for the reachability chain). Also
// self-wires defensively so `window.openApplicantToday()` / the `#today`
// deep-link are real even on a build where the nav edit hasn't landed yet.

function _wireLaunchers() {
  const rail = document.getElementById('rail-today');
  if (rail && !rail._applicantTodayWired) {
    rail._applicantTodayWired = true;
    rail.addEventListener('click', () => openApplicantToday());
  }
}

function _boot() {
  _wireLaunchers();
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLaunchers();
    if (document.getElementById('rail-today')?._applicantTodayWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing: '#today' deep-links straight into Today, mirroring every
// other surface's registration (applicantResults.js / applicantPortal.js).
registerRoute('today', { open: openApplicantToday, close: _close });

const applicantTodayModule = { openApplicantToday, closeApplicantToday };

try { window.applicantTodayModule = applicantTodayModule; } catch { /* no-op */ }
try { window.openApplicantToday = openApplicantToday; } catch { /* no-op */ }

export default applicantTodayModule;
