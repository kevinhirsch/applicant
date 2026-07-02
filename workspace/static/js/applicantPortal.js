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
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';
import {
  errText, loadingHTML, errorHTML, wireRetry, pollVisible,
} from './applicantCore.js';

const API = '/api/applicant/portal';
// Sibling owner-scoped proxies the home-base recap + momentum strip read from
// (surfacing-only; never the engine directly). The recap totals the activity
// run-history stats since the last visit; the momentum strip reads the results
// funnel. Both degrade to hidden/empty when their source is offline/gated.
const ACTIVITY_API = '/api/applicant/activity';
const RESULTS_API = '/api/applicant/results';
const BADGE_POLL_MS = 60000;
// localStorage marker: the newest notification timestamp (ms) the user has
// already been toasted about, so a backlog on first load doesn't spam and only
// genuinely-new arrivals pop a toast on later polls.
const NOTIF_SEEN_KEY = 'applicant_notif_last_toast_ts';
// localStorage marker: the wall-clock time (ms) of the user's PREVIOUS visit, so
// the "while you were away" recap can total up what happened since. Mirrors the
// NOTIF_SEEN_KEY get/set pattern below; a separate key so it never clobbers the
// toast bookkeeping.
const RECAP_SEEN_KEY = 'applicant_portal_recap_seen_ts';

let _modalEl = null;
let _modalA11yCleanup = null;
let _items = [];
// Informational notifications (digest ready / submitted / errors) folded into
// the queue alongside action-required rows. Action-required notifications are
// NOT folded — they are already represented by the pending-action rows above
// and clear when their action resolves, so folding them would double-track.
let _notifs = [];
let _loading = false;
// pollVisible's teardown handle — pauses the badge poll when the tab is hidden.
let _badgePollStop = null;
// Home-base recap bookkeeping. `_lastPendingCount` is the freshest count of items
// needing the user (set on every _load / badge refresh) so the recap's "— X need
// you" tail is accurate. `_recapSince` is the "last visit" cutoff captured ONCE per
// page session, so the recap stays stable across in-session refreshes.
let _lastPendingCount = 0;
let _recapSince = null;
let _recapSinceReady = false;
// The "I'm on it" empty-state proof-of-life line (task #10): the engine's own
// now/next agent-status snapshot, so the copy can name something concrete (the
// applied-today count, the next scheduled action) instead of a static sentence.
// Null until loaded / when there's nothing concrete to report — never fabricated.
let _agentPulse = null;



async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

// A toast that carries a single clickable action (reuses ui.js showToast's
// {action,onAction} slot). Falls back to a plain toast if the action slot is
// unavailable, so messaging never regresses. `onAction` opens the target surface
// directly instead of leaving the user with dead "go here" instruction text.
function _toastAction(msg, actionLabel, onAction) {
  try {
    uiModule.showToast(msg, {
      action: actionLabel,
      onAction: () => { try { onAction(); } catch { /* best-effort */ } },
    });
    return;
  } catch { /* fall through to a plain toast */ }
  _toast(msg);
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
// Android Chrome throws "Illegal constructor" for a page-created
// `new Notification()` once a service worker is registered (index.html
// always registers one) — route through the SW registration's
// showNotification() when one is actually controlling the page, falling
// back to the direct constructor otherwise (today's desktop-browser path).
function _maybeDesktopNotify(n) {
  try {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    const body = (n.body && n.body !== n.title) ? String(n.body).slice(0, 140) : '';
    const title = n.title || 'Applicant';
    const options = body ? { body } : undefined;
    const swReady = (navigator.serviceWorker && navigator.serviceWorker.controller)
      ? navigator.serviceWorker.ready
      : null;
    if (swReady) {
      swReady.then((reg) => reg.showNotification(title, options))
        .catch(() => { try { new Notification(title, options); } catch { /* best-effort */ } });
      return;
    }
    // eslint-disable-next-line no-new
    new Notification(title, options);
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
  integral_change: {
    label: 'A core detail was inferred and needs your OK',
    hint: 'Confirm the change to apply it, or keep your current value.',
    affordance: 'confirm_change',
  },
  onboarding_incomplete: {
    label: 'A few profile steps are still to do before your search can run',
    hint: 'Finish these to switch on your automated job search.',
    affordance: 'complete',
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

// ── Task metadata (aging + urgency) ───────────────────────────────────────────
//
// The engine now returns derived task metadata on each item (#295): age_label,
// urgency ('normal' | 'due_soon' | 'overdue'), and priority. We surface aging +
// an urgency badge inline. Items already arrive sorted highest-priority-first.

function _urgencyBadge(item) {
  const u = item && item.urgency;
  if (u === 'overdue') {
    return ` <span class="applicant-portal-badge" style="background:var(--color-danger,#e06c6c);color:#fff;font-size:10px;font-weight:600;padding:1px 6px;border-radius:8px;margin-left:6px;vertical-align:middle;">Overdue</span>`;
  }
  if (u === 'due_soon') {
    return ` <span class="applicant-portal-badge" style="background:var(--color-warning,#e0a96c);color:#000;font-size:10px;font-weight:600;padding:1px 6px;border-radius:8px;margin-left:6px;vertical-align:middle;">Due soon</span>`;
  }
  return '';
}

function _ageLabel(item) {
  const a = item && item.age_label;
  return a ? `<span style="opacity:0.7;">· ${esc(a)}</span>` : '';
}

// Digest-approval rows that can be cleared in one "approve all" batch.
function _digestApprovalItems() {
  return (_items || []).filter((it) => it && it.kind === 'digest_approval');
}

// ── Modal scaffold ────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-portal-modal';
  // FR-UIKIT-2-style adoption (audit #25): compose the vendored Window kit's
  // `ow-window` alongside the legacy `.modal`, mirroring the established pattern
  // in applicantRemote.js (`modal.className = 'modal hidden ow-window'`). The
  // class lands on the actual painted dialog so the shared kit chrome (frame /
  // radius / shadow / font) applies; existing `.modal hidden`/`.modal-content`
  // rules, handlers and the focus trap are preserved unchanged.
  modal.className = 'modal hidden ow-window';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Pending');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:640px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header ow-titlebar">
        <div class="ow-controls">
          <button type="button" class="ow-close modal-close tap-exempt" id="applicant-portal-close" aria-label="Close" title="Close">&times;</button>
        </div>
        <h4 class="ow-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Pending
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-portal-neverdoes" aria-label="What Applicant never does" aria-expanded="false" aria-controls="applicant-portal-neverdoes-panel" title="What Applicant never does — its safety limits" style="font-size:11px;padding:2px 8px;opacity:0.8;">What it never does</button>
          <button type="button" class="memory-toolbar-btn" id="applicant-portal-refresh" aria-label="Refresh the list" title="Refresh the list" style="width:26px;height:26px;padding:0;flex-shrink:0;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
      </div>
      <div class="modal-body" id="applicant-portal-body" style="flex:1;overflow-y:auto;">
        <div id="applicant-portal-greeting"></div>
        <div id="applicant-portal-recap"></div>
        <div id="applicant-portal-momentum"></div>
        <div id="applicant-portal-neverdoes-panel" style="display:none;"></div>
        <div id="applicant-portal-digest"></div>
        <div id="applicant-portal-pending"><div class="hwfit-loading">Loading…</div></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#applicant-portal-close').addEventListener('click', _close);
  modal.querySelector('#applicant-portal-refresh').addEventListener('click', () => { _load(true); _loadDigest(true); _loadMomentum(); });
  modal.querySelector('#applicant-portal-neverdoes').addEventListener('click', _toggleNeverDoesPanel);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

// Trust affordance (task #3): the "what Applicant never does" contract is always
// one tap away from the header, even when the queue is full — not only on the
// empty/gated view. Toggles a small inline panel that reuses _neverDoesHTML().
function _toggleNeverDoesPanel() {
  const panel = _modalEl && _modalEl.querySelector('#applicant-portal-neverdoes-panel');
  const btn = _modalEl && _modalEl.querySelector('#applicant-portal-neverdoes');
  if (!panel) return;
  const showing = panel.style.display !== 'none';
  if (showing) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    if (btn) btn.setAttribute('aria-expanded', 'false');
    return;
  }
  const inner = _neverDoesHTML();
  if (!inner) return; // no list available — leave the affordance inert rather than showing an empty box
  panel.innerHTML = inner;
  panel.style.display = '';
  if (btn) btn.setAttribute('aria-expanded', 'true');
}

// Audit #32: the composer sits in the same chat-area band the window is
// centered over, and on shorter viewports the window's bottom edge can reach
// the composer row (glass-on-glass in a steady state, clipping its text).
// Rather than editing the shared composer chrome (owned by the main chat
// surface, not Portal), Portal dims + neutralizes it ONLY while its own
// window is open, restoring the exact prior inline style on close so no
// other surface is left touched.
let _composerDimmed = false;
let _composerPrevStyle = null;
function _setComposerDimmed(on) {
  let bar;
  try { bar = document.querySelector('.chat-input-bar'); } catch { bar = null; }
  if (!bar) return;
  if (on) {
    if (_composerDimmed) return; // already dimmed — don't clobber the saved prior style
    _composerDimmed = true;
    _composerPrevStyle = bar.getAttribute('style');
    bar.style.transition = 'opacity 0.15s ease';
    bar.style.opacity = '0.35';
    bar.style.pointerEvents = 'none';
  } else if (_composerDimmed) {
    _composerDimmed = false;
    if (_composerPrevStyle === null) bar.removeAttribute('style');
    else bar.setAttribute('style', _composerPrevStyle);
    _composerPrevStyle = null;
  }
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = '';
  }
  _setComposerDimmed(false);
}

// ── Greeting (task #1) ────────────────────────────────────────────────────────
//
// A warm, time-aware, first-person line at the top of the home base. Calm,
// on-your-side voice; neutral ink; no exclamation spam. Aware of the pending
// count so it reassures when clear and orients when there's work waiting.

function _partOfDay() {
  const h = new Date().getHours();
  if (h < 12) return 'morning';
  if (h < 18) return 'afternoon';
  return 'evening';
}

function _greetingLine(pendingCount) {
  const when = _partOfDay();
  const n = Number(pendingCount) || 0;
  if (n <= 0) return `Good ${when}. You're all clear — I'll bring anything that needs you right here.`;
  if (n === 1) return `Good ${when}. One thing is waiting for you below.`;
  return `Good ${when}. ${n} things are waiting for you below.`;
}

function _renderGreeting(pendingCount) {
  const slot = _modalEl && _modalEl.querySelector('#applicant-portal-greeting');
  if (!slot) return;
  slot.innerHTML = `
    <div style="font-size:13px;color:var(--fg);opacity:0.9;margin:2px 2px 10px;line-height:1.4;">
      ${esc(_greetingLine(pendingCount))}
    </div>`;
}

// ── "While you were away" recap (task #1) ────────────────────────────────────
//
// A calm card at the top of the home base totalling what happened since the
// user's last visit. Sourced from the activity run-history proxy: each run
// carries a `stats` block (discovered / digest_rows / pipelines_started /
// handoffs / completed) — the same fields the Activity page's _statSummary reads.
// We sum those over runs newer than the stored "last visit" marker. First-person,
// neutral ink, no exclamation spam. Shows only when there's something to report;
// hides silently otherwise (the pending list already carries the offline/gated
// state, so a duplicate here would be noise).

function _recapHost() { return _modalEl && _modalEl.querySelector('#applicant-portal-recap'); }
function _momentumHost() { return _modalEl && _modalEl.querySelector('#applicant-portal-momentum'); }

// Capture the "since your last visit" cutoff exactly once per page session, then
// advance the stored marker to now so the NEXT visit measures from this one. On
// the very first ever load (no marker) there is no prior visit to summarise, so we
// seed silently and leave `_recapSince` null — mirroring _toastNew's backlog seed.
function _captureRecapSince() {
  if (_recapSinceReady) return;
  _recapSinceReady = true;
  let stored = null;
  try { stored = window.localStorage.getItem(RECAP_SEEN_KEY); } catch { stored = null; }
  const n = Number(stored);
  _recapSince = (stored === null || !Number.isFinite(n)) ? null : n;
  try { window.localStorage.setItem(RECAP_SEEN_KEY, String(Date.now())); } catch { /* no-op */ }
}

// Best timestamp (ms) for a run record, tolerating ISO strings and epoch s/ms.
function _runTs(run) {
  const raw = run && (run.created_at || run.finished_at || run.started_at
    || run.last_run_at || run.timestamp || run.ts);
  if (raw == null || raw === '') return 0;
  if (typeof raw === 'number') return raw < 1e12 ? raw * 1000 : raw;
  const t = Date.parse(raw);
  return Number.isNaN(t) ? 0 : t;
}

// Sum the run stats over runs newer than `since`. Runs without a usable timestamp
// are skipped rather than guessed into the window.
function _recapTotals(items, since) {
  const acc = { discovered: 0, shortlisted: 0, prefilled: 0, submitted: 0 };
  const add = (v) => { const n = Number(v); return Number.isFinite(n) && n > 0 ? n : 0; };
  for (const run of items) {
    if (!run || typeof run !== 'object') continue;
    const ts = _runTs(run);
    if (!ts || (since != null && ts <= since)) continue;
    const s = run.stats || {};
    acc.discovered += add(s.discovered);
    acc.shortlisted += add(s.digest_rows);
    acc.prefilled += add(s.pipelines_started);
    acc.submitted += add(s.completed);
  }
  return acc;
}

function _recapSentence(t, pending) {
  const parts = [];
  if (t.discovered > 0) parts.push(`reviewed ${t.discovered} posting${t.discovered === 1 ? '' : 's'}`);
  if (t.shortlisted > 0) parts.push(`shortlisted ${t.shortlisted}`);
  if (t.prefilled > 0) parts.push(`pre-filled ${t.prefilled}`);
  if (t.submitted > 0) parts.push(`submitted ${t.submitted}`);
  if (!parts.length) return '';
  const body = parts.length === 1
    ? parts[0]
    : `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`;
  const p = Number(pending) || 0;
  const tail = p > 0 ? ` — ${p} need${p === 1 ? 's' : ''} you.` : '.';
  return `Since your last visit, I ${body}${tail}`;
}

function _renderRecap(host, totals, pending) {
  const line = _recapSentence(totals, pending);
  if (!line) { host.innerHTML = ''; return; }
  host.innerHTML = `
    <div class="admin-card" style="margin:0 0 10px;padding:10px 12px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.55;"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">While you were away</span>
      </div>
      <div style="font-size:13px;color:var(--fg);line-height:1.45;">${esc(line)}</div>
    </div>`;
}

async function _loadRecap() {
  const host = _recapHost();
  if (!host) return;
  _captureRecapSince();
  // First-ever visit: no prior visit to summarise. Stay quiet.
  if (_recapSince == null) { host.innerHTML = ''; return; }
  let data;
  try {
    data = await _fetchJSON(`${ACTIVITY_API}/runs`);
  } catch {
    host.innerHTML = ''; // supplementary card — hide on any read failure
    return;
  }
  // Offline / gated → hide; the pending panel already surfaces those states.
  if (!data || data.engine_available === false || data.gated === true) { host.innerHTML = ''; return; }
  const items = (Array.isArray(data.items) ? data.items : []).filter((it) => it && typeof it === 'object');
  _renderRecap(host, _recapTotals(items, _recapSince), _lastPendingCount);
}

// ── Momentum strip (task #2) ─────────────────────────────────────────────────
//
// A compact one-line scoreboard sourced from the owner-scoped results/funnel
// proxy (NOT the admin surface). The engine's learning funnel is cumulative
// (matched → approved → submitted) with sources ranked by conversion — there is
// no weekly window or interview/"responses" aggregate exposed yet, so this reads
// as an honest running scoreboard (labelled "Your momentum", not "this week")
// rather than fabricating numbers. Neutral chrome, plain-language tooltips.

function _momentumEmpty(host) {
  host.innerHTML = `
    <div style="font-size:11.5px;opacity:0.6;margin:0 2px 10px;line-height:1.4;">
      Your momentum shows up here once you've submitted a few.
    </div>`;
}

function _renderMomentum(host, data) {
  const summary = (data && data.summary) || {};
  const sources = (data && Array.isArray(data.sources)) ? data.sources : [];
  const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  const chip = (value, label, tip) =>
    `<span title="${esc(tip)}"><strong>${esc(String(num(value)))}</strong> ${esc(label)}</span>`;
  const sep = '<span style="opacity:0.35;">·</span>';
  const parts = [
    chip(summary.total_submitted, 'submitted', 'Applications submitted so far.'),
    chip(summary.total_approved, 'approved', 'Roles you approved to move forward.'),
    chip(summary.total_matched, 'found', 'Roles matched to your criteria.'),
  ];
  // Best source: the engine ranks sources by conversion; the first named one wins.
  const best = sources.find((s) => s && s.source);
  let scoreboard = parts.join(sep);
  if (best) {
    scoreboard += `${sep}<span title="The source converting best for you." style="opacity:0.85;">best source: ${esc(String(best.source))}</span>`;
  }
  host.innerHTML = `
    <div class="admin-card" style="margin:0 0 10px;padding:8px 12px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;font-size:12px;color:var(--fg);">
      <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">Your momentum</span>
      <span style="display:inline-flex;flex-wrap:wrap;gap:2px 8px;align-items:center;">${scoreboard}</span>
    </div>`;
}

async function _loadMomentum() {
  const host = _momentumHost();
  if (!host) return;
  let data;
  try {
    data = await _fetchJSON(RESULTS_API);
  } catch {
    host.innerHTML = ''; // hide silently; the pending panel already covers offline
    return;
  }
  // Offline / gated → hide (the pending list already surfaces those states).
  if (!data || data.engine_available === false || data.gated === true) { host.innerHTML = ''; return; }
  if (data.has_data === false) { _momentumEmpty(host); return; }
  _renderMomentum(host, data);
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

// A GATED response (the engine is UP, but automated work is blocked until setup
// is finished) is NOT offline. Show the engine's own plain-language setup message
// so the owner knows what to finish, instead of the misleading "not connected".
function _renderGated(body, data) {
  const msg = (data && data.message)
    || 'Finish onboarding and configure your model and notification channels to enable automated work.';
  // Audit #28/#29/#30/#39: a gated state is a HEALTHY unconfigured state, not a
  // warning, so it gets the same neutral inbox mark the header/offline states
  // use (not a warning circle+!). The copy is Semibold + left-aligned within a
  // centered column (not thin/centered/blanket-opacity), a real "Finish setup"
  // CTA closes the dead end, and the trust list renders beneath the gate so it's
  // reachable even before there's anything to review. 24pt-rhythm padding.
  body.innerHTML = `
    <div style="padding:48px 24px 24px;text-align:center;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;margin-bottom:14px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
      <div style="max-width:400px;margin:0 auto;text-align:left;">
        <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:6px;">Finish setup to begin</div>
        <div style="font-size:12px;line-height:1.5;color:color-mix(in srgb, var(--fg) 68%, transparent);">${esc(msg)}</div>
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-portal-gated-setup" style="margin-top:14px;">Finish setup</button>
      </div>
      ${_neverDoesHTML()}
    </div>`;
  const setupBtn = body.querySelector('#applicant-portal-gated-setup');
  if (setupBtn) {
    setupBtn.addEventListener('click', () => {
      try {
        if (typeof window.launchApplicantSetup === 'function') {
          window.launchApplicantSetup();
          _close();
          return;
        }
      } catch { /* fall through */ }
      _toast('Open Settings to finish setting up Applicant');
    });
  }
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

// ── Agent pulse (task #10 data half) ─────────────────────────────────────────
//
// The empty state's "I'm on it" line should be genuinely informative, not just
// warmly worded. The owner-scoped activity snapshot proxy (`/api/applicant/
// activity/snapshot`, NOT the admin surface) already assembles the engine's own
// first-person now/next sentences — e.g. "Right now I'm working on your job
// search. I've started 3 of today's 10 applications." — so we prefer that over a
// static placeholder. Fetched independently (mirrors _loadRecap/_loadMomentum)
// so a slow/offline snapshot never blocks the pending list; falls back to the
// calm static line when there's nothing concrete yet (no campaign, engine
// offline/gated, or the engine omitted every field) — never fabricates activity.

function _agentPulseLine() {
  const now = _agentPulse && _agentPulse.now;
  const nowLine = (now && typeof now.sentence === 'string') ? now.sentence.trim() : '';
  if (nowLine) return nowLine;
  const next = _agentPulse && _agentPulse.next;
  const nextLine = (next && typeof next.sentence === 'string') ? next.sentence.trim() : '';
  if (nextLine) return nextLine;
  return 'Searching and preparing applications for you';
}

// Updates the pulse line in place (no full re-render) so a slower snapshot fetch
// never flashes/reflows the empty state that already painted with the fallback
// line. A no-op when the empty state (or the modal) isn't currently showing.
function _renderPulseLine() {
  const el = _modalEl && _modalEl.querySelector('#applicant-portal-pulse-text');
  if (el) el.textContent = _agentPulseLine();
}

async function _loadAgentPulse() {
  try {
    const data = await _fetchJSON(`${ACTIVITY_API}/snapshot`);
    _agentPulse = (data && data.engine_available !== false && data.has_activity !== false) ? data : null;
  } catch {
    _agentPulse = null; // supplementary line — hide behind the static fallback on any read failure
  }
  _renderPulseLine();
}

function _renderEmpty(body) {
  // Warm, agency + reassurance empty state (task #2): first-person, on-your-side,
  // with a quiet proof-of-life line so "clear" reads as "working" not "idle".
  // Audit #42/#44: hierarchy comes from real per-element tokens (a Semibold
  // heading at full ink, secondary copy via a color-mix tint) instead of a
  // blanket wrapper `opacity` that also washes out the status dot; copy is
  // left-aligned within a centered column, and padding follows a 24pt rhythm
  // (matches the gated state so the two read as one family).
  body.innerHTML = `
    <div style="padding:48px 24px 24px;text-align:center;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.55;margin-bottom:14px;"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>
      <div style="max-width:400px;margin:0 auto;text-align:left;">
        <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:4px;">You're all clear</div>
        <div style="font-size:12px;line-height:1.5;color:color-mix(in srgb, var(--fg) 68%, transparent);">
          Applicant is working in the background — I'll bring anything that needs you
          right here.
        </div>
        <div style="font-size:11px;color:color-mix(in srgb, var(--fg) 65%, transparent);margin-top:8px;display:inline-flex;align-items:center;gap:6px;">
          <span style="width:7px;height:7px;border-radius:50%;background:var(--color-success,#4caf50);display:inline-block;"></span>
          <span id="applicant-portal-pulse-text">${esc(_agentPulseLine())}</span>
        </div>
      </div>
      ${_neverDoesHTML()}
    </div>`;
}

// ── Row rendering ──────────────────────────────────────────────────────────────

function _rowShell(item, inner) {
  const meta = _meta(item.kind);
  const title = item.title || meta.label;
  const where = item.campaign_name ? `<span style="opacity:0.55;">· ${esc(item.campaign_name)}</span>` : '';
  // The onboarding-gap row is synthetic (no engine action to resolve) and clears
  // itself when the profile is complete, so it carries no "Done" affordance — its
  // only control is "Finish your profile".
  const resolvable = meta.affordance !== 'complete';
  // Snooze ("remind me tomorrow") is offered on every real (resolvable) row so the
  // user can defer anything off the home base until tomorrow. The synthetic
  // onboarding-gap row is not snoozable (it clears itself when the profile is done).
  const snoozeBtn = resolvable
    ? `<button type="button" class="cal-btn applicant-portal-snooze" data-action-id="${esc(item.id)}" title="Hide this until tomorrow morning" style="flex-shrink:0;">Snooze</button>`
    : '';
  const doneBtn = resolvable
    ? `<button type="button" class="cal-btn applicant-portal-resolve" data-action-id="${esc(item.id)}" title="Mark this as handled" style="flex-shrink:0;">Done</button>`
    : '';
  return `
    <div class="admin-card og-card applicant-portal-row" data-action-id="${esc(item.id)}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;min-width:0;">
          <div style="font-weight:600;word-break:break-word;">${esc(title)}${_urgencyBadge(item)}</div>
          <div style="opacity:0.6;font-size:11px;margin-top:1px;">${esc(meta.label)} ${_ageLabel(item)} ${where}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">${snoozeBtn}${doneBtn}</div>
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

// Held integral change (FR-FB-3 / FR-LEARN-4): a core detail was inferred from a
// passive input (a survey answer or a parsed résumé) and is NOT applied until the
// user confirms. Show the from → to and offer confirm (apply) or reject (keep).
function _renderConfirmChange(item) {
  const p = item.payload || {};
  const name = p.attribute_name || p.name || 'this detail';
  const current = (p.current_value == null || p.current_value === '') ? '(not set)' : p.current_value;
  const proposed = p.proposed_value || '';
  const reason = p.reason || _meta(item.kind).hint || '';
  return `
    ${reason ? `<div style="font-size:12px;opacity:0.8;margin-bottom:6px;">${esc(reason)}</div>` : ''}
    <div style="font-size:12px;margin-bottom:8px;padding:7px 9px;border:1px solid var(--border);border-radius:6px;">
      <div style="opacity:0.6;margin-bottom:2px;">${esc(name)}</div>
      <div>${esc(current)} &rarr; <strong>${esc(proposed)}</strong></div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-confirm-change" data-action-id="${esc(item.id)}">Confirm change</button>
      <button type="button" class="cal-btn applicant-portal-reject-change" data-action-id="${esc(item.id)}">Keep current</button>
    </div>`;
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

// Onboarding gap (the single persistent "finish your profile" row). The engine's
// own onboarding state drives it: it lists the SPECIFIC missing intake steps by
// their friendly labels and offers one button that re-launches the setup wizard.
// It clears on its own once every required section is filled (the proxy stops
// emitting it when missing_sections is empty) — no resolve needed, so we hide the
// generic "Done" on this row and the button is the only affordance.
function _renderComplete(item) {
  const hint = _meta(item.kind).hint || 'Finish these to switch on your automated job search.';
  const missing = Array.isArray(item.missing) ? item.missing.filter(Boolean) : [];
  const list = missing.length
    ? `<ul style="margin:0 0 8px;padding-left:16px;font-size:12px;opacity:0.85;line-height:1.6;">
         ${missing.map((m) => `<li>${esc(m)}</li>`).join('')}
       </ul>`
    : '';
  const stillText = missing.length
    ? `Still to do: ${missing.length} step${missing.length === 1 ? '' : 's'}.`
    : '';
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">${esc(hint)}</div>
    ${list}
    ${stillText ? `<div style="font-size:11px;opacity:0.6;margin-bottom:8px;">${esc(stillText)}</div>` : ''}
    <button type="button" class="cal-btn cal-btn-primary applicant-portal-finish-profile"
            title="Open setup and complete the remaining profile steps">Finish your profile</button>`;
}

function _renderRowInner(item) {
  switch (_meta(item.kind).affordance) {
    case 'complete': return _renderComplete(item);
    case 'review': return _renderReview(item);
    case 'missing': return _renderMissing(item);
    case 'session': return _renderSession(item);
    case 'two_factor': return _renderTwoFactor(item);
    case 'digest': return _renderDigest(item);
    case 'confirm_change': return _renderConfirmChange(item);
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
    <div class="admin-card og-card applicant-portal-notif" data-notif-id="${esc(n.id)}" style="border-left:2px solid ${accent};">
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
  // "Approve all N" appears only when there are 2+ digest-approval rows to clear
  // in one batch (#295 bulk action). It resolves exactly those rows server-side.
  const bulkN = _digestApprovalItems().length;
  const bulkBtn = bulkN > 1
    ? `<button type="button" class="cal-btn cal-btn-primary applicant-portal-approve-all" title="Approve and clear all matched-role items at once" style="font-size:11px;padding:2px 8px;">Approve all ${bulkN}</button>`
    : '';
  const actionHdr = _items.length
    ? `<div style="display:flex;align-items:center;gap:8px;margin:2px 2px 2px;">
         <span style="font-size:11px;opacity:0.7;">${_items.length} item${_items.length === 1 ? '' : 's'} need${_items.length === 1 ? 's' : ''} your attention</span>
         ${bulkBtn ? `<span style="margin-left:auto;">${bulkBtn}</span>` : ''}
       </div>`
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
  // No direct opener available — offer a one-tap action that lands them on the
  // Library surface instead of dead "go here" instruction text.
  _toastAction('Applicant review is in your Library', 'Open Library', () => {
    const rail = document.getElementById('rail-documents') || document.getElementById('rail-library');
    if (rail) { rail.click(); _close(); }
  });
}

function _openDigest() {
  // The digest lives in the Email surface; deep-link there if available.
  try {
    const railEmail = document.getElementById('rail-email');
    if (railEmail) { railEmail.click(); _close(); return; }
  } catch { /* fall through */ }
  // Fall back to a clickable toast that opens Email directly.
  _toastAction('Your matched roles are in Email', 'Open Email', () => {
    const railEmail = document.getElementById('rail-email');
    if (railEmail) { railEmail.click(); _close(); }
  });
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
  _renderGreeting(_items.length);
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

  // Snooze → "remind me tomorrow": defer the item off the home base until due.
  host.querySelectorAll('.applicant-portal-snooze').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = '…';
      try {
        await _post(`${API}/actions/${encodeURIComponent(id)}/snooze`, {});
        _removeRow(host, id);
        _toast('Snoozed — we’ll remind you tomorrow');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not snooze that');
      }
    });
  });

  // Approve all N → bulk-resolve every matched-role (digest_approval) row at once.
  host.querySelectorAll('.applicant-portal-approve-all').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const targets = _digestApprovalItems();
      if (!targets.length) return;
      // Group by campaign (the engine batch is campaign-scoped) and clear each.
      const byCampaign = {};
      for (const it of targets) {
        const cid = it.campaign_id || '';
        if (!cid) continue;
        (byCampaign[cid] = byCampaign[cid] || []).push(String(it.id));
      }
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Approving…';
      let cleared = 0;
      try {
        for (const cid of Object.keys(byCampaign)) {
          const data = await _post(`${API}/actions/resolve-bulk`, {
            campaign_id: cid, action_ids: byCampaign[cid],
          });
          const resolved = (data && data.resolved) || [];
          for (const rid of resolved) { _removeRow(host, rid); cleared += 1; }
        }
        _toast(cleared ? `Approved ${cleared} item${cleared === 1 ? '' : 's'}` : 'Nothing to approve');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(e.message || 'Could not approve all of those');
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

  // Confirm / reject a held integral change (FR-FB-3). Confirm applies the
  // proposed value through the engine's confirmation gate before clearing the item;
  // reject just clears it (keeps the current value).
  const _resolveChange = (selector, apply, okToast) => {
    host.querySelectorAll(selector).forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.actionId;
        const row = btn.closest('.applicant-portal-row');
        const buttons = row ? row.querySelectorAll('button') : [btn];
        buttons.forEach((b) => { b.disabled = true; });
        const orig = btn.textContent;
        btn.textContent = '…';
        try {
          await _post(`${API}/actions/${encodeURIComponent(id)}/resolve`, { apply });
          _removeRow(host, id);
          _toast(okToast);
        } catch (e) {
          buttons.forEach((b) => { b.disabled = false; });
          btn.textContent = orig;
          _toast(e.message || 'Could not update that');
        }
      });
    });
  };
  _resolveChange('.applicant-portal-confirm-change', true, 'Change applied');
  _resolveChange('.applicant-portal-reject-change', false, 'Kept your current value');

  // Finish your profile → re-launch the setup wizard (re-launchable from
  // anywhere via the global seam Settings also uses). Closes the portal so the
  // wizard takes the surface; the gap row disappears on the next load once the
  // remaining sections are filled.
  host.querySelectorAll('.applicant-portal-finish-profile').forEach((btn) => {
    btn.addEventListener('click', () => {
      try {
        if (typeof window.launchApplicantSetup === 'function') {
          window.launchApplicantSetup();
          _close();
          return;
        }
      } catch { /* fall through */ }
      _toast('Open Settings to finish setting up your profile');
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
    }).catch(e => console.error('Failed:', e));
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
  if (body && showSpinner) body.innerHTML = loadingHTML('Loading your pending items…');
  try {
    const data = await _fetchJSON(`${API}/pending`);
    if (data && data.gated === true) {
      if (body) _renderGated(body, data);
      _renderGreeting(0);
      _lastPendingCount = 0;
      const rh = _recapHost(); if (rh) rh.innerHTML = '';
      _setBadge(0);
      return;
    }
    if (data && data.engine_available === false) {
      if (body) _renderOffline(body);
      _renderGreeting(0);
      _lastPendingCount = 0;
      const rh = _recapHost(); if (rh) rh.innerHTML = '';
      _setBadge(0);
      return;
    }
    _items = (data && data.items) || [];
    _lastPendingCount = _items.length;
    // Fold the informational notifications in alongside the action rows, and
    // toast any genuinely-new ones. Independent of the pending fetch, so a slow
    // inbox never blocks the action rows.
    await _loadNotifs();
    _renderGreeting(_items.length);
    _setBadge(_items.length + _infoNotifs().length);
    if (body) _renderList(body);
    // The "while you were away" recap needs the fresh pending count for its tail;
    // fire it now (independent async fetch of the run history — never blocks).
    _loadRecap();
    // The empty state's proof-of-life line (task #10): independent fetch, same
    // fire-and-forget shape as the recap — it self-updates in place once loaded.
    _loadAgentPulse();
  } catch (e) {
    // A down/unreachable engine (network/timeout) is a normal "not connected yet"
    // state, not an error — keep the friendly offline copy. An actual HTTP/auth
    // failure is a real error: surface the plain-language reason (branched by
    // err.kind via errText) with a one-tap retry instead of a silent catch.
    const kind = e && e.kind;
    if (body) {
      if (kind === 'network' || kind === 'timeout') {
        _renderOffline(body);
      } else {
        body.innerHTML = errorHTML(errText(e), { retry: true });
        wireRetry(body, () => _load(true));
      }
    }
    _renderGreeting(0);
    _lastPendingCount = 0;
    const rh = _recapHost(); if (rh) rh.innerHTML = '';
  } finally {
    _loading = false;
  }
}

export async function openApplicantPortal() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _setComposerDimmed(true);
  // Keyboard a11y: trap focus, Escape to close, restore on close.
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  // Today's digest at the home base (C1) loads alongside the pending list; the
  // two are independent so a slow/offline digest never blocks the pending items.
  // The momentum strip (results funnel) loads independently too; the recap is
  // kicked off from within _load once the fresh pending count is known.
  _loadDigest(true);
  _loadMomentum();
  await _load(true);
}

// ── Launcher + boot ────────────────────────────────────────────────────────────

// Both launchers open the Portal: #rail-portal in the collapsed .icon-rail, and
// #tool-portal-btn the sidebar list-item (the only door when the wide .sidebar is
// expanded, where the icon-rail is display:none).
const _LAUNCHER_IDS = ['rail-portal', 'tool-portal-btn'];

function _wireLauncher() {
  _LAUNCHER_IDS.forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn || btn._applicantPortalWired) return;
    btn._applicantPortalWired = true;
    btn.addEventListener('click', () => openApplicantPortal());
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        openApplicantPortal();
      }
    });
  });
}

// #tool-applicant-gallery-btn is the same style of keyboard-unreachable
// sidebar .list-item <div> (role="button" in index.html, no native
// key-to-click behavior) but its click handler lives in applicantGallery.js,
// not here — dispatch a synthetic click to reuse that handler instead of
// duplicating it.
const _KEYDOWN_ACTIVATE_ONLY_IDS = ['tool-applicant-gallery-btn'];

function _wireKeydownActivation() {
  _KEYDOWN_ACTIVATE_ONLY_IDS.forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn || btn._applicantKeydownActivateWired) return;
    btn._applicantKeydownActivateWired = true;
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        btn.click();
      }
    });
  });
}

function _boot() {
  _wireLauncher();
  _wireKeydownActivation();
  // The rail button may be (re)rendered after boot; retry briefly so the
  // launcher always gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    _wireKeydownActivation();
    const allWired = _LAUNCHER_IDS.every((id) => {
      const btn = document.getElementById(id);
      return !btn || btn._applicantPortalWired;
    }) && _KEYDOWN_ACTIVATE_ONLY_IDS.every((id) => {
      const btn = document.getElementById(id);
      return !btn || btn._applicantKeydownActivateWired;
    });
    if (allWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
  // Seed the badge, then keep it fresh on a slow poll. pollVisible pauses the
  // interval while the tab is backgrounded (no wasted fetches) and resumes —
  // with an immediate refresh — when it comes back to the foreground.
  refreshBadge();
  if (_badgePollStop) { _badgePollStop(); _badgePollStop = null; }
  _badgePollStop = pollVisible(refreshBadge, BADGE_POLL_MS);
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
