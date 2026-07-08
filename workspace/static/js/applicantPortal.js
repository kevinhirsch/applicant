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
//                                 rebuild redline — we link to it. "Fix documents"
//                                 runs the engine's ensure-submittable auto-heal
//                                 inline (dark-engine audit item 2).
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
import { trustLine } from './applicantOnboarding.js';
import { renderApplicantPortalHealthBanner } from './applicantHealth.js';
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';
import {
  errText, loadingHTML, errorHTML, wireRetry, pollVisible,
} from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';
import { ensureSubmittable } from './applicantReachability.js';

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
// localStorage marker: the SET of one-time milestone ids already celebrated
// (e.g. "submitted_25"), so a round-number "applications sent" threshold is
// announced exactly once, ever — never re-shown on a later visit. Mirrors the
// `applicant_vault_*` naming convention applicantVault.js established this
// session for its own campaign-persistence key.
const MILESTONES_SEEN_KEY = 'applicant_portal_milestones_shown';

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
// The count the badge last actually painted (lens-10 audit #44): a transient
// fetch error must not erase a real "N waiting" signal, so refreshBadge's
// catch restores this instead of zeroing it. Kept current on every _setBadge
// call (including explicit-zero ones — those are real states, not errors).
let _lastBadgeCount = 0;
// The "I'm on it" empty-state proof-of-life line (task #10): the engine's own
// now/next agent-status snapshot, so the copy can name something concrete (the
// applied-today count, the next scheduled action) instead of a static sentence.
// Null until loaded / when there's nothing concrete to report — never fabricated.
let _agentPulse = null;
// The engine's real apply-readiness gate, read from the same `/pending` payload
// (product-honesty). The home base must NEVER claim it's "searching" while the
// gate is closed. Tri-state booleans start `null` (unknown: an older engine or a
// failed status read) so we neither falsely claim "running" nor hard-assert "not
// running". `apply_missing` is the ONE server-truth "what's left" list the wizard
// finish + chat also report, so all three agree.
let _gate = { automated_work_allowed: null, apply_ready: null, apply_missing: [] };

// The search is genuinely running only when the engine says automated work is
// allowed — the ONLY signal that means "I'm actually out there searching".
function _searchRunning() { return _gate.automated_work_allowed === true; }
// The gate is known-closed (setup unfinished): applying is blocked. `null`
// (unknown) is deliberately NOT closed, so an older engine degrades to today's
// calm empty state rather than a false "not running" alarm.
function _gateClosed() {
  return _gate.automated_work_allowed === false || _gate.apply_ready === false;
}
function _applyMissing() {
  return Array.isArray(_gate.apply_missing) ? _gate.apply_missing.filter(Boolean) : [];
}



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

// Lens-04 audit #65: `Number('')` and `Number('   ')` both coerce to 0 in JS
// (not NaN), so a corrupted/blank marker — a partial write, a stray manual
// edit, anything that isn't a genuine missing key — used to read back as a
// "since epoch zero" cutoff, making the ENTIRE backlog look newly-arrived and
// re-toasting all of it at once. Only a genuinely positive, finite timestamp
// counts as a usable marker; a missing OR corrupt one both return null so
// callers can treat them identically ("no marker yet" — seed silently,
// never re-toast the backlog) instead of silently defaulting to 0.
function _notifSeenTs() {
  try {
    const raw = window.localStorage.getItem(NOTIF_SEEN_KEY);
    if (raw == null || raw === '') return null;
    const v = Number(raw);
    return (Number.isFinite(v) && v > 0) ? v : null;
  } catch { return null; }
}

function _setNotifSeenTs(ts) {
  try { window.localStorage.setItem(NOTIF_SEEN_KEY, String(ts || 0)); } catch { /* no-op */ }
}

function _notifTs(n) {
  const t = n && n.created_at ? Date.parse(n.created_at) : NaN;
  return Number.isFinite(t) ? t : 0;
}

// Lens-10 audit #40: the router ships `created_at` on every row
// (app/routers/notifications.py `_shape`) but nothing ever rendered it —
// pending-action rows already show a server-computed `age_label` (`_ageLabel`
// below), so an error/update row gave no clue whether it happened 2 minutes
// or 20 hours ago (and it silently vanishes after 24h). Notifications carry
// no `age_label` field, so this mirrors that same short relative-time
// affordance client-side from `created_at`, reusing `_notifTs` (the exact
// parser `_toastNew` already relies on) rather than a new date library.
function _notifAgeText(n) {
  const t = _notifTs(n);
  if (!t) return '';
  // Lens-04 audit #66: `t` is the server's own `created_at`, but "now" here is
  // the CLIENT clock — a client running even slightly behind the server can
  // make a just-created item look like it happened in the future. Clamp
  // rather than blank the age out entirely: the item still deserves an
  // honest, if approximate, affordance, and "just now" reads truthfully for a
  // small negative skew instead of silently withholding real information.
  const deltaMs = Math.max(0, Date.now() - t);
  const mins = Math.floor(deltaMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Informational = not an open action (those are the pending-action rows already).
function _isInformational(n) {
  return !!n && n.kind !== 'action' && !n.links_action;
}

// Lens-10 audit #39: the inverse of _isInformational — a newly-arrived
// action-required row (a new 2FA wait, CAPTCHA/emergency handoff, or final
// approval). These are already represented as persistent rows in the
// pending-action list once loaded, so they are deliberately NOT folded into
// the informational notification queue (`_infoNotifs`/`_renderNotifRow`) —
// that would double-track them. But the *arrival signal* (toast + desktop
// notification) was being dropped entirely, so the single most urgent class
// of event produced no transient signal at all, only a badge bump on the
// next poll. This predicate exists so `_toastNew` can toast these too.
function _isActionArrival(n) {
  return !!n && (n.kind === 'action' || !!n.links_action);
}

// ── Quiet hours (lens-10 audit #45) ────────────────────────────────────────
//
// The engine's notifier already defers Discord/email pushes during the
// persisted quiet-hours window (FR-NOTIF-5), but treats in-app as "always
// silent" — so a tab left open overnight kept popping toasts AND OS-level
// desktop notifications straight through the user's configured quiet window.
// Read the SAME persisted window the Settings quiet-hours card already
// configures (no new engine endpoint: this is the existing
// `GET /api/applicant/setup/channels/quiet-hours` proxy over the engine's
// `setup_service.get_quiet_hours()`) and gate both `_toastNew` and
// `_maybeDesktopNotify` on it.
let _quietHoursCfg = null;
let _quietHoursFetchedAt = 0;
const QUIET_HOURS_TTL_MS = 5 * 60 * 1000;

// Best-effort, cached fetch — never throws, never blocks toasting on a slow
// or offline engine. A stale/absent cache degrades to "not quiet hours" (the
// pre-fix behavior) rather than silently swallowing every arrival forever.
async function _refreshQuietHoursCfg() {
  const now = Date.now();
  if (_quietHoursCfg && (now - _quietHoursFetchedAt) < QUIET_HOURS_TTL_MS) return _quietHoursCfg;
  try {
    const data = await _fetchJSON('/api/applicant/setup/channels/quiet-hours');
    if (data && typeof data === 'object') _quietHoursCfg = data;
  } catch { /* keep the last-known cache (or null) on a transient error */ }
  _quietHoursFetchedAt = now;
  return _quietHoursCfg;
}

function _parseHHMM(s) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(s == null ? '' : s));
  if (!m) return null;
  const mins = (Number(m[1]) % 24) * 60 + Number(m[2]);
  return Number.isFinite(mins) ? mins : null;
}

// Minutes-since-midnight "now", in the configured IANA zone when given and
// valid; falls back to the browser's local clock otherwise — the same
// graceful degrade the engine documents for an unrecognised zone name.
//
// Lens-04 audit #66 (client-clock trust): unlike the other timing decisions
// in this file, there is no server-provided timestamp anywhere in the
// quiet-hours payload (`{enabled,start,end,tz}`) to anchor "now" to — the
// gate is genuinely computed from the CLIENT's own clock. A client whose
// clock (not just its timezone) is wrong will therefore compute the wrong
// quiet-hours verdict with no way for this function to detect or correct
// that from data already in hand. Flagging this here rather than silently
// living with it: fully fixing this needs the quiet-hours proxy to start
// returning a `server_now` (or equivalent) field this function can anchor
// to instead of `Date.now()`.
function _minutesNowInTz(tz) {
  if (tz) {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: tz, hour12: false, hour: '2-digit', minute: '2-digit',
      }).formatToParts(new Date());
      const h = Number((parts.find((p) => p.type === 'hour') || {}).value);
      const m = Number((parts.find((p) => p.type === 'minute') || {}).value);
      if (Number.isFinite(h) && Number.isFinite(m)) return (h % 24) * 60 + m;
    } catch { /* unknown/invalid zone — fall through to local time */ }
  }
  const d = new Date();
  return d.getHours() * 60 + d.getMinutes();
}

// True when "now" falls inside the persisted quiet-hours window. Handles the
// overnight wrap (e.g. 22:00–07:00) the same way the engine's own window
// check does. A zero-length window (start === end) is inert, mirroring the
// engine's own "no quiet hours" treatment of that case.
function _isQuietHoursNow(cfg) {
  if (!cfg || !cfg.enabled) return false;
  const start = _parseHHMM(cfg.start);
  const end = _parseHHMM(cfg.end);
  if (start === null || end === null || start === end) return false;
  const nowMin = _minutesNowInTz(cfg.tz);
  if (start < end) return nowMin >= start && nowMin < end;
  return nowMin >= start || nowMin < end;
}

// Fire a transient toast for each notification newer than the last-toasted
// marker, then advance the marker. On the very first load (no marker yet, or
// a corrupted one — #65) we seed the marker to the newest item WITHOUT
// toasting, so a backlog never spams. Informational AND action-required
// arrivals share one seen-marker (lens-10 audit #39) so an action item
// already toasted once is never re-toasted on a later poll just because no
// new informational item arrived meanwhile.
async function _toastNew(notifs) {
  const all = notifs || [];
  const newest = all.reduce((mx, n) => Math.max(mx, _notifTs(n)), 0);
  const since = _notifSeenTs();
  if (since == null) {
    // No usable marker (missing OR corrupt, #65) — settle the backlog into
    // the queue silently, same as a genuine first-ever load.
    _setNotifSeenTs(newest);
    return;
  }
  // Lens-04 audit #62: claim the cutoff and advance the marker in this same
  // synchronous step — BEFORE the quiet-hours fetch below (a real await) or
  // any other yield point. The previous ordering read `since` only AFTER
  // that await, leaving a window where a second overlapping call (another
  // poll cycle, or another tab sharing this same localStorage key) could
  // read the identical stale marker and toast the very same arrivals a
  // second time. Claiming first means whichever call's synchronous read+
  // write executes first is authoritative for this batch; a second call —
  // this tab or another — sees the marker already moved forward and has
  // nothing left to toast.
  if (newest > since) _setNotifSeenTs(newest);
  const cfg = await _refreshQuietHoursCfg();
  // Lens-10 audit #45: quiet hours suppresses the arrival signal itself; the
  // marker was already advanced above so nothing already-seen re-toasts in a
  // burst once the window ends.
  if (_isQuietHoursNow(cfg)) return;
  const fresh = all
    .filter((n) => _notifTs(n) > since)
    .sort((a, b) => _notifTs(a) - _notifTs(b));
  const freshActions = fresh.filter(_isActionArrival);
  const freshInfo = fresh.filter((n) => !_isActionArrival(n));
  // Action-required arrivals toast in full — an "Open Pending" action (reusing
  // the same showToast action-slot the review/digest deep-link toasts already
  // use) rather than a plain message, since there is something to do about it.
  // These are deliberately NOT subject to the burst cap below: the most
  // urgent events must not be the ones squeezed out by an informational
  // flurry.
  for (const n of freshActions) {
    const label = n.title || n.body || 'New notification';
    _toastAction(label, 'Open Pending', () => { openApplicantPortal(); });
    _maybeDesktopNotify(n);
  }
  // Cap the informational toast burst so a flurry never floods the corner.
  for (const n of freshInfo.slice(-3)) {
    const label = n.title || n.body || 'New notification';
    _toast(label);
    _maybeDesktopNotify(n);
  }
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
    // Lens-10 audit #45: belt-and-suspenders quiet-hours gate using the
    // cached config `_toastNew` just refreshed — `_toastNew` already skips
    // calling this during the window, but guard here too so this function is
    // correct standalone if anything else ever calls it directly.
    if (_isQuietHoursNow(_quietHoursCfg)) return;
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
    label: 'I have a question for you',
    affordance: 'answer',
  },
  material_review: {
    label: 'A tailored document is ready for your review',
    hint: 'Open the side-by-side review before anything is sent.',
    affordance: 'review',
  },
  missing_attr: {
    label: 'I need one detail before I can continue',
    affordance: 'missing',
  },
  missing_attribute: {
    label: 'I need one detail before I can continue',
    affordance: 'missing',
  },
  emergency_handoff: {
    label: 'Needs you to take over in the live view',
    affordance: 'session',
  },
  account_human_step: {
    label: 'I need you to create an account — then I can continue',
    affordance: 'session',
  },
  account_creation: {
    label: 'I need you to create an account — then I can continue',
    affordance: 'session',
  },
  two_factor: {
    label: 'Google needs a two-factor sign-in to continue',
    hint: 'Tap ‘Continue Google sign-in’, then approve the prompt on your phone within 60 seconds.',
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
    label: 'I hit a snag and need your help',
    affordance: 'answer',
  },
  integral_change: {
    label: 'I think one of your core details changed — OK it before I use it',
    hint: 'Confirm the change to apply it, or keep your current value.',
    affordance: 'confirm_change',
  },
  onboarding_incomplete: {
    label: 'A few profile steps are left before your search can run',
    hint: 'Finish these to switch on your automated job search.',
    affordance: 'complete',
  },
};

function _meta(kind) {
  return KINDS[kind] || { label: 'Needs your attention', affordance: 'answer' };
}

// The engine carries a live-session URL under a few possible payload keys.
function _sessionUrl(payload) {
  if (!payload) return '';
  return payload.session_url || payload.live_session_url || payload.sessionUrl || '';
}

function _appId(item) {
  return item.application_id || (item.payload && item.payload.application_id) || '';
}

// Resume-backoff countdown (dark-engine audit #78): a blocked application is
// re-driven at most every ~300s, so right after the owner clears a blocker
// (answers a question / supplies a missing detail) it can sit for up to 5
// minutes with no sign anything will happen. Fetches the real countdown and
// returns a short, honest suffix to append to the "Sent"/"Saved" toast — or ''
// when there's nothing to report (not currently backed off, or the read
// failed). Best-effort only: never blocks or fails the toast it's appended to.
async function _resumeCountdownSuffix(appId) {
  if (!appId) return '';
  try {
    const data = await _fetchJSON(`/api/applicant/tracker/applications/${encodeURIComponent(appId)}/resume-status`);
    if (data && data.status === 'blocked' && data.next_retry_at) {
      const when = new Date(data.next_retry_at);
      if (!isNaN(when.getTime())) {
        const label = when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        return ` — I'll pick this back up by ${label}`;
      }
    }
  } catch { /* best-effort — the toast still lands without the countdown */ }
  return '';
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
  modal.setAttribute('aria-label', 'Waiting on you — pending actions');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:640px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header ow-titlebar">
        <div class="ow-controls">
          <button type="button" class="ow-close modal-close tap-exempt" id="applicant-portal-close" aria-label="Close" title="Close">&times;</button>
        </div>
        <h4 class="ow-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Waiting on you
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-portal-neverdoes" aria-label="You’re in control" aria-expanded="false" aria-controls="applicant-portal-neverdoes-panel" title="You approve every application before it’s sent" style="font-size:11px;padding:2px 8px;opacity:0.8;">You’re in control</button>
          <button type="button" class="memory-toolbar-btn" id="applicant-portal-refresh" aria-label="Refresh the list" title="Check for anything new right now" style="width:26px;height:26px;padding:0;flex-shrink:0;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
      </div>
      <div class="modal-body" id="applicant-portal-body" style="flex:1;overflow-y:auto;">
        <div id="applicant-portal-greeting"></div>
        <!-- P1-3 (#655): honest health panel banner — renders ONLY when the
             engine is unreachable or a LOAD-BEARING capability is degraded
             (postgres/résumé renderer/browser); empty otherwise. See
             applicantHealth.js renderApplicantPortalHealthBanner. -->
        <div id="applicant-portal-health"></div>
        <div id="applicant-portal-today"></div>
        <div id="applicant-portal-streak"></div>
        <div id="applicant-portal-recap"></div>
        <div id="applicant-portal-momentum"></div>
        <div id="applicant-portal-neverdoes-panel" style="display:none;"></div>
        <div id="applicant-portal-digest"></div>
        <div id="applicant-portal-pending"><div class="hwfit-loading">Checking what needs you…</div></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#applicant-portal-close').addEventListener('click', _close);
  modal.querySelector('#applicant-portal-refresh').addEventListener('click', () => { _load(true); _loadDigest(true); _loadMomentum(); _loadStreak(); _loadHealth(); });
  modal.querySelector('#applicant-portal-neverdoes').addEventListener('click', _toggleNeverDoesPanel);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

// Trust affordance (task #3): the "you're in control" statement is always one
// tap away from the header, even when the queue is full — not only on the
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
  // Hash routing (audit #7): only clears when the hash is actually ours —
  // safe to call unconditionally even when Portal closed for an unrelated
  // reason (row action, click-outside) while some other hash (a session id,
  // an in-flight #email= deep link) is current.
  clearHash('portal');
}

// Exported so other modules/tests can close Portal without reaching into its
// private state, mirroring openApplicantPortal's public export.
export function closeApplicantPortal() {
  _close();
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
  if (n <= 0) {
    // Product-honesty: "you're all clear" implies I'm out there working. Only say
    // it when the search is genuinely running; if the gate is closed, tell the
    // truth so an empty queue never reads as a search that isn't happening.
    if (_gateClosed()) return `Good ${when}. Your search isn’t running yet — let’s finish setting it up.`;
    return `Good ${when}. You’re all clear — I’ll bring anything that needs you right here.`;
  }
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
//
// Lens-04 audit #63: a plain read-then-write here is a classic read-modify-write
// race the moment TWO tabs/windows of the same session are open — each can call
// this near-simultaneously, each reads the SAME old marker, and whichever one's
// write lands last silently clobbers the other's already-claimed cursor (the
// interval between them either drops out of both recaps, or — depending on
// ordering — gets shown to both). Claim it inside a Web Locks cross-tab mutual-
// exclusion section when the browser supports one; a browser without it falls
// back to the plain read+write below, which is still safe WITHIN a single tab
// since `_recapSinceReady` already prevents a second same-tab capture.
function _captureRecapSinceUnlocked() {
  let stored = null;
  try { stored = window.localStorage.getItem(RECAP_SEEN_KEY); } catch { stored = null; }
  const n = Number(stored);
  _recapSince = (stored == null || stored === '' || !Number.isFinite(n) || n <= 0) ? null : n;
  try { window.localStorage.setItem(RECAP_SEEN_KEY, String(Date.now())); } catch { /* no-op */ }
}

function _captureRecapSince() {
  if (_recapSinceReady) return Promise.resolve();
  _recapSinceReady = true;
  let locks = null;
  try { locks = (typeof navigator !== 'undefined' && navigator && navigator.locks) || null; } catch { locks = null; }
  if (locks && typeof locks.request === 'function') {
    try {
      return Promise.resolve(locks.request(`${RECAP_SEEN_KEY}:lock`, () => { _captureRecapSinceUnlocked(); }))
        .catch(() => { _captureRecapSinceUnlocked(); });
    } catch { /* fall through to the unlocked path below */ }
  }
  _captureRecapSinceUnlocked();
  return Promise.resolve();
}

// Lens-04 audit #66 (client-clock trust): the persisted "last visit" marker
// above is written from the CLIENT's clock, but the recap totals it gates
// (`_recapTotals`) are computed against SERVER-timestamped activity runs
// (`_runTs`, from the SAME `/activity/runs` payload this function receives).
// Comparing a client-clock cutoff against server timestamps means a skewed
// client clock can drop real activity (client clock running ahead) or
// re-show/double-count it (client clock running behind). Once the run data
// is in hand, re-anchor the stored marker to the newest SERVER timestamp
// actually observed — a real value already present in this payload — rather
// than trusting the client clock any further. Only ever moves the marker
// FORWARD (never earlier than what's already stored), so it can't reopen a
// window another tab already consumed; a client clock running AHEAD of the
// server still isn't fully correctable this way — that would need a real
// `server_now` field on this payload, which doesn't exist today.
function _reanchorRecapMarker(items) {
  const newestServerTs = (items || []).reduce((mx, r) => Math.max(mx, _runTs(r)), 0);
  if (!newestServerTs) return; // nothing server-timestamped in this payload to anchor to
  try {
    const current = Number(window.localStorage.getItem(RECAP_SEEN_KEY));
    const anchored = Number.isFinite(current) ? Math.max(current, newestServerTs) : newestServerTs;
    window.localStorage.setItem(RECAP_SEEN_KEY, String(anchored));
  } catch { /* no-op — best-effort refinement only */ }
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
  await _captureRecapSince();
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
  _reanchorRecapMarker(items); // #66: prefer the server's own timeline once we have one
  _renderRecap(host, _recapTotals(items, _recapSince), _lastPendingCount);
}

// ── Supportive streak ────────────────────────────────────────────────────────
//
// "Days in a row the agent has been actively working", sourced from the SAME
// run-history proxy _loadRecap reads (`/api/applicant/activity/runs` — one
// record per scheduler tick, via `_runTs`) grouped into calendar days and
// counted backward from today. One day's grace: if today hasn't produced a
// run YET, yesterday still anchors the count (a tick simply may not have
// fired yet today) rather than reading as broken. Deliberately NOT punitive:
// there is no broken-streak state, no red/warning styling, and no callout
// when a day is missed — below a 2-day streak (or on any miss) the line just
// quietly stops rendering, the same "reset without comment" shape as the
// notification-seen/recap-seen markers above.

const _ONE_DAY_MS = 24 * 60 * 60 * 1000;

function _streakHost() { return _modalEl && _modalEl.querySelector('#applicant-portal-streak'); }

// A local calendar-day key (not UTC) — good enough as a Set key, no formatting
// contract to keep, so no zero-padding needed.
function _dayKey(ts) {
  const d = new Date(ts);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function _computeStreakDays(items) {
  const days = new Set();
  let newestServerTs = 0;
  for (const run of items) {
    if (!run || typeof run !== 'object') continue;
    const ts = _runTs(run);
    if (ts) {
      days.add(_dayKey(ts));
      if (ts > newestServerTs) newestServerTs = ts;
    }
  }
  if (!days.size) return 0;
  // Lens-04 audit #66: anchor "today" to the LATER of the client clock and the
  // newest SERVER-observed run already in `items` — a client clock running
  // behind the server (common under VM clock drift) would otherwise fail to
  // credit a run that has already genuinely happened today server-side,
  // silently breaking a real streak. A client clock running AHEAD of the
  // server isn't correctable this way (there's no server "now" in this
  // payload to anchor to instead — this is the honest best-effort version).
  const now = Math.max(Date.now(), newestServerTs);
  let anchor = now;
  if (!days.has(_dayKey(now))) {
    const yesterday = now - _ONE_DAY_MS;
    if (!days.has(_dayKey(yesterday))) return 0; // more than a day's gap — quietly reset
    anchor = yesterday;
  }
  let count = 0;
  let cursor = anchor;
  while (days.has(_dayKey(cursor))) {
    count += 1;
    cursor -= _ONE_DAY_MS;
  }
  return count;
}

function _renderStreak(host, days) {
  if (!host) return;
  // A 1-day "streak" doesn't read as a streak yet — stay quiet until there's
  // genuinely something to be warm about.
  if (!(days >= 2)) { host.innerHTML = ''; return; }
  host.innerHTML = `
    <div style="font-size:11px;opacity:0.65;margin:0 2px 8px;line-height:1.4;">
      Working for you ${days} days running
    </div>`;
}

async function _loadStreak() {
  const host = _streakHost();
  if (!host) return;
  let data;
  try {
    data = await _fetchJSON(`${ACTIVITY_API}/runs`);
  } catch {
    host.innerHTML = ''; // supplementary line — hide on any read failure
    return;
  }
  if (!data || data.engine_available === false || data.gated === true) { host.innerHTML = ''; return; }
  const items = (Array.isArray(data.items) ? data.items : []).filter((it) => it && typeof it === 'object');
  _renderStreak(host, _computeStreakDays(items));
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
      Your momentum shows up here once your first applications go out.
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
    scoreboard += `${sep}<span title="The job board that's working best for you so far." style="opacity:0.85;">best source: ${esc(String(best.source))}</span>`;
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
  // Milestone celebration (daily-ritual §4B, item #1): reuses the SAME funnel
  // data just rendered above — no second data path.
  _checkSubmitMilestone(data.summary);
}

// ── Milestone celebrations ────────────────────────────────────────────────────
//
// A ONE-TIME, tasteful nudge when a round-number "applications sent" threshold
// is crossed, sourced from the funnel data _loadMomentum already fetches
// (`summary.total_submitted`, cumulative) — no second data path. Reuses the
// exact toast mechanism the outcome-loop's own celebratory notifications
// surface through here (`_toast`, backed by ui.js `showToast`, the same
// function `_toastNew` calls for an arriving engine notification) rather than
// a bespoke banner/confetti widget — reduce-motion-safe by construction (plain
// text, no animation). Deduped in localStorage (`MILESTONES_SEEN_KEY`, mirrors
// the `applicant_vault_*` key-naming convention) so a threshold is announced
// exactly once, ever.
//
// "First interview" is deliberately NOT re-celebrated here: the engine's own
// `notify_positive_outcome()` already fires a celebratory in-app notification
// on every interview invite (deduped per outcome event via `dedup_key`), and
// Portal already folds informational notifications into a toast the moment
// they arrive (`_toastNew`, wired into `_loadNotifs`) — adding a second,
// Portal-local "first interview" trigger on top of that would be exactly the
// second celebration mechanism this feature is not supposed to build.

const SUBMIT_MILESTONES = [10, 25, 50, 100];

function _milestonesSeen() {
  try {
    const raw = window.localStorage.getItem(MILESTONES_SEEN_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch { return new Set(); }
}

function _markMilestonesSeen(ids) {
  try {
    const seen = _milestonesSeen();
    ids.forEach((id) => seen.add(id));
    window.localStorage.setItem(MILESTONES_SEEN_KEY, JSON.stringify(Array.from(seen)));
  } catch { /* no-op */ }
}

function _checkSubmitMilestone(summary) {
  const n = Number(summary && summary.total_submitted);
  if (!Number.isFinite(n) || n <= 0) return;
  const reached = SUBMIT_MILESTONES.filter((t) => n >= t);
  if (!reached.length) return;
  const seen = _milestonesSeen();
  const unseen = reached.filter((t) => !seen.has(`submitted_${t}`));
  // Mark every threshold at/below the current count as seen — a big jump
  // between visits (a batch of submissions) celebrates only the highest
  // newly-crossed one below, and never re-fires the smaller ones later.
  _markMilestonesSeen(reached.map((t) => `submitted_${t}`));
  if (!unseen.length) return;
  const top = unseen[unseen.length - 1];
  _toast(`🎉 ${top} applications sent — nice momentum.`);
}

// ── Empty / offline states ────────────────────────────────────────────────────

function _renderOffline(body) {
  body.innerHTML = `
    <div style="padding:28px 18px;text-align:center;opacity:0.75;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;margin-bottom:10px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
      <div style="font-size:14px;margin-bottom:6px;">I can't check in right now</div>
      <div style="font-size:12px;max-width:420px;margin:0 auto;">
        I've lost my connection. I'll keep trying — anything that needs you will
        appear here as soon as I'm back.
      </div>
    </div>`;
}

// A GATED response (the engine is UP, but automated work is blocked until setup
// is finished) is NOT offline. Show the engine's own plain-language setup message
// so the owner knows what to finish, instead of the misleading "not connected".
function _renderGated(body, data) {
  const msg = (data && data.message)
    || 'Finish setup — connect a model and fill in your profile — and I can start working for you.';
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
  // D4: reuse the EXACT trust statement (`trustLine`) from the OOBE welcome
  // step (B1). Demo-tone pass: this used to render a disclaimer-style list of
  // negative "never" statements — replaced with the same ONE positive
  // control line the wizard shows, so the empty state reads as reassurance,
  // not a wall of "nots".
  const line = trustLine || (typeof window !== 'undefined' && window.applicantTrustLine) || '';
  if (!line) return '';
  return `
    <div style="max-width:380px;margin:14px auto 0;text-align:left;border-top:1px solid var(--border);padding-top:12px;">
      <div style="font-size:11px;opacity:0.75;line-height:1.5;">${esc(line)}</div>
    </div>`;
}

// ── Honest health panel banner (P1-3, issue #655) ────────────────────────────
//
// Reads the SAME owner-gated proxy Settings -> System's full panel reads
// (applicantHealth.js's shared API constant) and renders a compact banner —
// or nothing — into its own always-present host, independent of the pending
// list (mirrors _loadMomentum/_loadStreak/_loadAgentPulse: a slow/offline
// health read never blocks or delays the queue the user opened Portal for).

function _healthHost() { return _modalEl && _modalEl.querySelector('#applicant-portal-health'); }

async function _loadHealth() {
  const host = _healthHost();
  if (!host) return;
  try {
    await renderApplicantPortalHealthBanner(host);
  } catch {
    host.innerHTML = ''; // best-effort supplementary strip — never break Portal over this
  }
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
  // Honest fallback: only claim active searching when the gate is genuinely open.
  // (This line normally shows only in the gate-open empty state, but guard it too
  // so the words can never contradict the real gate.)
  if (_gateClosed()) return 'Waiting on a few setup essentials before I can start.';
  return 'Searching and preparing applications for you';
}

// Updates the pulse line in place (no full re-render) so a slower snapshot fetch
// never flashes/reflows the empty state that already painted with the fallback
// line. A no-op when the empty state (or the modal) isn't currently showing.
function _renderPulseLine() {
  const el = _modalEl && _modalEl.querySelector('#applicant-portal-pulse-text');
  if (el) el.textContent = _agentPulseLine();
}

// ── "Today at a glance" ──────────────────────────────────────────────────────
//
// A compact one-line summary of TODAY specifically (not the whole "while you
// were away" recap window), reusing the EXACT `_agentPulse` data
// `_agentPulseLine` already reads (the engine's `now`/`next` snapshot) — no
// new data path. Renders in its own always-visible slot (whether the pending
// queue is empty or full), independent of the empty-state proof-of-life line.

function _todayHost() { return _modalEl && _modalEl.querySelector('#applicant-portal-today'); }

function _todayGlanceLine() {
  const now = _agentPulse && _agentPulse.now;
  const next = _agentPulse && _agentPulse.next;
  const parts = [];
  const applied = (now && Number.isInteger(now.applied_today)) ? now.applied_today : null;
  const budget = (now && Number.isInteger(now.daily_budget)) ? now.daily_budget : null;
  if (applied != null && budget != null && budget > 0) {
    parts.push(`${applied} of ${budget} application${budget === 1 ? '' : 's'} started`);
  } else if (applied != null) {
    parts.push(`${applied} application${applied === 1 ? '' : 's'} started today`);
  }
  const pending = (next && Number.isInteger(next.pending_actions)) ? next.pending_actions : null;
  if (pending != null && pending > 0) {
    parts.push(`${pending} need${pending === 1 ? 's' : ''} you`);
  }
  return parts.length ? `Today: ${parts.join(' · ')}` : '';
}

function _renderTodayGlance() {
  const host = _todayHost();
  if (!host) return;
  const line = _todayGlanceLine();
  if (!line) { host.innerHTML = ''; return; }
  host.innerHTML = `<div style="font-size:11px;opacity:0.65;margin:0 2px 8px;line-height:1.4;">${esc(line)}</div>`;
}

async function _loadAgentPulse() {
  try {
    const data = await _fetchJSON(`${ACTIVITY_API}/snapshot`);
    _agentPulse = (data && data.engine_available !== false && data.has_activity !== false) ? data : null;
  } catch {
    _agentPulse = null; // supplementary line — hide behind the static fallback on any read failure
  }
  _renderPulseLine();
  // Best-effort: a missing #applicant-portal-today host (an older cached DOM,
  // or a test harness that only fakes the pulse-text element) must never break
  // the pulse-line update above.
  try { _renderTodayGlance(); } catch { /* no-op */ }
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
          I'm working in the background — I'll bring anything that needs you
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

// Choose the honest "nothing waiting" state: the calm "I'm searching in the
// background" empty state ONLY when the apply-readiness gate is genuinely open;
// otherwise the truthful "your search isn't running yet" state. This is the
// product-honesty fix — the home base must never show a green "searching" signal
// while the engine's own gate says automated work is blocked.
function _renderVacant(body) {
  if (_gateClosed()) { _renderNotRunning(body); return; }
  _renderEmpty(body);
}

// The honest "not running yet" home state: the search is NOT happening because
// the apply-readiness gate is closed, and here is exactly what's still needed
// (the ONE server-truth `apply_missing`, the same list the wizard finish + chat
// report). Distinct neutral chrome (a paused clock, not the green success check)
// and a "Finish setup" CTA that reuses the same launcher the gated state uses.
function _renderNotRunning(body) {
  const missing = _applyMissing();
  const list = missing.length
    ? `<ul style="margin:10px 0 0;padding-left:18px;font-size:12px;line-height:1.6;color:color-mix(in srgb, var(--fg) 78%, transparent);">
         ${missing.map((m) => `<li>${esc(m)}</li>`).join('')}
       </ul>`
    : '';
  body.innerHTML = `
    <div style="padding:48px 24px 24px;text-align:center;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;margin-bottom:14px;"><circle cx="12" cy="12" r="10"/><polyline points="12 7 12 12 15 14"/></svg>
      <div style="max-width:400px;margin:0 auto;text-align:left;">
        <div style="font-size:14px;font-weight:600;color:var(--fg);margin-bottom:6px;">Your search isn't running yet</div>
        <div style="font-size:12px;line-height:1.5;color:color-mix(in srgb, var(--fg) 68%, transparent);">
          I'm not searching or sending anything yet — I can't start until a few
          essentials are in place. Finish these and I'll begin on my own.
        </div>
        ${list}
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-portal-notrunning-setup" style="margin-top:14px;">Finish setup</button>
      </div>
      ${_neverDoesHTML()}
    </div>`;
  const setupBtn = body.querySelector('#applicant-portal-notrunning-setup');
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

// ── Row rendering ──────────────────────────────────────────────────────────────

//: Plain-language channel names for the escalation-ladder line (#77) — never the
//: raw engine channel key.
const _LADDER_CHANNEL_LABEL = { discord: 'Discord', email: 'email', ntfy: 'push', in_app: 'in-app' };

// Notification escalation-ladder state (dark-engine audit #77): every tick
// advances a hold→email cadence (Discord held briefly for a quick web approval,
// then email after a timeout, both further held during quiet hours) but none of
// that was ever visible — a reminder just silently landed later with no
// explanation. Returns a short, honest caption for the item's card, or '' when
// the engine has no ladder info for it (most kinds notify once, immediately,
// with nothing to hold) or nothing is currently pending.
function _ladderLine(item) {
  const ladder = item.notification_ladder;
  if (!ladder || !ladder.held || !ladder.next_channel) return '';
  const chLabel = _LADDER_CHANNEL_LABEL[ladder.next_channel] || ladder.next_channel;
  if (ladder.quiet_hours_held) {
    return `Reminder held for quiet hours — will notify by ${chLabel} once it ends`;
  }
  if (ladder.next_due_at) {
    const when = new Date(ladder.next_due_at);
    if (!isNaN(when.getTime())) {
      const label = when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      return `Reminder held — escalates to ${chLabel} at ${label}`;
    }
  }
  return `Reminder held — will escalate to ${chLabel}`;
}

function _rowShell(item, inner) {
  const meta = _meta(item.kind);
  const title = item.title || meta.label;
  // Only show the generic per-kind label as a subtitle when the engine sent
  // its own distinct title — otherwise the same sentence would print twice
  // (the title already fell back to meta.label above).
  const subtitleLabel = title === meta.label ? '' : esc(meta.label);
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
  const ladderText = _ladderLine(item);
  const ladderLine = ladderText
    ? `<div style="opacity:0.55;font-size:10.5px;margin-top:2px;" title="The reminder ladder: a quick channel is held briefly for a web approval before escalating to the next one.">${esc(ladderText)}</div>`
    : '';
  return `
    <div class="admin-card og-card applicant-portal-row" data-action-id="${esc(item.id)}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;min-width:0;">
          <div style="font-weight:600;word-break:break-word;">${esc(title)}${_urgencyBadge(item)}</div>
          <div style="opacity:0.6;font-size:11px;margin-top:1px;">${subtitleLabel} ${_ageLabel(item)} ${where}</div>
          ${ladderLine}
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">${snoozeBtn}${doneBtn}</div>
      </div>
      <div class="applicant-portal-row-body" style="margin-top:8px;">${inner}</div>
    </div>`;
}

function _renderAnswer(item) {
  // Inline answer → resolve. Covers agent questions / confirms / soft errors.
  // For a deferred essay/screening question the pre-fill walk parked instead
  // of auto-answering (dark-engine audit item 21), also offer to have the
  // assistant draft one from the profile — still routed through the normal
  // document review before it's ever used — as an alternative to typing one
  // by hand below.
  const p = item.payload || {};
  const draftBtn = item.kind === 'agent_question' ? `
      <button type="button" class="cal-btn applicant-portal-generate-essay"
              data-action-id="${esc(item.id)}"
              data-campaign-id="${esc(item.campaign_id || '')}"
              data-application-id="${esc(_appId(item))}"
              data-question="${esc(p.question || '')}"
              data-selector="${esc(p.field_selector || '')}"
              data-url="${esc(p.url || '')}"
              title="Draft an answer from your profile — you still review it before it's used">Generate a draft</button>` : '';
  return `
    <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
      <textarea class="applicant-portal-answer" rows="2" placeholder="Type your answer…"
                style="flex:1;min-width:160px;resize:vertical;padding:7px 9px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:12px;"></textarea>
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-send-answer" data-action-id="${esc(item.id)}" data-application-id="${esc(_appId(item))}">Send</button>
      ${draftBtn}
    </div>`;
}

function _renderReview(item) {
  const hint = _meta(item.kind).hint || 'See exactly what I changed, side by side, before anything goes out.';
  const appId = esc(_appId(item));
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">${esc(hint)}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-review" data-app-id="${appId}">Review the document</button>
      <button type="button" class="cal-btn applicant-portal-fix-documents" data-app-id="${appId}"
              title="Check this application's documents and rebuild anything missing">Fix documents</button>
    </div>`;
}

function _renderMissing(item) {
  const p = item.payload || {};
  const name = p.attribute_name || p.name || '';
  const cid = item.campaign_id || '';
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">
      Give me this one detail and I’ll pick the application up where it left off.
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <input type="text" class="applicant-portal-missing-name" value="${esc(name)}" placeholder="What’s missing (e.g. desired salary)"
             style="flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;" />
      <input type="text" class="applicant-portal-missing-value" placeholder="Your answer"
             style="flex:2;min-width:140px;padding:6px 8px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-size:12px;" />
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-save-missing"
              data-action-id="${esc(item.id)}" data-campaign-id="${esc(cid)}" data-application-id="${esc(_appId(item))}">Save &amp; continue</button>
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
                data-app-id="${esc(appId)}" data-session-url="${esc(url)}">Watch live</button>`;
  } else {
    action = `<div style="font-size:12px;opacity:0.7;">When the live view is ready, the link will appear here.</div>`;
  }
  return handoff + action;
}

// Dark-engine audit #55: the engine scores every matched role (a 0-100
// viability score + a plain-language "why this role" rationale) but that only
// ever rendered inside the digest itself (Email tab). Each digest-approval row
// here already IS one specific scored posting (`payload.posting_id` /
// `payload.score` — see `DigestService.deliver`/`PendingActionsService.
// digest_approval`), so this card can show that same score right away instead
// of forcing a deep-link to "see why". The plain-language rationale text
// itself isn't stored on the pending action (only the numeric score is), so
// it is fetched lazily by `_wireDigestWhy` below, reusing the EXACT SAME
// `digestModule.fetchDigest` read (and its `why_suggested` field) the digest
// panel and the Portal's own "Today's roles" embed already use — never a
// second scoring/formatting implementation.
function _digestScoreLine(item) {
  const score = item && item.payload && item.payload.score;
  if (score == null || score === '') return '';
  return `<div style="font-size:12px;margin-bottom:4px;">`
    + `<span class="memory-count" title="How well this role fits what you told the assistant" `
    + `style="font-size:10.5px;font-weight:600;opacity:0.85;">${esc(String(score))}% match</span></div>`;
}

function _renderDigest(item) {
  const postingId = item && item.payload && item.payload.posting_id;
  const scoreLine = _digestScoreLine(item);
  // Populated asynchronously by `_wireDigestWhy` once the matching digest row
  // loads; left empty (not a "Loading…" placeholder) so a stale/expired
  // posting id just renders no line at all instead of a permanent spinner.
  const whyLine = postingId
    ? `<div class="applicant-portal-digest-why" data-digest-why="${esc(String(item.id))}" `
      + `data-digest-posting="${esc(String(postingId))}" data-digest-campaign="${esc(String(item.campaign_id || ''))}" `
      + `style="font-size:11px;opacity:0.72;margin-bottom:6px;display:-webkit-box;-webkit-box-orient:vertical;`
      + `-webkit-line-clamp:2;line-clamp:2;overflow:hidden;"></div>`
    : '';
  return `
    <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">Review the matched role and approve or skip it.</div>
    ${scoreLine}
    ${whyLine}
    <button type="button" class="cal-btn cal-btn-primary applicant-portal-digest">Review today's roles</button>`;
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
    ? 'The last attempt timed out. Tap ‘Try Google again’ and approve the prompt on your phone within 60 seconds.'
    : (meta.hint || 'Tap ‘Continue Google sign-in’, then approve the prompt on your phone within 60 seconds.');
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
              title="Open the live view and click submit yourself">I'll submit it myself</button>
      <button type="button" class="cal-btn cal-btn-primary applicant-portal-final-authorize"
              data-app-id="${esc(appId)}" data-action-id="${esc(item.id)}" data-label="${esc(label)}"
              title="I'll click the final submit for you — just this once, only after you confirm">Let me submit it</button>
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
//
// Lens-10 audit #41: `digest` used to collapse onto the same "Update" label
// and styling as generic `info` rows, so the one kind with a natural
// affordance (today's roles are waiting, in the same digest embed below) was
// indistinguishable from a routine update. Give it its own plain-language tag.
const _NOTIF_KIND_LABEL = {
  error: 'Heads up',
  digest: 'Daily digest',
  info: 'Update',
};

function _renderNotifRow(n) {
  // The digest kind also gets its own accent (distinct from the plain border
  // generic updates use) so the distinction reads at a glance, not just in text.
  const accent = n.kind === 'error'
    ? 'var(--color-danger,#e06c6c)'
    : (n.kind === 'digest' ? 'var(--color-accent,#00aaff)' : 'var(--border)');
  const tag = _NOTIF_KIND_LABEL[n.kind] || 'Update';
  const age = _notifAgeText(n);
  const ageSuffix = age ? ` <span style="opacity:0.7;">· ${esc(age)}</span>` : '';
  const body = (n.body && n.body !== n.title) ? `<div style="opacity:0.7;font-size:11px;margin-top:2px;word-break:break-word;">${esc(n.body)}</div>` : '';
  return `
    <div class="admin-card og-card applicant-portal-notif" data-notif-id="${esc(n.id)}" style="border-left:2px solid ${accent};">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;">
        <div style="font-size:13px;min-width:0;">
          <div style="font-weight:600;word-break:break-word;">${esc(n.title || tag)}</div>
          <div style="opacity:0.55;font-size:11px;margin-top:1px;">${esc(tag)}${ageSuffix}</div>
          ${body}
        </div>
        <button type="button" class="cal-btn applicant-portal-dismiss" data-notif-id="${esc(n.id)}" title="Dismiss this notification" style="flex-shrink:0;">Dismiss</button>
      </div>
    </div>`;
}

function _infoNotifs() {
  return (_notifs || []).filter(_isInformational);
}

// ── In-flight input preservation across a re-render (lens-04 #49) ──────────
//
// `_renderList` fully rebuilds the pending-list DOM from `_items` on every
// call — the first paint, the notifications fold-in a moment later, "Deliver
// now", any resolve/snooze/bulk-approve, and the manual refresh button all
// re-render it. Anything the user was mid-typing into an open row (an agent-
// question answer, a missing-detail name/value pair) lived only in that
// now-discarded DOM and silently vanished from under them. Capture what's
// actually been typed before the rebuild and splice it back into the
// freshly-rendered rows afterward, keyed by the same `data-action-id` a row
// already carries elsewhere (`_removeRow`).
function _captureDraftInputs(body) {
  const drafts = {};
  if (!body || !body.querySelectorAll) return drafts;
  Array.from(body.querySelectorAll('.applicant-portal-row')).forEach((row) => {
    const id = row.getAttribute && row.getAttribute('data-action-id');
    if (!id) return;
    const q = (sel) => (row.querySelector ? row.querySelector(sel) : null);
    const answer = q('.applicant-portal-answer');
    const missingName = q('.applicant-portal-missing-name');
    const missingValue = q('.applicant-portal-missing-value');
    const entry = {};
    if (answer && answer.value) entry.answer = answer.value;
    if (missingName && missingName.value) entry.missingName = missingName.value;
    if (missingValue && missingValue.value) entry.missingValue = missingValue.value;
    if (Object.keys(entry).length) drafts[id] = entry;
  });
  return drafts;
}

function _restoreDraftInputs(body, drafts) {
  if (!body || !drafts || !body.querySelectorAll) return;
  const rows = Array.from(body.querySelectorAll('.applicant-portal-row'));
  Object.keys(drafts).forEach((id) => {
    const row = rows.find((r) => r.getAttribute && r.getAttribute('data-action-id') === id);
    if (!row) return; // the row is gone (resolved/snoozed/expired) — nothing to restore it into
    const d = drafts[id];
    const q = (sel) => (row.querySelector ? row.querySelector(sel) : null);
    const answer = q('.applicant-portal-answer');
    if (answer && d.answer != null) answer.value = d.answer;
    const missingName = q('.applicant-portal-missing-name');
    if (missingName && d.missingName != null) missingName.value = d.missingName;
    const missingValue = q('.applicant-portal-missing-value');
    if (missingValue && d.missingValue != null) missingValue.value = d.missingValue;
  });
}

function _renderList(body) {
  const drafts = _captureDraftInputs(body);
  const infos = _infoNotifs();
  if (!_items.length && !infos.length) { _renderVacant(body); return; }
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
         <span style="font-size:11px;opacity:0.7;">Waiting on you: ${_items.length}</span>
         ${bulkBtn ? `<span style="margin-left:auto;">${bulkBtn}</span>` : ''}
       </div>`
    : '';
  // "Deliver now" (lens-10 audit #46): the release control used to live only on
  // the Settings quiet-hours card, not here in the center it actually flushes —
  // a user who opens the Portal precisely because "it's quiet hours and I want
  // my stuff now" had no affordance. Lift-and-shift the same fetch/handler shape
  // as `applicantOnboarding.js`'s `ao-qh-deliver` button (same endpoint, same
  // save-then-status message pattern) into this header, shown whenever there is
  // anything in the center to look at. No engine field currently exposes a count
  // of what quiet hours is holding (`GET /api/notifications` and the quiet-hours
  // proxy both omit it), so this ships as a button alone rather than guessing at
  // a "N held" figure.
  const deliverBtn = `<button type="button" class="cal-btn applicant-portal-deliver-now" id="applicant-portal-deliver-now" title="Send anything quiet hours is currently holding back, right now">Deliver now</button>`;
  const notifHdr = (infos.length || _items.length)
    ? `<div style="display:flex;align-items:center;gap:8px;margin:10px 2px 2px;">
         <span style="font-size:11px;opacity:0.7;">${infos.length ? 'Recent updates' : 'Notifications'}</span>
         <span id="applicant-portal-deliver-msg" style="font-size:11px;opacity:0.7;margin-left:auto;"></span>
         ${deliverBtn}
       </div>`
    : '';
  // #49: when there are pending actions above but no info notifications yet,
  // the header above ("Notifications") rendered with nothing under it and no
  // explanation — indistinguishable from a rendering bug. Name what's true
  // instead of leaving it blank.
  const notifEmpty = (!infos.length && _items.length)
    ? '<div class="applicant-portal-notif-empty" style="font-size:11px;opacity:0.55;padding:2px 2px 4px;">Nothing new to report — I’ll let you know here as soon as there’s an update.</div>'
    : '';
  body.innerHTML = `${actionHdr}${actionRows}${notifHdr}${notifRows}${notifEmpty}`;
  _restoreDraftInputs(body, drafts);
  _wireRows(body);
  _wireDigestWhy(body);
  _wireDeliverNow(body);
}

// Lift-and-shift of the Settings quiet-hours card's "Deliver now" handler
// (`applicantOnboarding.js` `ao-qh-deliver`, in its quiet-hours card) onto the
// SAME workspace proxy endpoint (`POST /api/applicant/portal/notifications/
// deliver-now`), so tapping this button in the Portal force-releases exactly
// what the Settings button would have. On success the notifications feed is
// reloaded and the list re-rendered so anything just released appears here
// immediately instead of waiting for the next poll.
function _wireDeliverNow(host) {
  const btn = host.querySelector('#applicant-portal-deliver-now');
  if (!btn) return;
  const msg = host.querySelector('#applicant-portal-deliver-msg');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    if (msg) { msg.textContent = 'Releasing…'; msg.className = ''; }
    try {
      const res = await _post(`${API}/notifications/deliver-now`, {});
      const n = (res && typeof res.count === 'number') ? res.count : 0;
      const text = n > 0
        ? `Released ${n} held notification${n === 1 ? '' : 's'}.`
        : 'Nothing was being held back by quiet hours.';
      _toast(text);
      if (msg) msg.textContent = '';
      await _loadNotifs();
      _setBadge(_items.length + _infoNotifs().length);
      _renderList(host);
    } catch (e) {
      _toast(errText(e) || 'Could not deliver those notifications');
      if (msg) msg.textContent = '';
      btn.disabled = false;
    }
  });
}

// ── Matched-role "why" (dark-engine audit #55) ──────────────────────────────
//
// One digest row's plain-language rationale, fetched lazily. Rows are grouped
// by campaign BEFORE fetching (below) so several matched-role cards open at
// once in the SAME render still cost one digest read per campaign, not one
// per row. Deliberately no cross-render cache: `_renderList` calls this fresh
// on every pending-list render (`_load`'s initial paint and its notifications
// fold-in), which already keeps this cheap without risking a stale/expired
// posting's rationale surviving past that render.
function _digestRowsForCampaign(campaignId) {
  if (!campaignId) return Promise.resolve([]);
  return digestModule.fetchDigest(campaignId)
    .then((data) => ((data && Array.isArray(data.rows)) ? data.rows : []))
    .catch(() => []);
}

// Fills in each rendered `[data-digest-why]` placeholder with the matching
// digest row's `why_suggested` text (the same field `buildDigestRow` in
// applicantDigest.js renders) once its campaign's digest loads. Best-effort:
// a posting that no longer appears in the digest (already acted on, expired,
// or the engine is unreachable) just leaves the line blank instead of erroring.
async function _wireDigestWhy(host) {
  const nodes = Array.from(host.querySelectorAll('[data-digest-why]'));
  if (!nodes.length) return;
  const byCampaign = new Map();
  nodes.forEach((el) => {
    const cid = el.getAttribute('data-digest-campaign') || '';
    if (!byCampaign.has(cid)) byCampaign.set(cid, []);
    byCampaign.get(cid).push(el);
  });
  await Promise.all(Array.from(byCampaign.entries()).map(async ([cid, els]) => {
    const rows = await _digestRowsForCampaign(cid);
    els.forEach((el) => {
      const pid = el.getAttribute('data-digest-posting') || '';
      const row = rows.find((r) => r && String(r.posting_id) === pid);
      const why = row && (row.why_suggested || row.reason);
      if (why) {
        el.textContent = String(why);
        el.title = 'Why the assistant suggested this';
      }
    });
  }));
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
  _toastAction('Your document review is in the Library', 'Open Library', () => {
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
  _toast('No live view is available yet');
}

// ── Wiring ──────────────────────────────────────────────────────────────────

function _removeRow(host, id) {
  const row = host.querySelector(`.applicant-portal-row[data-action-id="${CSS.escape(id)}"]`);
  if (row) row.remove();
  _items = _items.filter((it) => String(it.id) !== String(id));
  _setBadge(_items.length + _infoNotifs().length);
  _renderGreeting(_items.length);
  if (!host.querySelector('.applicant-portal-row') && !host.querySelector('.applicant-portal-notif')) {
    _renderVacant(host);
  }
}

// Lens-04 audit #50 (pairs with engine #27): the engine's resolve endpoint is
// idempotent-silent — it always reports success even for an action that's
// already resolved, gone, or mid-resolve elsewhere (a stale click after a
// bulk-approve/another tab/poll raced it away, or a genuine double-tap
// before the button's own disabled state lands) — there is nothing in that
// response to tell "really just resolved" apart from "resolving something
// that no longer needs it." Track what Portal itself already knows is no
// longer open (`_items`) plus a same-tab in-flight guard, and answer BOTH
// cases ourselves with a calm, explicit "already handled" state instead of
// quietly repeating the original success toast or bubbling a confusing
// network error for a click that had nothing left to do.
const _resolvingActionIds = new Set();

function _isActionOpen(id) {
  return _items.some((it) => String(it.id) === String(id));
}

async function _doResolve(id) {
  if (!_isActionOpen(id) || _resolvingActionIds.has(id)) {
    const err = new Error('This was already handled');
    err.alreadyHandled = true;
    throw err;
  }
  _resolvingActionIds.add(id);
  try {
    await _post(`${API}/actions/${encodeURIComponent(id)}/resolve`, {});
  } finally {
    _resolvingActionIds.delete(id);
  }
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
        if (e && e.alreadyHandled) {
          // Nothing left to do — the row (if it's even still here) just
          // needs to go, with an honest "already handled" instead of either
          // a silent no-op or the generic failure toast below.
          _removeRow(host, id);
          _toast('This was already handled');
          return;
        }
        btn.disabled = false;
        btn.textContent = orig;
        _toast(errText(e) || 'Could not update that');
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
        _toast('Snoozed — I’ll bring it back tomorrow morning.');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(errText(e) || 'Could not snooze that');
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
        _toast(errText(e) || 'Could not approve all of those');
      }
    });
  });

  // Answer → resolve.
  host.querySelectorAll('.applicant-portal-send-answer').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      const appId = btn.dataset.applicationId;
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
        // #78: the underlying application is still parked until the engine's next
        // resume sweep (up to ~5 minutes) — say honestly when that is instead of
        // implying it continues right away.
        _toast(`Sent${await _resumeCountdownSuffix(appId)}`);
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Send';
        _toast(errText(e) || 'Could not send that');
      }
    });
  });

  // Generate a draft answer for a deferred essay/screening question
  // (dark-engine audit item 21) instead of typing one by hand — the engine
  // generates + routes it through the normal document review, and clears the
  // originating question itself once the draft is created.
  host.querySelectorAll('.applicant-portal-generate-essay').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.actionId;
      const campaignId = btn.dataset.campaignId;
      const applicationId = btn.dataset.applicationId;
      if (!campaignId || !applicationId) {
        _toast('Missing campaign/application context for this question.');
        return;
      }
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Drafting…';
      try {
        await _post('/api/applicant/documents/deferred-essay', {
          campaign_id: campaignId,
          application_id: applicationId,
          question: btn.dataset.question || '',
          label: btn.dataset.question || '',
          selector: btn.dataset.selector || null,
          url: btn.dataset.url || null,
        });
        _removeRow(host, id);
        _toast('Draft generated — find it in Documents for review.');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(errText(e) || 'Could not generate a draft.');
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
          _toast(errText(e) || 'Could not update that');
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

  // Fix documents → run the engine's ensure-submittable auto-heal for this
  // application right from the blocked-material row (dark-engine audit item 2).
  // Leaves the row in place either way: success still needs the (now-clean)
  // Review click to actually approve anything; failure repeats what's missing.
  host.querySelectorAll('.applicant-portal-fix-documents').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const appId = btn.dataset.appId;
      if (!appId) { _toast('No application is linked to this item yet'); return; }
      btn.disabled = true;
      const orig = btn.textContent;
      btn.textContent = 'Checking…';
      try {
        await ensureSubmittable(appId);
        _toast('All documents are ready to submit');
      } catch (e) {
        const detail = e && e.body && e.body.detail;
        const msg = (typeof detail === 'string' && detail)
          || (e && e.message && e.message !== '[object Object]' && e.message)
          || 'Some documents still need your review before this can be submitted.';
        _toast(msg);
      }
      btn.disabled = false;
      btn.textContent = orig;
    });
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
        _toast(errText(e) || 'Could not continue the sign-in');
      }
    });
  });

  // Final submit (D2): submit-self opens the live session; authorize calls the
  // SAME engine endpoint the remote modal uses, behind an explicit confirm that
  // echoes the role/company + "materials approved ✓" (D5).
  host.querySelectorAll('.applicant-portal-final-self').forEach((btn) => {
    btn.addEventListener('click', () => {
      _openSession(btn.dataset.appId, '');
      _toast('Open the live view and click submit when you’re ready');
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
      catch { message = `Send ${label || 'this application'} now? You’ve approved everything in it. Once it’s submitted, I can’t take it back.`; }
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
        _toast('Done — I submitted it. It’s on its way.');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(errText(e) || 'Could not authorize the submission');
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
      const appId = btn.dataset.applicationId;
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
        // #78: if the application is still parked behind the resume backoff
        // (up to ~5 minutes) after this save, say honestly when the engine will
        // next check on it instead of implying it continues immediately.
        _toast(`Saved${await _resumeCountdownSuffix(appId)}`);
      } catch (e) {
        btn.disabled = false;
        btn.textContent = orig;
        _toast(errText(e) || 'Could not save that');
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
        _toast(errText(e) || 'Could not dismiss that');
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
    _renderVacant(host);
  }
}

// ── Count badge ────────────────────────────────────────────────────────────────

function _setBadge(n) {
  _lastBadgeCount = Math.max(0, Number(n) || 0);
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
    await _toastNew(_notifs);
  } catch {
    _notifs = [];
  }
  return _infoNotifs().length;
}

async function refreshBadge() {
  // Poll both feeds so new notifications toast and the badge reflects everything
  // waiting (open actions + undismissed informational notifications), even when
  // the modal is closed. Perf lens 03 item #5: this used to call the full
  // `/pending` aggregate (shaped rows + the onboarding-gap fan-out) just to read
  // an integer — call the lightweight `/pending/count` sibling instead and
  // reserve the full fetch for an actually-open Portal (`_load`).
  let pendingCount = 0;
  try {
    const data = await _fetchJSON(`${API}/pending/count`);
    // The engine explicitly reporting itself unreachable is a real state (the
    // modal's own offline copy covers it) — zero the badge for that.
    if (data && data.engine_available === false) { _setBadge(0); return; }
    pendingCount = (data && data.count) || 0;
  } catch {
    // Lens-10 audit #44: a transient fetch error (one dropped poll, not a
    // confirmed-offline engine) must not erase a real "N waiting" badge —
    // leave the last count actually painted in place instead of zeroing it.
    _setBadge(_lastBadgeCount);
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
      : "No new roles cleared the bar today. I'm still looking — I'll tell you the moment one does.";
    const searched = payload && payload.searched ? String(payload.searched) : '';
    if (searched && note.indexOf(searched) === -1) note += ` I looked at: ${searched}.`;
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
      dbody.innerHTML = `<div style="padding:6px 4px;font-size:12px;opacity:0.7;">Finish setup and I'll start lining up matched roles here.</div>`;
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
    // Capture the real apply-readiness gate so the home status is honest: only
    // claim "searching" when automated work is truly allowed (product-honesty).
    _gate = {
      automated_work_allowed:
        (data && typeof data.automated_work_allowed === 'boolean') ? data.automated_work_allowed : null,
      apply_ready: (data && typeof data.apply_ready === 'boolean') ? data.apply_ready : null,
      apply_missing: (data && Array.isArray(data.apply_missing)) ? data.apply_missing : [],
    };
    _lastPendingCount = _items.length;
    _renderGreeting(_items.length);
    _setBadge(_items.length + _infoNotifs().length);
    // Render the action rows the user opened Portal for RIGHT NOW — don't wait
    // on the notifications fetch first (audit item #17: first paint was
    // serialized behind it despite a comment claiming independence). Notifications
    // fold in asynchronously, the same fire-and-forget "render now, enrich later"
    // shape as _loadRecap/_loadAgentPulse below: _loadNotifs resolves, then we
    // re-render the list (now including any informational rows) and refresh the
    // badge to match.
    if (body) _renderList(body);
    _loadNotifs().then(() => {
      _setBadge(_items.length + _infoNotifs().length);
      if (body) _renderList(body);
    });
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

// `opts.skipHashUpdate` lets the one boot-time caller that auto-lands the
// user here on every page load (app.js, "post-login home base") leave
// location.hash untouched — every other caller (rail/sidebar launcher,
// the chat pending-actions link, the redline "Continue to submit" CTA, the
// hash router itself replaying a deep link) wants the URL to reflect that
// Portal is open.
export async function openApplicantPortal(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _setComposerDimmed(true);
  if (!(opts && opts.skipHashUpdate)) setHash('portal');
  // Keyboard a11y: trap focus, Escape to close, restore on close.
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  // Today's digest at the home base (C1) loads alongside the pending list; the
  // two are independent so a slow/offline digest never blocks the pending items.
  // The momentum strip (results funnel) and the supportive streak load
  // independently too; the recap is kicked off from within _load once the
  // fresh pending count is known.
  _loadDigest(true);
  _loadMomentum();
  _loadStreak();
  _loadHealth();
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
  _autoLandOnToday();
}

// Post-login HOME BASE: on a cold load, greet the user at Today (the Portal),
// not the bare chat shell they'd otherwise restore into. Guarded so it never
// fights a deliberate deep link and never races the onboarding wizard:
//   · a surface deep-link hash (#chat / #compare / #settings / …) owns the
//     screen — the hash router will open it, so we stand down;
//   · the onboarding wizard, when it shows, simply stacks ABOVE Today and
//     reveals it on dismiss (it also hands off to the Portal on completion),
//     so opening Today underneath is exactly the home base we want behind it.
// Fires once, after a short settle so the hash router + module wiring exist.
let _autoLandedOnToday = false;
const _LAND_SURFACES = ['chat', 'compare', 'debug', 'gallery', 'mind', 'results',
  'activity', 'portal', 'today', 'settings', 'tracker', 'memory', 'email',
  'calendar', 'library', 'archive'];
function _onboardingUp() {
  const o = document.getElementById('applicant-onboarding-overlay');
  return !!(o && o.offsetParent !== null && !o.classList.contains('hidden'));
}
function _landNow() {
  try {
    // A named surface deep-link means the user asked for something specific —
    // respect it and don't override with the home base.
    const hash = (window.location.hash || '').replace(/^#/, '').trim();
    if (_LAND_SURFACES.includes(hash)) return;
    // Only land on the BARE shell. If the user already opened a window in the
    // settle window (Settings, a chat, another surface) — or the Portal itself
    // is already up — don't pop Today on top of it.
    const otherOpen = [...document.querySelectorAll('.modal')].some((m) => {
      if (m.id === 'applicant-onboarding-overlay') return false;
      const s = getComputedStyle(m);
      return s.display !== 'none' && !m.classList.contains('hidden') && m.offsetParent !== null;
    });
    if (otherOpen) return;
    openApplicantPortal({ skipHashUpdate: true });
  } catch { /* best-effort landing — never block boot */ }
}
function _autoLandOnToday() {
  if (_autoLandedOnToday) return;
  _autoLandedOnToday = true;
  // The onboarding wizard mounts asynchronously (it probes engine status first),
  // so its timing races a fixed delay. Watch instead: never open Today WHILE the
  // wizard is up (a single Escape would then close both, dropping the user on the
  // bare chat), and land the moment it's absent — including RE-landing if the
  // wizard pops up late and then closes. _landNow() is idempotent (skips a deep
  // link or an already-open Portal), so re-calling it is safe.
  let sawOnboarding = false;
  let ticks = 0;
  const iv = setInterval(() => {
    ticks += 1;
    // While the wizard owns the screen, wait — never land underneath it.
    if (_onboardingUp()) { sawOnboarding = true; return; }
    // Land exactly ONCE, the first moment it's safe: either the wizard has been
    // seen and is now gone, or ~4s passed with no wizard (setup complete — its
    // async status probe resolves well inside that window, so we never land only
    // to have the wizard mount on top a beat later). _landNow() itself no-ops if
    // the user already opened a surface, so a single attempt is correct.
    if (sawOnboarding || ticks >= 16) {
      clearInterval(iv);
      _landNow();
    }
  }, 250);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#portal' deep-links straight into Portal — a
// refresh/shared-link/back-forward on that hash opens/closes it. Registered
// at module-eval time (runs as soon as app.js's dynamic import resolves,
// well before app.js calls hashRouter.initHashRouting()).
registerRoute('portal', { open: openApplicantPortal, close: _close });

const applicantPortalModule = { openApplicantPortal, closeApplicantPortal, refreshBadge };

// Expose for deep-links / other modules without import coupling.
try { window.applicantPortalModule = applicantPortalModule; } catch { /* no-op */ }

export default applicantPortalModule;
