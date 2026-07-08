// static/js/applicantRail.js
//
// P0-3 — the right-hand GADGET RAIL of the 3-pane shell (sidebar | chat |
// rail). This is the "at-a-glance state" pane: a stack of small gadgets that
// each surface ONE live signal about the owner's job search and expand to
// their full page in a single click. It is a NEW LENS over EXISTING data —
// it introduces NO new engine endpoints and duplicates NO engine logic. Every
// gadget reads the SAME owner-scoped front-door proxy the matching full-page
// module already reads, and every "open the full view" affordance calls the
// SAME exported launcher that module already exposes on `window`:
//
//   1. Waiting on you   → GET /api/applicant/portal/pending      (applicantPortal.js / applicantToday.js)
//   2. Pipeline         → GET /api/applicant/tracker             (applicantTracker.js)
//   3. Recent activity  → GET /api/applicant/activity/runs       (applicantActivity.js)
//   4. Cost & pace      → GET /api/applicant/campaigns/{id}/guardrails  (applicantToday.js P1-6)
//   5. Next interview   → GET /api/applicant/tracker             (interview bucket; applicantTracker.js)
//   6. Daily digest     → GET /api/applicant/email/digest/{id}  + deliverDigestNow (applicantReachability.js)
//   7. Your momentum    → GET /api/applicant/results             (applicantPortal.js momentum strip)
//   8. System health    → GET /api/applicant/health/capabilities (applicantHealth.js P1-3)
//
// The waiting-on-you gadget sits at the TOP as the rail's notification area:
// it auto-expands when action-required items arrive and shrinks when the queue
// is empty. That is one of the THREE notification surfaces P0-3 requires (the
// other two — the Portal's own toasts and the sidebar count badge — already
// exist and are reused, never rebuilt: this file pops a toast for a genuinely
// new waiting item through the SAME `ui.js` `showToast` seam via `_toast`).
//
// Rail chrome: the whole rail collapses to a slim badge strip (a pin/unpin per
// gadget reorders the stack), and both the collapsed state and the pin set
// persist in localStorage so the layout survives a reload. On small viewports
// the rail hides entirely (CSS) — the existing mobile bottom-sheet fallback
// stays the phone experience, exactly as the P0-3 DoR agreed.
//
// This module is ADDITIVE and self-contained: it owns only its mount
// (`#applicant-gadget-rail`) and reuses ONLY the shared kit (.admin-card /
// .cal-btn / .memory-* classes) plus applicantCore.js's fetch/toast helpers.
// It does NOT restructure the chat container, the Portal, or global nav.

import {
  esc, _toast, _fetchJSON,
} from './applicantCore.js';
import { deliverDigestNow } from './applicantReachability.js';

// ── Endpoints (all owner-scoped front-door proxies, same as the full pages) ──
const PORTAL_API = '/api/applicant/portal';
const TRACKER_API = '/api/applicant/tracker';
const ACTIVITY_API = '/api/applicant/activity';
const CAMPAIGNS_API = '/api/applicant/campaigns';
const RESULTS_API = '/api/applicant/results';
const HEALTH_API = '/api/applicant/health/capabilities';
const DIGEST_API = '/api/applicant/email/digest';

// ── localStorage keys (layout persistence) ──────────────────────────────────
const LS_COLLAPSED = 'applicant-rail-collapsed';
const LS_PINS = 'applicant-rail-pins';

const POLL_MS = 45000;
const RECENT_RUNS_CAP = 3;

let _mounted = false;
let _pollStop = null;
// The waiting-count last surfaced as a toast — a genuinely-new item toasts
// once; a steady or shrinking queue never re-toasts (mirrors the Portal badge
// contract: a transient blip must not spam the same signal). -1 = unseeded
// (nothing rendered yet): the boot render seeds silently, but a real 0 → N
// transition after "Nothing needs you right now." DOES toast.
let _lastWaitingToasted = -1;

// ── Pure helpers (unit-tested headlessly via the JS harness) ─────────────────

// Roll the tracker board's applications up into stage counts. The engine tags
// each application with a coarse `stage`/`status`/`bucket` — this reads
// whichever it finds, lower-cased, and never throws on a malformed row.
export function _pipelineCounts(applications) {
  const counts = { total: 0, interview: 0, submitted: 0, offer: 0, active: 0 };
  if (!Array.isArray(applications)) return counts;
  for (const app of applications) {
    if (!app || typeof app !== 'object') continue;
    counts.total += 1;
    const stage = String(app.stage || app.status || app.bucket || '').toLowerCase();
    if (stage.includes('interview')) counts.interview += 1;
    else if (stage.includes('offer')) counts.offer += 1;
    else if (stage.includes('submit') || stage.includes('applied')) counts.submitted += 1;
    else counts.active += 1;
  }
  return counts;
}

// The pinnable gadget ids, in their DEFAULT order. The waiting-on-you gadget
// is NOT here — it is the fixed notification area rendered above this list and
// is never pinnable/reorderable.
export const _PINNABLE_IDS = ['pipeline', 'activity', 'cost', 'interview', 'digest', 'momentum', 'health'];

// Resolve the rail's gadget order: pinned ids (in their default relative order)
// float to the top, the rest keep their default order below. Unknown ids in
// the persisted pin set are ignored so a stale key never injects a phantom
// gadget.
export function _railOrderIds(pins) {
  const pinned = new Set(Array.isArray(pins) ? pins.filter((id) => _PINNABLE_IDS.includes(id)) : []);
  const top = _PINNABLE_IDS.filter((id) => pinned.has(id));
  const rest = _PINNABLE_IDS.filter((id) => !pinned.has(id));
  return top.concat(rest);
}

// Cost & pace one-liner — lifted verbatim in shape from applicantToday.js's
// `_formatGuardrailsLine` so the rail and Today speak the same guardrails
// language ("target N/day (up to M, capped for safety)"), never the internal
// "hard cap" term.
export function _guardrailsLine(today) {
  if (!today || typeof today !== 'object') return '';
  const count = Number(today.applications_today) || 0;
  const target = Number(today.daily_target) || 0;
  const cap = Number(today.hard_cap) || 0;
  const costPart = today.usage_reported
    ? ` · ~$${(Number(today.cost_today_usd_estimate) || 0).toFixed(2)}`
    : '';
  const noun = count === 1 ? 'application' : 'applications';
  return `${count} ${noun}${costPart} · target ${target}/day (up to ${cap}, capped for safety)`;
}

// Health chip label + tone from the capabilities payload. Mirrors
// applicantHealth.js's own summary logic ("all real" vs "N of M degraded")
// rather than inventing a second verdict.
export function _healthChip(data) {
  if (!data || typeof data !== 'object') return null;
  if (data.engine_available === false) return { label: 'Offline', tone: 'warn' };
  if (data.gated === true) return { label: 'Setup needed', tone: 'muted' };
  const caps = Array.isArray(data.capabilities) ? data.capabilities : [];
  if (!caps.length) return { label: 'No report yet', tone: 'muted' };
  if (data.all_real === true) return { label: 'All systems real', tone: 'ok' };
  const degraded = Array.isArray(data.degraded) ? data.degraded.length : 0;
  return { label: `${degraded} of ${caps.length} degraded`, tone: 'warn' };
}

// Consecutive-day streak from the activity runs (compact mirror of
// applicantPortal.js's `_computeStreakDays`): count back from today over the
// set of local day-keys the runs land on, stopping at the first gap. Returns 0
// for an empty deck or a gap wider than one day.
export function _streakDays(items, nowMs) {
  const ONE_DAY = 86400000;
  const dayKey = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
  const runTs = (run) => {
    const raw = run && (run.finished_at || run.started_at || run.created_at || run.ts || run.time);
    const t = raw ? Date.parse(raw) : (typeof (run && run.timestamp) === 'number' ? run.timestamp : NaN);
    return Number.isFinite(t) ? t : 0;
  };
  const days = new Set();
  let newest = 0;
  for (const run of (Array.isArray(items) ? items : [])) {
    const ts = runTs(run);
    if (ts) { days.add(dayKey(ts)); if (ts > newest) newest = ts; }
  }
  if (!days.size) return 0;
  const now = Math.max(Number.isFinite(nowMs) ? nowMs : Date.now(), newest);
  let anchor = now;
  if (!days.has(dayKey(now))) {
    const yesterday = now - ONE_DAY;
    if (!days.has(dayKey(yesterday))) return 0;
    anchor = yesterday;
  }
  let count = 0;
  let cursor = anchor;
  while (days.has(dayKey(cursor))) { count += 1; cursor -= ONE_DAY; }
  return count;
}

// ── localStorage-backed layout state ────────────────────────────────────────

function _loadPins() {
  try {
    const raw = localStorage.getItem(LS_PINS);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((id) => _PINNABLE_IDS.includes(id)) : [];
  } catch { return []; }
}

function _savePins(pins) {
  try { localStorage.setItem(LS_PINS, JSON.stringify(pins)); } catch { /* private mode — layout just won't persist */ }
}

function _isCollapsed() {
  try { return localStorage.getItem(LS_COLLAPSED) === '1'; } catch { return false; }
}

function _saveCollapsed(collapsed) {
  try { localStorage.setItem(LS_COLLAPSED, collapsed ? '1' : '0'); } catch { /* no-op */ }
}

// ── Deep-links: one click opens the matching FULL PAGE (never a window) ───────
//
// Each gadget's "open" reuses the SAME launcher its full-page module already
// exports on `window` — the rail never invents a second path into a surface.

function _openTracker() { try { if (typeof window.openApplicantTracker === 'function') return window.openApplicantTracker(); } catch { /* fall through */ } _toast('Open the tracker to see your applications'); }
function _openActivity() { try { if (window.applicantActivityModule && window.applicantActivityModule.openApplicantActivity) return window.applicantActivityModule.openApplicantActivity(); } catch { /* fall through */ } _toast('Open Activity to see recent runs'); }
function _openToday() { try { if (typeof window.openApplicantToday === 'function') return window.openApplicantToday(); } catch { /* fall through */ } _toast('Open Today to review what needs you'); }
function _openResults() { try { if (typeof window.openApplicantResults === 'function') return window.openApplicantResults(); } catch { /* fall through */ } _toast('Open Results to see your momentum'); }
function _openDigest() { try { const railEmail = document.getElementById('rail-email'); if (railEmail) return railEmail.click(); } catch { /* fall through */ } _toast('Your matched roles are in the updates view'); }
function _openHealth() { try { const s = document.getElementById('user-bar-settings'); if (s) return s.click(); } catch { /* fall through */ } _toast('Open Settings → System to see engine health'); }

// Read the owner's first campaign id — MVP-1 runs a single active campaign, so
// this mirrors the same "first campaign" fallback applicantToday.js /
// applicantVault.js / applicantGallery.js already use rather than adding a
// second campaign picker into the rail.
async function _firstCampaignId() {
  try {
    const list = await _fetchJSON(CAMPAIGNS_API);
    const campaigns = (list && list.campaigns) || [];
    if (campaigns.length && campaigns[0] && campaigns[0].id) return String(campaigns[0].id);
  } catch { /* best-effort */ }
  return '';
}

// Per-refresh memos: pipeline+interview share ONE tracker read and cost+digest
// share ONE campaign-id read per refresh cycle (gadget loads run concurrently,
// so without these each poll would hit the same proxy twice). Reset by
// _renderGadgets at the top of every refresh; caching the PROMISE means
// concurrent gadgets await the same in-flight request.
let _trackerMemo = null;
let _campaignIdMemo = null;
function _trackerJSON() {
  if (!_trackerMemo) _trackerMemo = _fetchJSON(TRACKER_API);
  return _trackerMemo;
}
function _campaignIdOnce() {
  if (!_campaignIdMemo) _campaignIdMemo = _firstCampaignId();
  return _campaignIdMemo;
}

// ── Gadget definitions ───────────────────────────────────────────────────────
//
// Each gadget is { id, title, open, load(bodyEl) }. `load` fills the gadget's
// body with a compact live summary and hides the whole gadget (returns false)
// when its backing is offline/gated/empty, so the rail never shows dead UI —
// gadgets APPEAR as data exists, matching the "no padlocks, sections grow in"
// principle of the shell.

function _muted(text) { return `<div style="font-size:11.5px;opacity:0.6;line-height:1.45;">${esc(text)}</div>`; }

const _GADGETS = {
  pipeline: {
    id: 'pipeline', title: 'Pipeline', open: _openTracker,
    async load(body) {
      const data = await _trackerJSON();
      if (!data || data.engine_available === false || data.gated === true || data.has_data === false) return false;
      const c = _pipelineCounts(data.applications);
      if (!c.total) return false;
      const chip = (n, label) => `<span style="display:inline-flex;gap:4px;align-items:baseline;"><strong style="font-size:15px;">${n}</strong><span style="font-size:10.5px;opacity:0.6;">${esc(label)}</span></span>`;
      body.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:6px 14px;">${chip(c.total, 'in flight')}${c.interview ? chip(c.interview, 'interview') : ''}${c.offer ? chip(c.offer, 'offer') : ''}</div>`;
      return true;
    },
  },
  activity: {
    id: 'activity', title: 'Recently I…', open: _openActivity,
    async load(body) {
      const data = await _fetchJSON(`${ACTIVITY_API}/runs`);
      if (!data || data.engine_available === false || data.gated === true) return false;
      const items = (data.items || []).slice(-RECENT_RUNS_CAP).reverse();
      if (!items.length) return false;
      body.innerHTML = items.map((run) => {
        const intent = run.intent || run.summary || 'Worked on your job search';
        return `<div style="font-size:11.5px;line-height:1.4;padding:2px 0;opacity:0.85;">${esc(intent)}</div>`;
      }).join('');
      return true;
    },
  },
  cost: {
    id: 'cost', title: 'Cost & pace', open: _openToday,
    async load(body) {
      const cid = await _campaignIdOnce();
      if (!cid) return false;
      const data = await _fetchJSON(`${CAMPAIGNS_API}/${encodeURIComponent(cid)}/guardrails`);
      const today = data && data.today;
      if (!today) return false;
      const line = _guardrailsLine(today);
      if (!line) return false;
      body.innerHTML = _muted(line);
      return true;
    },
  },
  interview: {
    id: 'interview', title: 'Next interview', open: _openTracker,
    async load(body) {
      const data = await _trackerJSON();
      if (!data || data.engine_available === false || data.gated === true || data.has_data === false) return false;
      const c = _pipelineCounts(data.applications);
      if (!c.interview) return false;
      const noun = c.interview === 1 ? 'interview' : 'interviews';
      body.innerHTML = `<div style="font-size:12px;"><strong>${c.interview}</strong> ${esc(noun)} in your pipeline<div style="font-size:10.5px;opacity:0.6;margin-top:2px;">Open the tracker to prep.</div></div>`;
      return true;
    },
  },
  digest: {
    id: 'digest', title: 'Daily digest', open: _openDigest,
    async load(body) {
      const cid = await _campaignIdOnce();
      if (!cid) return false;
      let count = 0;
      try {
        const data = await _fetchJSON(`${DIGEST_API}/${encodeURIComponent(cid)}`);
        if (data && data.engine_available === false) return false;
        const roles = (data && (data.roles || data.items || data.applications)) || [];
        count = Array.isArray(roles) ? roles.length : 0;
      } catch { /* still render the send-now affordance */ }
      const line = count
        ? `<strong>${count}</strong> role${count === 1 ? '' : 's'} ready for your digest`
        : 'No new roles waiting for a digest right now.';
      body.innerHTML = `
        <div style="font-size:11.5px;opacity:0.85;line-height:1.4;margin-bottom:8px;">${line}</div>
        <button type="button" class="cal-btn" data-rail-digest-send style="font-size:11px;padding:4px 10px;">Send it now</button>`;
      const btn = body.querySelector('[data-rail-digest-send]');
      if (btn) {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          btn.disabled = true;
          const orig = btn.textContent;
          btn.textContent = 'Sending…';
          try {
            await deliverDigestNow(cid);
            _toast('Sent — your digest is on its way.');
          } catch {
            _toast('Could not send the digest just now.');
          } finally {
            btn.disabled = false;
            btn.textContent = orig;
          }
        });
      }
      return true;
    },
  },
  momentum: {
    id: 'momentum', title: 'Your momentum', open: _openResults,
    async load(body) {
      const data = await _fetchJSON(RESULTS_API);
      if (!data || data.engine_available === false || data.gated === true || data.has_data === false) return false;
      const s = (data.summary) || {};
      const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
      const chip = (v, label, tip) => `<span title="${esc(tip)}"><strong>${num(v)}</strong> ${esc(label)}</span>`;
      const sep = '<span style="opacity:0.35;">·</span>';
      body.innerHTML = `<div style="font-size:12px;display:flex;flex-wrap:wrap;gap:2px 8px;align-items:center;">${[
        chip(s.total_submitted, 'submitted', 'Applications submitted so far.'),
        chip(s.total_approved, 'approved', 'Roles you approved to move forward.'),
        chip(s.total_matched, 'found', 'Roles matched to your criteria.'),
      ].join(sep)}</div>`;
      return true;
    },
  },
  health: {
    id: 'health', title: 'System health', open: _openHealth,
    async load(body) {
      const data = await _fetchJSON(HEALTH_API);
      const chip = _healthChip(data);
      if (!chip) return false;
      const tones = { ok: 'var(--color-success,#4caf50)', warn: 'var(--color-warning,#e0a96c)', muted: 'var(--fg)' };
      const color = tones[chip.tone] || tones.muted;
      body.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px;font-size:12px;"><span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>${esc(chip.label)}</span>`;
      return true;
    },
  },
};

// ── DOM scaffold ─────────────────────────────────────────────────────────────

function _railEl() { return document.getElementById('applicant-gadget-rail'); }

function _pinIconSVG(filled) {
  return filled
    ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.4 5.4 5.9.5-4.5 3.9 1.4 5.8L12 20l-5.6 3.1 1.4-5.8L3.3 8.4l5.9-.5z"/></svg>'
    : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2l2.4 5.4 5.9.5-4.5 3.9 1.4 5.8L12 20l-5.6 3.1 1.4-5.8L3.3 8.4l5.9-.5z"/></svg>';
}

function _ensureScaffold() {
  const rail = _railEl();
  if (!rail || rail._applicantRailBuilt) return rail;
  rail._applicantRailBuilt = true;
  rail.setAttribute('role', 'complementary');
  rail.setAttribute('aria-label', 'At-a-glance job search');
  rail.classList.toggle('rail-collapsed', _isCollapsed());
  rail.innerHTML = `
    <div class="applicant-rail-head">
      <span class="applicant-rail-title">At a glance</span>
      <button type="button" class="applicant-rail-collapse memory-toolbar-btn" id="applicant-rail-collapse"
        aria-label="Collapse the rail" title="Collapse the rail" style="width:24px;height:24px;padding:0;flex-shrink:0;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg>
      </button>
    </div>
    <div class="applicant-rail-waiting" id="applicant-rail-waiting" aria-live="polite"></div>
    <div class="applicant-rail-gadgets" id="applicant-rail-gadgets"></div>
    <div class="applicant-rail-badges" id="applicant-rail-badges" aria-hidden="true"></div>`;
  const collapseBtn = rail.querySelector('#applicant-rail-collapse');
  if (collapseBtn) collapseBtn.addEventListener('click', () => _toggleCollapsed());
  return rail;
}

function _toggleCollapsed() {
  const rail = _railEl();
  if (!rail) return;
  const collapsed = !rail.classList.contains('rail-collapsed');
  rail.classList.toggle('rail-collapsed', collapsed);
  _saveCollapsed(collapsed);
  const btn = rail.querySelector('#applicant-rail-collapse');
  if (btn) {
    btn.setAttribute('aria-label', collapsed ? 'Expand the rail' : 'Collapse the rail');
    btn.setAttribute('title', collapsed ? 'Expand the rail' : 'Collapse the rail');
  }
}

// ── Rendering ────────────────────────────────────────────────────────────────

function _gadgetCard(gadget, pinned) {
  const card = document.createElement('div');
  card.className = 'admin-card applicant-rail-gadget';
  card.dataset.railGadget = gadget.id;
  card.style.cssText = 'padding:10px 12px;margin-bottom:8px;cursor:pointer;';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `${gadget.title} — open`);
  card.innerHTML = `
    <div class="applicant-rail-gadget-head" style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px;">
      <span style="font-size:10px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">${esc(gadget.title)}</span>
      <button type="button" class="applicant-rail-pin" data-rail-pin="${esc(gadget.id)}"
        aria-label="${pinned ? 'Unpin' : 'Pin'} ${esc(gadget.title)}" aria-pressed="${pinned ? 'true' : 'false'}"
        title="${pinned ? 'Unpin from the top' : 'Pin to the top'}"
        style="background:none;border:none;cursor:pointer;padding:2px;line-height:0;opacity:${pinned ? '0.9' : '0.4'};color:inherit;">${_pinIconSVG(pinned)}</button>
    </div>
    <div data-rail-body></div>`;
  // Whole-card click opens the full page; the pin button and any inner control
  // stop propagation so they don't also navigate.
  card.addEventListener('click', () => { try { gadget.open(); } catch { /* no-op */ } });
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); try { gadget.open(); } catch { /* no-op */ } }
  });
  const pinBtn = card.querySelector('[data-rail-pin]');
  if (pinBtn) {
    pinBtn.addEventListener('click', (e) => { e.stopPropagation(); _togglePin(gadget.id); });
  }
  return card;
}

function _togglePin(id) {
  if (!_PINNABLE_IDS.includes(id)) return;
  const pins = _loadPins();
  const idx = pins.indexOf(id);
  if (idx >= 0) pins.splice(idx, 1);
  else pins.push(id);
  _savePins(pins);
  _renderGadgets();
}

async function _renderGadgets() {
  const host = document.getElementById('applicant-rail-gadgets');
  const badges = document.getElementById('applicant-rail-badges');
  if (!host) return;
  const pins = _loadPins();
  const pinnedSet = new Set(pins);
  const order = _railOrderIds(pins);
  host.innerHTML = '';
  // Fresh per-refresh memos (see _trackerJSON/_campaignIdOnce): the concurrent
  // loads below share one tracker read and one campaign-id read per cycle.
  _trackerMemo = null;
  _campaignIdMemo = null;
  // Append every card first (keeps the default/pinned DOM order), then load
  // them CONCURRENTLY — one slow endpoint must not waterfall-stall the gadgets
  // below it on every poll.
  const cards = order
    .map((id) => ({ id, gadget: _GADGETS[id] }))
    .filter(({ gadget }) => gadget)
    .map(({ id, gadget }) => {
      const card = _gadgetCard(gadget, pinnedSet.has(id));
      host.appendChild(card);
      return { id, gadget, card };
    });
  const results = await Promise.all(cards.map(async ({ id, gadget, card }) => {
    try {
      const shown = await gadget.load(card.querySelector('[data-rail-body]'));
      return { id, gadget, card, shown };
    } catch { return { id, gadget, card, shown: false }; }
  }));
  const badgeParts = [];
  for (const { id, gadget, card, shown } of results) {
    if (shown === false) { card.remove(); continue; }
    badgeParts.push(`<button type="button" class="applicant-rail-badge" data-rail-badge="${esc(id)}" title="${esc(gadget.title)}" aria-label="${esc(gadget.title)}">${esc(gadget.title.charAt(0))}</button>`);
  }
  // Collapsed-rail badge strip: one initial per live gadget, click expands +
  // opens that gadget's page.
  if (badges) {
    badges.innerHTML = badgeParts.join('');
    badges.querySelectorAll('[data-rail-badge]').forEach((b) => {
      b.addEventListener('click', () => {
        const gid = b.getAttribute('data-rail-badge');
        const rail = _railEl();
        if (rail && rail.classList.contains('rail-collapsed')) _toggleCollapsed();
        const g = _GADGETS[gid];
        if (g) { try { g.open(); } catch { /* no-op */ } }
      });
    });
  }
}

// The rail's TOP notification area: the owner's waiting-on-you queue. It
// auto-expands (renders its rows) when action-required items arrive and
// collapses to a single "all clear" line when the queue is empty. Clicking it
// opens Today (the one-at-a-time run-through). A genuinely-new item also pops
// a toast through the SAME `ui.js` showToast seam — the third notification
// surface, reused not rebuilt.
async function _renderWaiting() {
  const host = document.getElementById('applicant-rail-waiting');
  if (!host) return;
  let data;
  try { data = await _fetchJSON(`${PORTAL_API}/pending`); }
  catch { host.classList.remove('has-items'); host.innerHTML = ''; return; }
  if (!data || data.engine_available === false || data.gated === true) {
    host.classList.remove('has-items');
    host.innerHTML = '';
    return;
  }
  const items = Array.isArray(data.items) ? data.items : [];
  const count = Number(data.count) || items.length;
  if (!count) {
    host.classList.remove('has-items');
    host.innerHTML = `<div class="applicant-rail-allclear" style="font-size:11.5px;opacity:0.6;padding:4px 2px;">Nothing needs you right now.</div>`;
    _lastWaitingToasted = 0;
    return;
  }
  host.classList.add('has-items');
  const rows = items.slice(0, 4).map((it) => {
    const title = esc(it.title || 'Needs your attention');
    return `<div class="applicant-rail-waiting-row" style="font-size:11.5px;line-height:1.4;padding:3px 0;border-top:1px solid var(--border);">${title}</div>`;
  }).join('');
  host.innerHTML = `
    <button type="button" class="applicant-rail-waiting-head" id="applicant-rail-waiting-open"
      style="width:100%;text-align:left;background:none;border:none;cursor:pointer;color:inherit;padding:0 0 4px;display:flex;align-items:center;gap:6px;">
      <span class="applicant-rail-waiting-badge">${count > 99 ? '99+' : count}</span>
      <span style="font-size:12px;font-weight:600;">Waiting on you</span>
    </button>
    ${rows}`;
  const openBtn = host.querySelector('#applicant-rail-waiting-open');
  if (openBtn) openBtn.addEventListener('click', _openToday);
  // Toast a genuinely-new waiting item (count grew) exactly once. The boot
  // render (_lastWaitingToasted === -1) seeds without toasting; after that any
  // growth — including 0 → N after the queue cleared — notifies.
  if (_lastWaitingToasted >= 0 && count > _lastWaitingToasted) {
    _toast(`${count} item${count === 1 ? '' : 's'} waiting on you`);
  }
  _lastWaitingToasted = count;
}

async function _refresh() {
  _ensureScaffold();
  await Promise.all([_renderWaiting(), _renderGadgets()]);
}

// ── Boot ─────────────────────────────────────────────────────────────────────

export function mountApplicantRail() {
  if (_mounted) return;
  const rail = _railEl();
  if (!rail) return;
  _mounted = true;
  _ensureScaffold();
  // Slow, visibility-aware poll so a backgrounded tab doesn't hammer the proxy.
  // pollVisible fires once immediately, seeding the first paint.
  if (_pollStop) _pollStop();
  let timer = null;
  const tick = () => { _refresh(); };
  const start = () => { if (timer == null) timer = setInterval(tick, POLL_MS); };
  const stop = () => { if (timer != null) { clearInterval(timer); timer = null; } };
  const onVis = () => { if (document.visibilityState === 'visible') { tick(); start(); } else stop(); };
  document.addEventListener('visibilitychange', onVis);
  // Shared cross-surface signal (P0-3b): the Portal's _setBadge fires
  // `applicant:pending-changed` whenever the authoritative pending count moves
  // (a resolve/snooze in Today, or the top-bar bell). Re-read the ONE backing
  // feed immediately so the rail's waiting area clears in lockstep with the
  // bell + Portal instead of waiting out its own poll.
  document.addEventListener('applicant:pending-changed', tick);
  tick();
  if (document.visibilityState === 'visible') start();
  _pollStop = () => { stop(); document.removeEventListener('visibilitychange', onVis); document.removeEventListener('applicant:pending-changed', tick); };
}

function _boot() {
  // The mount lives in index.html; wire whenever it's present.
  if (_railEl()) { mountApplicantRail(); return; }
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    if (_railEl()) { mountApplicantRail(); clearInterval(iv); }
    else if (tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantRailModule = { mountApplicantRail };
try { window.applicantRailModule = applicantRailModule; } catch { /* no-op */ }
try { window.mountApplicantRail = mountApplicantRail; } catch { /* no-op */ }

export default applicantRailModule;
