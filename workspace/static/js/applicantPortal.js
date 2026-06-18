// static/js/applicantPortal.js
//
// Pending-Actions Portal — the workspace's primary home-base surface. This is a
// STANDALONE, top-level rail entry (not buried in the Job Assistant chat modal):
// a single place that lists EVERYTHING awaiting the user across ALL of their
// job-search workspaces, with the right affordance per item:
//
//   • agent question / confirm  → answer inline → resolve.
//   • material review (cover letter / screening answer / resume)
//                               → "Review" deep-links to the Applications tab in
//                                 the Library (the redline surface). We don't
//                                 rebuild redline — we link to it.
//   • missing detail            → a small form to supply the value → the engine
//                                 acquires it and resumes the blocked application.
//   • account-creation / verification / emergency hand-off carrying a live
//                                 session → "Open live session" (uses the global
//                                 window.openApplicantRemoteSession if another
//                                 surface provides it, else falls back to the
//                                 session link from the item).
//   • emergency hand-off        → renders the pasteable hand-off values.
//   • digest decision           → "Review applications" deep-links to the digest.
//
// This is ADDITIVE and self-contained. It talks to the engine through the
// workspace proxy at /api/applicant/portal/* and never reaches the engine
// directly. A live count badge on the rail launcher reflects how many items are
// waiting. Degrades gracefully (a friendly "connect the engine" state) when the
// engine is unreachable.

import uiModule from './ui.js';
import digestModule from './emailLibrary/applicantDigest.js';
import remoteModule from './applicantRemote.js';
import { neverDoesList } from './applicantOnboarding.js';

const API = '/api/applicant/portal';
const BADGE_POLL_MS = 60000;
// localStorage marker: the newest notification timestamp (ms) the user has
// already been toasted about, so a backlog on first load doesn't spam and only
// genuinely-new arrivals pop a toast on later polls.
const NOTIF_SEEN_KEY = 'applicant_notif_last_toast_ts';

let _modalEl = null;
let _items = [];
// Informational notifications (digest ready / submitted / errors) folded into
// the queue alongside action-required rows. Action-required notifications are
// NOT folded — they are already represented by the pending-action rows above
// and clear when their action resolves, so folding them would double-track.
let _notifs = [];
let _loading = false;
let _badgePollIv = null;

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

async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
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

// ── Notification center (informational notifications + toasts) ────────────────
//
// The engine's in-app notifier captures every notification (the same ones that
// fan out to Discord/email when configured). We fold the INFORMATIONAL ones
// (digest ready / submitted / errors — anything that is NOT an open action) into
// the same queue as dismissible rows, and pop a transient browser toast (reusing
// ui.js's showToast) when a genuinely-new one arrives. The action-required ones
// are skipped here because the pending-action rows already represent them and
// they clear on resolve.

function _notifSeenTs() {
  try {
    const v = Number(window.localStorage.getItem(NOTIF_SEEN_KEY));
    return Number.isFinite(v) ? v : 0;
  } catch { return 0; }
}

function _setNotifSeenTs(ts) {
  try { window.localStorage.setItem(NOTIF_SEEN_KEY, String(ts || 0)); } catch { /* no-op */ }
}

function _notifTs(n) {
  const t = n && n.created_at ? Date.parse(n.created_at) : NaN;
  return Number.isFinite(t) ? t : 0;
}

// Informational = not an open action (those are the pending-action rows already).
function _isInformational(n) {
  return !!n && n.kind !== 'action' && !n.links_action;
}

// Fire a transient toast for each notification newer than the last-toasted
// marker, then advance the marker. On the very first load (no marker yet) we
// seed the marker to the newest item WITHOUT toasting, so a backlog never spams.
function _toastNew(notifs) {
  const infos = (notifs || []).filter(_isInformational);
  const newest = infos.reduce((mx, n) => Math.max(mx, _notifTs(n)), 0);
  let seen;
  try { seen = window.localStorage.getItem(NOTIF_SEEN_KEY); } catch { seen = null; }
  if (seen === null) {
    // First ever load — settle the backlog into the queue silently.
    _setNotifSeenTs(newest);
    return;
  }
  const since = _notifSeenTs();
  const fresh = infos
    .filter((n) => _notifTs(n) > since)
    .sort((a, b) => _notifTs(a) - _notifTs(b));
  // Cap the toast burst so a flurry never floods the corner.
  for (const n of fresh.slice(-3)) {
    const label = n.title || n.body || 'New notification';
    _toast(label);
    _maybeDesktopNotify(n);
  }
  if (newest > since) _setNotifSeenTs(newest);
}

// Optional desktop notification, mirroring calendar.js/tasks.js: only when the
// user has already granted permission. Never prompts, never blocks.
function _maybeDesktopNotify(n) {
  try {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    const body = (n.body && n.body !== n.title) ? String(n.body).slice(0, 140) : '';
    // eslint-disable-next-line no-new
    new Notification(n.title || 'Applicant', body ? { body } : undefined);
  } catch { /* desktop notifications are best-effort */ }
}

// ── Action taxonomy ──────────────────────────────────────────────────────────
//
// Plain-language labels + which affordance each engine pending-action kind gets.
// `affordance` is one of: 'review' | 'missing' | 'session' | 'answer' | 'digest'.
// The fallback (no entry) is a plain "Done" resolve.

const KINDS = {
  agent_question: {
    label: 'The assistant has a question for you',
    affordance: 'answer',
  },
  material_review: {
    label: 'A tailored document is ready for your review',
    hint: 'Open the side-by-side review before anything is sent.',
    affordance: 'review',
  },
  missing_attr: {
    label: 'A detail is needed before this can continue',
    affordance: 'missing',
  },
  missing_attribute: {
    label: 'A detail is needed before this can continue',
    affordance: 'missing',
  },
  emergency_handoff: {
    label: 'Needs you to take over in the live session',
    affordance: 'session',
  },
  account_human_step: {
    label: 'Needs you to create an account, then it can continue',
    affordance: 'session',
  },
  account_creation: {
    label: 'Needs you to create an account, then it can continue',
    affordance: 'session',
  },
  two_factor: {
    label: 'Google needs a two-factor sign-in to continue',
    hint: 'Tap continue, then approve the prompt on your phone within 60 seconds.',
    affordance: 'two_factor',
  },
  detection_blocker: {
    label: 'Paused on a verification check',
    affordance: 'session',
  },
  detection_clear: {
    label: 'Paused on a verification check',
    affordance: 'session',
  },
  digest_approval: {
    label: 'New roles are waiting for your decision',
    affordance: 'digest',
  },
  final_approval: {
    label: 'Ready for your final approval',
    hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.',
    affordance: 'final',
  },
  'request-final-approval': {
    label: 'Ready for your final approval',
    hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.',
    affordance: 'final',
  },
  request_final_approval: {
    label: 'Ready for your final approval',
    hint: 'Your materials are approved. Choose how to submit — nothing is sent until you do.',
    affordance: 'final',
  },
  error: {
    label: 'Hit a snag that needs a look',
    affordance: 'answer',
  },
};

function _meta(kind) {
  return KINDS[kind] || { label: (kind || 'Needs your attention').replace(/_/g, ' '), affordance: 'answer' };
}

// The engine carries a live-session URL under a few possible payload keys.
function _sessionUrl(payload) {
  if (!payload) return '';
  return payload.session_url || payload.live_session_url || payload.sessionUrl || '';
}

function _appId(item) {
  return item.application_id || (item.payload && item.payload.application_id) || '';
}

// Best human "Role · Company" label for an item, from whichever fields the
// engine carries on the action or its payload.
function _roleCompany(item) {
  const p = (item && item.payload) || {};
  const role = item.role || p.role || item.job_title || p.job_title || p.title || '';
  const company = item.company || p.company || p.company_name || p.employer || '';
  if (role && company) return `${role} · ${company}`;
  return role || company || item.title || '';
}

// ── Modal scaffold ────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-portal-modal';
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content" style="max-width:640px;width:96%;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Pending
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-portal-refresh" title="Refresh the list">Refresh</button>
          <button class="close-btn" id="applicant-portal-close" title="Close">✖</button>
        </div>
      </div>
      <div class="modal-body" id="applicant-portal-body" style="flex:1;overflow-y:auto;">
        <div id="applicant-portal-digest"></div>
        <div id="applicant-portal-pending"><div class="hwfit-loading">Loading…</div></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#applicant-portal-close').addEventListener('click', _close);
  modal.querySelector('#applicant-portal-refresh').addEventListener('click', () => { _load(true); _loadDigest(true); });
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = '';
  }
}

// ── Empty / offline states ────────────────────────────────────────────────────

function _renderOffline(body) {
  body.innerHTML = `
    <div style="padding:28px 18px;text-align:center;opacity:0.75;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;margin-bottom:10px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
      <div style="font-size:14px;margin-bottom:6px;">Not connected yet</div>
      <div style="font-size:12px;max-width:420px;margin:0 auto;">
        Connect a model in Settings to activate your job search. Once it's running,
        anything that needs your input will show up here.
      </div>
    </div>`;
}

function _neverDoesHTML() {
  // D4: reuse the EXACT "what Applicant never does" list from the OOBE (B1).
  const items = (Array.isArray(neverDoesList) && neverDoesList.length)
    ? neverDoesList
    : (window.applicantNeverDoesList || []);
  if (!items.length) return '';
  return `
    <div style="max-width:380px;margin:14px auto 0;text-align:left;border-top:1px solid var(--border);padding-top:12px;">
      <div style="font-size:11px;opacity:0.7;margin-bottom:4px;">What Applicant never does</div>
      <ul style="margin:0;padding-left:16px;font-size:11px;opacity:0.75;line-height:1.5;">
        ${items.map((t) => `<li>${esc(t)}</li>`).join('')}
      </ul>
    </div>`;
}

function _renderEmpty(body) {
  body.innerHTML = `
    <div style="padding:32px 18px;text-align:center;opacity:0.7;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.55;margin-bottom:10px;"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>
      <div style="font-size:14px;margin-bottom:4px;">You're all caught up</div>
      <div style="font-size:12px;max-width:380px;margin:0 auto;">
        Nothing needs your attention right now. When a document is ready to review
        or a detail is needed, it'll appear here.
      </div>
      ${_neverDoesHTML()}
    </div>`;
}

// ── Row rendering ──────────────────────────────────────────────────────────────

function _rowShell(item, inner) {
  const meta = _meta(item.kind);
  const title = item.title || meta.label;
  const where = item.campaign_name ? `<span style="opacity:0.55;">· ${esc(item.campaign_name)}</span>` : '';
  return `
    <div class="admin-card applicant-portal-row" data-action-id="${esc(item.id)}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;min-width:0;">
          <div style="font-weight:600;word-break:break-word;">${esc(title)}</div>
          <div style="opacity:0.6;font-size:11px;margin-top:1px;">${esc(meta.label)} ${where}</div>
        </div>
        <button type="button" class="cal-btn applicant-portal-resolve" data-action-id="${esc(item.id)}" title="Mark this as handled" style="flex-shrink:0;">Done</button>
      </div>
      <div class="applicant-portal-row-body" style="margin-top:8px;">${inner}</div>
    </div>`;
}

function _renderAnswer(item) {
  // Inline answer → resolve. Covers agent questions / confirms / soft errors.
  return `
    <div style="display:flex;gap:8px;align-items:flex-end;">
      <textarea class="applicant-portal-answer" rows="2" placeholder="Type your answer…"
                style="flex:1;resize:vertical;padding:7px 9px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:12px;"></textarea>
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-send-answer" data-action-id="${esc(item.id)}">Send</button>
    </div>`;
}

function _renderReview(item) {
  const hint = _meta(item.kind).hint || 'Open the side-by-side review.';
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">${esc(hint)}</div>
    <button type="button" class="cal-btn cal-btn-primary applicant-portal-review" data-app-id="${esc(_appId(item))}">Review</button>`;
}

function _renderMissing(item) {
  const p = item.payload || {};
  const name = p.attribute_name || p.name || '';
  const cid = item.campaign_id || '';
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">
      Provide the value below and the application will pick up where it left off.
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <input type="text" class="applicant-portal-missing-name" value="${esc(name)}" placeholder="Field"
             style="flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;" />
      <input type="text" class="applicant-portal-missing-value" placeholder="Value"
             style="flex:2;min-width:140px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;" />
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-save-missing"
              data-action-id="${esc(item.id)}" data-campaign-id="${esc(cid)}">Save &amp; continue</button>
    </div>`;
}

function _renderSession(item) {
  const url = _sessionUrl(item.payload);
  const appId = _appId(item);
  // Emergency hand-off also renders the pasteable values, if present.
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
      <div style="margin-bottom:8px;border:1px solid var(--border);border-radius:6px;padding:6px 10px;">
        <div style="font-size:11px;opacity:0.7;margin-bottom:2px;">Details to paste in</div>
        ${rows}
      </div>`;
  }
  let action = '';
  if (url || appId) {
    action = `<button type="button" class="cal-btn cal-btn-primary applicant-portal-session"
                data-app-id="${esc(appId)}" data-session-url="${esc(url)}">Open live session</button>`;
  } else {
    action = `<div style="font-size:12px;opacity:0.7;">When the live session is ready, a link will appear here.</div>`;
  }
  return handoff + action;
}

function _renderDigest(item) {
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">Review the matched roles and approve or skip each one.</div>
    <button type="button" class="cal-btn cal-btn-primary applicant-portal-digest">Review applications</button>`;
}

// Google 2FA hand-off: a held application needs the user to approve a Google
// two-factor prompt. "Continue" triggers the push and waits up to 60s for the
// on-device approval; on approval the application picks up where it stopped, on
// timeout the engine re-notifies and the row stays so the user can tap again.
function _renderTwoFactor(item) {
  const meta = _meta(item.kind);
  const appId = _appId(item);
  const retry = !!(item.payload && item.payload.retry);
  const hint = retry
    ? 'The last attempt timed out. Tap continue and approve the prompt on your phone within 60 seconds.'
    : (meta.hint || 'Tap continue, then approve the prompt on your phone within 60 seconds.');
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:8px;">${esc(hint)}</div>
    <button type="button" class="cal-btn cal-btn-primary applicant-portal-two-factor"
            data-app-id="${esc(appId)}" data-action-id="${esc(item.id)}"
            title="Send the two-factor prompt to your phone and continue">${retry ? 'Try Google again' : 'Continue Google sign-in'}</button>`;
}

// Final-submit approval (D2). Inline in the Portal: confirm the role/company and
// that materials are approved, then offer the two explicit choices that call the
// SAME engine endpoints the live-session modal uses — submit-self (open the live
// session) or authorize-the-engine-to-finish. The live session remains the path
// for takeover cases.
function _renderFinal(item) {
  const hint = _meta(item.kind).hint || 'Choose how to submit — nothing is sent until you do.';
  const label = _roleCompany(item);
  const appId = _appId(item);
  const who = label ? `<div style="font-weight:600;margin-bottom:2px;">${esc(label)}</div>` : '';
  return `
    ${who}
    <div style="font-size:12px;opacity:0.85;margin-bottom:4px;">
      <span style="color:var(--color-success,#4caf50);">Materials approved ✓</span>
    </div>
    <div style="font-size:12px;opacity:0.8;margin-bottom:8px;">${esc(hint)}</div>
    <div class="applicant-portal-final-caveat" style="font-size:11px;opacity:0.7;margin-bottom:8px;"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" class="cal-btn applicant-portal-final-self"
              data-app-id="${esc(appId)}" data-label="${esc(label)}"
              title="Open the live session and click submit yourself">I'll submit it myself (open live session)</button>
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-final-authorize"
              data-app-id="${esc(appId)}" data-action-id="${esc(item.id)}" data-label="${esc(label)}"
              title="Let the assistant click the final submit, just this once">Authorize Applicant to submit this</button>
    </div>`;
}

function _renderRowInner(item) {
  switch (_meta(item.kind).affordance) {
    case 'review': return _renderReview(item);
    case 'missing': return _renderMissing(item);
    case 'session': return _renderSession(item);
    case 'two_factor': return _renderTwoFactor(item);
    case 'digest': return _renderDigest(item);
    case 'final': return _renderFinal(item);
    case 'answer':
    default: return _renderAnswer(item);
  }
}

// An informational notification rendered as a dismissible queue row. It mirrors
// the action-row shell (.admin-card) but the affordance is a single "Dismiss"
// that calls the seen endpoint, since there is nothing to act on.
const _NOTIF_KIND_LABEL = {
  error: 'Heads up',
  digest: 'Update',
  info: 'Update',
};

function _renderNotifRow(n) {
  const accent = n.kind === 'error' ? 'var(--color-danger,#e06c6c)' : 'var(--border)';
  const tag = _NOTIF_KIND_LABEL[n.kind] || 'Update';
  const body = (n.body && n.body !== n.title) ? `<div style="opacity:0.7;font-size:11px;margin-top:2px;word-break:break-word;">${esc(n.body)}</div>` : '';
  return `
    <div class="admin-card applicant-portal-notif" data-notif-id="${esc(n.id)}" style="border-left:2px solid ${accent};">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;min-width:0;">
          <div style="font-weight:600;word-break:break-word;">${esc(n.title || tag)}</div>
          <div style="opacity:0.55;font-size:11px;margin-top:1px;">${esc(tag)}</div>
          ${body}
        </div>
        <button type="button" class="cal-btn applicant-portal-dismiss" data-notif-id="${esc(n.id)}" title="Dismiss this notification" style="flex-shrink:0;">Dismiss</button>
      </div>
    </div>`;
}

function _infoNotifs() {
  return (_notifs || []).filter(_isInformational);
}

function _renderList(body) {
  const infos = _infoNotifs();
  if (!_items.length && !infos.length) { _renderEmpty(body); return; }
  const actionRows = _items.map((it) => _rowShell(it, _renderRowInner(it))).join('');
  const notifRows = infos.map((n) => _renderNotifRow(n)).join('');
  const actionHdr = _items.length
    ? `<div style="font-size:11px;opacity:0.7;margin:2px 2px 2px;">${_items.length} item${_items.length === 1 ? '' : 's'} need${_items.length === 1 ? 's' : ''} your attention</div>`
    : '';
  const notifHdr = infos.length
    ? `<div style="font-size:11px;opacity:0.7;margin:10px 2px 2px;">Recent updates</div>`
    : '';
  body.innerHTML = `${actionHdr}${actionRows}${notifHdr}${notifRows}`;
  _wireRows(body);
}

// ── Deep links + global seams ──────────────────────────────────────────────────

function _openRedline(appId) {
  // Deep-link to the Applications tab in the Library (the existing redline
  // surface). We do NOT rebuild redline — we link to it, and hand it the
  // application id so the review opens WITHOUT the user typing an id (D1).
  try {
    if (window.documentModule && typeof window.documentModule.openLibrary === 'function') {
      window.documentModule.openLibrary({ tab: 'applicant', appId: appId || '' });
      _close();
      return;
    }
  } catch { /* fall through */ }
  _toast('Open the Library → Applications tab to review');
}

function _openDigest() {
  // The digest lives in the Email surface; deep-link there if available.
  try {
    const railEmail = document.getElementById('rail-email');
    if (railEmail) { railEmail.click(); _close(); return; }
  } catch { /* fall through */ }
  _toast('Open Email to review your matched roles');
}

function _openSession(appId, url) {
  // Prefer the global live-session seam if another surface provides it.
  try {
    if (typeof window.openApplicantRemoteSession === 'function') {
      window.openApplicantRemoteSession(appId, url);
      return;
    }
  } catch { /* fall through */ }
  if (url) {
    try { window.open(url, '_blank', 'noopener'); return; } catch { /* fall through */ }
  }
  _toast('No live session is available yet');
}

// ── Wiring ──────────────────────────────────────────────────────────────────

function _removeRow(host, id) {
  const row = host.querySelector(`.applicant-portal-row[data-action-id="${CSS.escape(id)}"]`);
  if (row) row.remove();
  _items = _items.filter((it) => String(it.id) !== String(id));
  _setBadge(_items.length + _infoNotifs().length);
  if (!host.querySelector('.applicant-portal-row') && !host.querySelector('.applicant-portal-notif')) {
    _renderEmpty(host);
  }
}

async function _doResolve(id) {
  await _post(`${API}/actions/${encodeURIComponent(id)}/resolve`, {});
}

function _wireRows(host) {
  // Done → resolve.
  host.querySelectorAll('.applicant-portal-resolve').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = '…';
      try {
        await _doResolve(id);
        _removeRow(host, id);
        _toast('Marked as handled');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not update that');
      }
    });
  });

  // Answer → resolve.
  host.querySelectorAll('.applicant-portal-send-answer').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      const row = btn.closest('.applicant-portal-row');
      const ta = row && row.querySelector('.applicant-portal-answer');
      const text = (ta && ta.value || '').trim();
      if (!text) { if (ta) ta.focus(); return; }
      btn.disabled = true;
      btn.textContent = '…';
      try {
        // The portal records the answer by resolving the action; the engine
        // attaches the user's response to the originating run.
        await _post(`${API}/actions/${encodeURIComponent(id)}/resolve`, { answer: text });
        _removeRow(host, id);
        _toast('Sent');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Send';
        _toast(e.message || 'Could not send that');
      }
    });
  });

  // Review → deep-link to the redline surface.
  host.querySelectorAll('.applicant-portal-review').forEach((btn) => {
    btn.addEventListener('click', () => _openRedline(btn.dataset.appId));
  });

  // Digest → deep-link to the digest.
  host.querySelectorAll('.applicant-portal-digest').forEach((btn) => {
    btn.addEventListener('click', () => _openDigest());
  });

  // Live session → global seam or link.
  host.querySelectorAll('.applicant-portal-session').forEach((btn) => {
    btn.addEventListener('click', () => _openSession(btn.dataset.appId, btn.dataset.sessionUrl));
  });

  // Google 2FA → trigger the push + wait up to 60s for on-device approval. On
  // approval the engine continues pre-fill (state leaves the account step) and
  // we drop the row; on timeout the engine re-notifies for a retry and the row
  // refreshes back in, so we leave the queue to the next reload.
  host.querySelectorAll('.applicant-portal-two-factor').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const appId = btn.dataset.appId;
      const actionId = btn.dataset.actionId;
      if (!appId) { _toast('No application is linked to this item yet'); return; }
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Waiting for your phone…';
      try {
        const data = await remoteModule.continueTwoFactor(appId);
        const state = String((data && data.state) || '').toUpperCase();
        if (state && state !== 'AWAITING_ACCOUNT_HUMAN_STEP') {
          if (actionId) _removeRow(host, actionId);
          _toast('Signed in — the application is continuing');
        } else {
          // Timed out; the engine emitted a fresh retry notification.
          btn.disabled = false;
          btn.textContent = 'Try Google again';
          _toast('That timed out — approve the prompt on your phone, then try again');
          _load(true);
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not continue the sign-in');
      }
    });
  });

  // Final submit (D2): submit-self opens the live session; authorize calls the
  // SAME engine endpoint the remote modal uses, behind an explicit confirm that
  // echoes the role/company + "materials approved ✓" (D5).
  host.querySelectorAll('.applicant-portal-final-self').forEach((btn) => {
    btn.addEventListener('click', () => {
      _openSession(btn.dataset.appId, '');
      _toast('Open the live session and click submit when you’re ready');
    });
  });
  host.querySelectorAll('.applicant-portal-final-authorize').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const appId = btn.dataset.appId;
      const actionId = btn.dataset.actionId;
      const label = btn.dataset.label || '';
      if (!appId) { _toast('No application is linked to this item yet'); return; }
      let message;
      try { message = remoteModule.authorizeConfirmMessage({ label }); }
      catch { message = `Authorize the assistant to submit ${label || 'this application'}? Materials approved ✓ — this cannot be undone.`; }
      const ok = await _confirm(message, { confirmText: 'Authorize & submit', cancelText: 'Cancel', danger: true });
      if (!ok) return;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Submitting…';
      try {
        await remoteModule.authorizeEngineFinish(appId);
        // Best-effort clear the pending row once the submit is authorized.
        if (actionId) { try { await _doResolve(actionId); } catch { /* row refreshes anyway */ } }
        _removeRow(host, actionId);
        _toast('Authorized — the assistant submitted the application');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not authorize the submission');
      }
    });
  });

  // Surface the honest best-effort / egress caveat (D3) on any final-approval
  // row. Best-effort: degrade silently if the engine doesn't return one.
  const caveatSlots = host.querySelectorAll('.applicant-portal-final-caveat');
  if (caveatSlots.length) {
    remoteModule.fetchCaveat().then((data) => {
      const line = data && (data.caveat || data.egress_caveat);
      if (!line) return;
      caveatSlots.forEach((slot) => { slot.textContent = String(line); });
    }).catch(() => { /* silent */ });
  }

  // Missing detail → acquire + resume.
  host.querySelectorAll('.applicant-portal-save-missing').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      const cid = btn.dataset.campaignId || null;
      const row = btn.closest('.applicant-portal-row');
      const nameEl = row && row.querySelector('.applicant-portal-missing-name');
      const valEl = row && row.querySelector('.applicant-portal-missing-value');
      const name = (nameEl && nameEl.value || '').trim();
      const value = (valEl && valEl.value || '').trim();
      if (!name) { if (nameEl) nameEl.focus(); return; }
      if (!value) { if (valEl) valEl.focus(); return; }
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Saving…';
      try {
        await _post(`${API}/missing-attribute`, {
          name, value, campaign_id: cid, action_id: id,
        });
        _removeRow(host, id);
        _toast('Saved — the application will continue');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not save that');
      }
    });
  });

  // Dismiss an informational notification → seen endpoint → drop the row.
  host.querySelectorAll('.applicant-portal-dismiss').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.notifId;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = '…';
      try {
        await _post(`${API}/notifications/${encodeURIComponent(id)}/seen`, {});
        _removeNotifRow(host, id);
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not dismiss that');
      }
    });
  });
}

function _removeNotifRow(host, id) {
  const row = host.querySelector(`.applicant-portal-notif[data-notif-id="${CSS.escape(id)}"]`);
  if (row) row.remove();
  _notifs = _notifs.filter((n) => String(n.id) !== String(id));
  _setBadge(_items.length + _infoNotifs().length);
  if (!host.querySelector('.applicant-portal-row') && !host.querySelector('.applicant-portal-notif')) {
    _renderEmpty(host);
  }
}

// ── Count badge ────────────────────────────────────────────────────────────────

function _setBadge(n) {
  const btn = document.getElementById('rail-portal');
  if (!btn) return;
  let badge = btn.querySelector('.rail-notes-badge');
  if (!n || n <= 0) {
    if (badge) badge.remove();
    return;
  }
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'rail-notes-badge';
    btn.appendChild(badge);
  }
  badge.textContent = n > 99 ? '99+' : String(n);
}

// Fetch the in-app notifications, toast any genuinely-new ones, and keep
// ``_notifs`` current for the queue. Never throws — a down engine just yields an
// empty set so the action rows still render. Returns the informational count.
async function _loadNotifs() {
  try {
    const data = await _fetchJSON(`${API}/notifications`);
    if (data && data.engine_available === false) { _notifs = []; return 0; }
    _notifs = (data && data.items) || [];
    _toastNew(_notifs);
  } catch {
    _notifs = [];
  }
  return _infoNotifs().length;
}

async function refreshBadge() {
  // Poll both feeds so new notifications toast and the badge reflects everything
  // waiting (open actions + undismissed informational notifications), even when
  // the modal is closed.
  let pendingCount = 0;
  try {
    const data = await _fetchJSON(`${API}/pending`);
    if (data && data.engine_available === false) { _setBadge(0); return; }
    pendingCount = (data && data.count) || 0;
  } catch {
    _setBadge(0);
    return;
  }
  const infoCount = await _loadNotifs();
  _setBadge(pendingCount + infoCount);
}

// ── Today's digest (home-base embed, C1) ────────────────────────────────────────
//
// Reuses the Email tool's digest module wholesale: its data accessors
// (listCampaigns/fetchDigest) and its row renderer (buildDigestRow), so a digest
// row looks and behaves identically here and in the Email tab. We only own the
// small section shell + the job-search picker.

let _digestCampaigns = [];
let _digestCampaignId = '';

function _digestHost() {
  return _modalEl && _modalEl.querySelector('#applicant-portal-digest');
}

function _digestSectionShell() {
  const picker = (_digestCampaigns.length > 1)
    ? `<select id="applicant-portal-digest-campaign" class="settings-select" title="Choose which job search to show today's roles for"
               style="flex:0 1 auto;margin-left:auto;max-width:200px;"></select>`
    : '';
  return `
    <div style="display:flex;align-items:center;gap:8px;margin:2px 2px 6px;">
      <span style="font-weight:600;font-size:12px;display:flex;align-items:center;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        Today's roles
      </span>
      ${picker}
    </div>
    <div id="applicant-portal-digest-body"></div>
    <div style="border-bottom:1px solid var(--border);margin:12px 0 2px;"></div>`;
}

function _renderDigestRows(payload) {
  const dbody = _modalEl && _modalEl.querySelector('#applicant-portal-digest-body');
  if (!dbody) return;
  dbody.innerHTML = '';
  const rows = (payload && Array.isArray(payload.rows)) ? payload.rows : [];
  if (!rows.length) {
    // Empty-day note with the engine's search rationale (mirrors the Email tab).
    let note = (payload && payload.note) ? String(payload.note)
      : 'No new roles cleared the bar today. The assistant keeps looking and will let you know.';
    const searched = payload && payload.searched ? String(payload.searched) : '';
    if (searched && note.indexOf(searched) === -1) note += ` Searched: ${searched}.`;
    dbody.innerHTML = `<div style="padding:6px 4px;font-size:12px;opacity:0.75;">${esc(note)}</div>`;
    return;
  }
  const ctx = {
    getCampaignId: () => _digestCampaignId,
    onResolved: () => { refreshBadge(); },
  };
  for (const row of rows) dbody.appendChild(digestModule.buildDigestRow(row, ctx));
}

async function _loadDigest(showSpinner) {
  const host = _digestHost();
  if (!host) return;
  if (showSpinner) host.innerHTML = '<div class="hwfit-loading" style="padding:8px 4px;font-size:12px;">Loading today’s roles…</div>';
  let campaigns = [];
  try { campaigns = await digestModule.listCampaigns(); } catch { campaigns = []; }
  _digestCampaigns = campaigns;
  if (!campaigns.length) {
    // No job search yet (or engine offline) — stay quiet; the pending list /
    // offline state already explains the connect-a-model path.
    host.innerHTML = '';
    return;
  }
  const remembered = digestModule.rememberedCampaignId();
  const known = new Set(campaigns.map((c) => String(c.id)));
  if (!_digestCampaignId || !known.has(_digestCampaignId)) {
    _digestCampaignId = known.has(remembered) ? remembered : String(campaigns[0].id);
  }
  host.innerHTML = _digestSectionShell();
  const sel = _modalEl.querySelector('#applicant-portal-digest-campaign');
  if (sel) {
    sel.innerHTML = campaigns.map((c) =>
      `<option value="${esc(c.id)}"${String(c.id) === _digestCampaignId ? ' selected' : ''}>${esc(c.name || c.id)}</option>`
    ).join('');
    sel.addEventListener('change', () => {
      _digestCampaignId = sel.value;
      _loadDigestRows();
    });
  }
  await _loadDigestRows();
}

async function _loadDigestRows() {
  const dbody = _modalEl && _modalEl.querySelector('#applicant-portal-digest-body');
  if (dbody) dbody.innerHTML = '<div class="hwfit-loading" style="padding:6px 4px;font-size:12px;">Loading…</div>';
  try {
    const payload = await digestModule.fetchDigest(_digestCampaignId);
    _renderDigestRows(payload);
  } catch (e) {
    if (!dbody) return;
    if (e && e.status === 409) {
      // 409 here means automated work isn't enabled yet (setup/onboarding still
      // in progress) — a normal pre-setup state, not a failure. The Portal is the
      // post-login home, so this is the common case before setup is finished;
      // point to setup instead of showing an alarming error.
      dbody.innerHTML = `<div style="padding:6px 4px;font-size:12px;opacity:0.7;">Finish setting up Applicant to start seeing matched roles here.</div>`;
    } else {
      dbody.innerHTML = `<div style="padding:6px 4px;font-size:12px;opacity:0.7;">Could not load today’s roles right now.</div>`;
    }
  }
}

// ── Load / open ────────────────────────────────────────────────────────────────

async function _load(showSpinner) {
  if (_loading) return;
  _loading = true;
  const body = _modalEl && _modalEl.querySelector('#applicant-portal-pending');
  if (body && showSpinner) body.innerHTML = '<div class="hwfit-loading">Loading…</div>';
  try {
    const data = await _fetchJSON(`${API}/pending`);
    if (data && data.engine_available === false) {
      if (body) _renderOffline(body);
      _setBadge(0);
      return;
    }
    _items = (data && data.items) || [];
    // Fold the informational notifications in alongside the action rows, and
    // toast any genuinely-new ones. Independent of the pending fetch, so a slow
    // inbox never blocks the action rows.
    await _loadNotifs();
    _setBadge(_items.length + _infoNotifs().length);
    if (body) _renderList(body);
  } catch (e) {
    if (body) _renderOffline(body);
  } finally {
    _loading = false;
  }
}

export async function openApplicantPortal() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  // Today's digest at the home base (C1) loads alongside the pending list; the
  // two are independent so a slow/offline digest never blocks the pending items.
  _loadDigest(true);
  await _load(true);
}

// ── Launcher + boot ────────────────────────────────────────────────────────────

function _wireLauncher() {
  const btn = document.getElementById('rail-portal');
  if (!btn || btn._applicantPortalWired) return;
  btn._applicantPortalWired = true;
  btn.addEventListener('click', () => openApplicantPortal());
}

function _boot() {
  _wireLauncher();
  // The rail button may be (re)rendered after boot; retry briefly so the
  // launcher always gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('rail-portal')?._applicantPortalWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
  // Seed the badge, then keep it fresh on a slow poll.
  refreshBadge();
  if (_badgePollIv) clearInterval(_badgePollIv);
  _badgePollIv = setInterval(refreshBadge, BADGE_POLL_MS);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantPortalModule = { openApplicantPortal, refreshBadge };

// Expose for deep-links / other modules without import coupling.
try { window.applicantPortalModule = applicantPortalModule; } catch { /* no-op */ }

export default applicantPortalModule;
