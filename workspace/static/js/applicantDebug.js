// static/js/applicantDebug.js
//
// Activity / Debug — the workspace observability + operations surface wired to
// the Applicant engine. ADDITIVE and self-contained: it opens its own modal,
// talks to the engine through the admin/ops workspace proxies
// (/api/applicant/admin/* and /api/applicant/ops/*), and never touches any
// native surface.
//
// What it shows (all plain-language, white-labeled, read-only unless noted):
//   • Activity   — per-application history for a campaign, with a drill-in to
//                  that application's screenshots, workflow state and outcomes,
//                  plus a one-click "I submitted this myself" (mark-submitted)
//                  so manual/hand-off applications still teach the system.
//   • Insights   — what the system has learned: overall conversion, each
//                  source's funnel ranked by conversion, the roles that convert,
//                  and the exploration budget (read-only).
//   • Logs       — recent redacted run logs.
//   • Variants   — the resume-variant library (lineage / score / approval).
//   • Run        — run mode + daily target controls, the latest plain-language
//                  "what the agent is doing right now" intent (or, per dark-
//                  engine audit #64, WHY nothing is happening — waiting on
//                  setup / paused — when a scheduled run skipped instead of
//                  working), a live-status chip that also surfaces THIS
//                  campaign's own recent tick failures/overlap-skips (dark-
//                  engine audit #73), and a "Recent runs" mini-table of the
//                  per-run stats the engine already persists every tick (dark-
//                  engine audit #75) (writes config).
//   • Config     — Sources (turn each job-discovery source on/off + see its
//                  yield), Detection events (dark-engine audit #26 — plain-
//                  language history of bot-checks/blocks a job site threw at
//                  the automated browser, read-only), Tools (enable/disable
//                  the engine's tools, engine-wide; writes), Stealth posture
//                  (dark-engine audit #27 — the live egress/connection posture
//                  + honest best-effort caveat, read-only), Diagnostics (dark-
//                  engine audit #34 — recent plain-language issues where
//                  pre-fill degraded gracefully instead of stopping, read-only),
//                  Background connection (dark-engine audit #71 — whether the
//                  engine's callback link to this workspace, used for calendar
//                  sync / deep research / shared memory, is configured and
//                  actually reachable right now, read-only) and Update (a
//                  one-click Update button with confirm + status) as
//                  sub-sections of one pane (item #86 — these were separate
//                  top-level tabs, pushing the tab strip past its ceiling;
//                  grouped so it stays within the 5-7 ceiling).
//
// Activation: the launcher (tool-debug-btn) is greyed + click-guarded by the
// feature-activation layer in app.js until the engine reports it's configured
// (the `debug` section). We still render a graceful offline state if opened while
// the engine is unreachable or the caller isn't an admin.

import uiModule from './ui.js';
import { esc, _toast, _fetchJSON, _post, _put, errText, loadingHTML, errorHTML, wireRetry } from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const ADMIN = '/api/applicant/admin';
const OPS = '/api/applicant/ops';

let _modalEl = null;
let _modalA11yCleanup = null;
let _activeTab = 'activity';
let _campaignId = null;
let _busySave = false; // re-entry guard for save-run-settings
let _busySubmit = false; // re-entry guard for mark-submitted






// ── Modal scaffold ──────────────────────────────────────────────────────────

// #86: collapsed from 8 tabs (Activity/Insights/Logs/Variants/Run/Sources/
// Tools/Update) to 6 — Sources/Tools/Update now render as sub-sections of one
// Config pane (see _renderConfig) instead of three separate top-level tabs.
const TABS = [
  ['activity', 'Activity'],
  ['insights', 'Insights'],
  ['logs', 'Logs'],
  ['variants', 'Variants'],
  ['run', 'Run controls'],
  ['config', 'Config'],
];

const CLOSE_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

// Keep the tab strip's `.active`/`aria-selected` and the shared tabpanel's
// `aria-labelledby` all pointing at the same current tab (a11y audit #29 —
// real `role="tab"`/`role="tabpanel"` semantics instead of plain buttons with
// no selected-state). Pure DOM sync, no render — callers that also need a
// fresh render call `_activateTab` instead (below) or `_renderTab()` directly.
function _syncTabActiveUI(tab) {
  if (!_modalEl) return;
  const body = _modalEl.querySelector('#applicant-debug-body');
  _modalEl.querySelectorAll('#applicant-debug-tabs .admin-tab').forEach((x) => {
    const active = x.dataset.tab === tab;
    x.classList.toggle('active', active);
    x.setAttribute('aria-selected', active ? 'true' : 'false');
    if (active && body) body.setAttribute('aria-labelledby', x.id);
  });
}

// Click/arrow-key entry point: sets the active tab, syncs its ARIA state, and
// renders it — the click handler and the tablist's arrow-key navigation both
// go through this one function so they can never drift out of sync.
function _activateTab(tab) {
  _activeTab = tab;
  _syncTabActiveUI(tab);
  _renderTab();
}

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-debug-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  // aria-labelledby (pointing at the actual visible title) instead of a
  // hardcoded aria-label string that can drift from the on-screen text —
  // a11y audit #9.
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:860px;display:flex;flex-direction:column;max-height:88vh;">
      <div class="modal-header">
        <h4 id="applicant-debug-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;" aria-hidden="true"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          Activity
        </h4>
        <button class="close-btn" id="applicant-debug-close" title="Close" aria-label="Close">${CLOSE_SVG}</button>
      </div>
      <div style="padding:8px 14px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <label class="admin-toggle-sub" style="margin:0;display:flex;gap:6px;align-items:center;">
          Job search
          <select id="applicant-debug-campaign" class="ow-select" style="min-width:180px;"></select>
        </label>
        <div class="applicant-debug-overflow-wrap" style="margin-left:auto;position:relative;">
          <button class="cal-btn" type="button" id="applicant-debug-overflow-btn" title="More actions" aria-label="More actions" aria-haspopup="true" aria-expanded="false">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-3px;" aria-hidden="true"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>
          </button>
          <div class="applicant-debug-overflow-menu hidden" id="applicant-debug-overflow-menu" role="menu">
            <button type="button" class="applicant-debug-overflow-item" id="applicant-debug-download-log" role="menuitem" title="Download a record of every action the engine took for this search, in order">Download activity log</button>
            <button type="button" class="applicant-debug-overflow-item" id="applicant-debug-chat" role="menuitem" title="Open the assistant beside this so you can ask about what the agent is doing">Ask the assistant</button>
          </div>
        </div>
      </div>
      <div id="applicant-debug-engine-banner" class="admin-toggle-sub" style="padding:0 14px;margin-top:4px;opacity:0.7;display:none;"></div>
      <div class="admin-tabs" id="applicant-debug-tabs" role="tablist" style="padding:8px 14px 0;">
        ${TABS.map(([k, label], i) => `<button class="admin-tab${i === 0 ? ' active' : ''}" role="tab" id="applicant-debug-tab-${k}" aria-selected="${i === 0 ? 'true' : 'false'}" aria-controls="applicant-debug-body" data-tab="${k}">${esc(label)}</button>`).join('')}
      </div>
      <div class="modal-body" id="applicant-debug-body" role="tabpanel" aria-labelledby="applicant-debug-tab-${TABS[0][0]}" style="flex:1;overflow-y:auto;padding:14px;">
        ${loadingHTML('Loading…')}
      </div>
      <div id="applicant-debug-live" aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;"></div>
    </div>`;
  document.body.appendChild(modal);
  const overflowBtn = modal.querySelector('#applicant-debug-overflow-btn');
  const overflowMenu = modal.querySelector('#applicant-debug-overflow-menu');
  const closeOverflow = () => {
    if (!overflowMenu) return;
    overflowMenu.classList.add('hidden');
    if (overflowBtn) overflowBtn.setAttribute('aria-expanded', 'false');
  };
  // Focus-trap/restore (uiModule.initModalA11y) is deliberately NOT wired here
  // — this function only runs once, on first creation, and re-gating the trap
  // behind that "created once" branch is exactly the six-modals bug design
  // audit #1 flags (Debug named explicitly): the cleanup that Escape/close
  // runs tears the trap down, and a modal only ever re-created here would
  // never get it back. `_wireA11y()` below is called fresh from every
  // openApplicantDebug()/openApplicantDebugDetail() instead, so every open —
  // not just the first — gets a working trap, Escape, and focus restore.
  modal.querySelector('#applicant-debug-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  modal.querySelectorAll('#applicant-debug-tabs .admin-tab').forEach((b) => {
    b.addEventListener('click', () => { _activateTab(b.dataset.tab); });
  });
  // Left/Right arrow-key accelerators on the tablist (design audit #29 — no
  // tab strip in the product has arrow-key nav). Additive: every tab button
  // keeps its normal tabindex, so plain Tab-key order through the strip is
  // unchanged; arrows are a layered-on shortcut, not a replacement.
  const tablist = modal.querySelector('#applicant-debug-tabs');
  if (tablist) {
    tablist.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const tabs = Array.from(tablist.querySelectorAll('.admin-tab'));
      const idx = tabs.indexOf(document.activeElement);
      if (idx === -1) return;
      e.preventDefault();
      const next = e.key === 'ArrowRight'
        ? tabs[(idx + 1) % tabs.length]
        : tabs[(idx - 1 + tabs.length) % tabs.length];
      next.focus();
      _activateTab(next.dataset.tab);
    });
  }
  modal.querySelector('#applicant-debug-campaign').addEventListener('change', (e) => {
    _campaignId = e.target.value || null;
    _renderTab();
  });

  // #87: the header used to pack picker + status text + two text buttons (4+
  // groups). Now: leading = the job-search picker, trailing = ONE overflow
  // control housing the two former actions; the engine-offline note moved to
  // its own banner in the body instead of a header-row badge.
  if (overflowBtn && overflowMenu) {
    overflowBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const willOpen = overflowMenu.classList.contains('hidden');
      if (willOpen) {
        // #101: gate "Ask the assistant" on the module actually being present
        // each time the menu opens, instead of always showing it and no-oping
        // to a toast on click.
        const chatItem = overflowMenu.querySelector('#applicant-debug-chat');
        if (chatItem) {
          const hasChat = !!(window.applicantChatModule && typeof window.applicantChatModule.openApplicantChat === 'function');
          chatItem.style.display = hasChat ? '' : 'none';
        }
      }
      overflowMenu.classList.toggle('hidden', !willOpen);
      overflowBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    });
    document.addEventListener('click', (e) => {
      if (!overflowMenu.classList.contains('hidden') && e.target !== overflowBtn && !overflowMenu.contains(e.target)) {
        closeOverflow();
      }
    });
  }
  // Download activity log (JSON) — one-click export of the full action trail.
  const downloadBtn = modal.querySelector('#applicant-debug-download-log');
  if (downloadBtn) downloadBtn.addEventListener('click', () => { closeOverflow(); _downloadAuditLog(); });

  // Dual view: open the Job Assistant beside this window (both are scrim-less,
  // draggable tool windows, so they sit side by side) — watch the agent on one
  // side, ask it questions on the other.
  const chatBtn = modal.querySelector('#applicant-debug-chat');
  if (chatBtn) chatBtn.addEventListener('click', () => {
    closeOverflow();
    try {
      if (window.applicantChatModule && window.applicantChatModule.openApplicantChat) {
        window.applicantChatModule.openApplicantChat();
      } else { _toast('The assistant is not available right now.'); }
    } catch { _toast('Could not open the assistant.'); }
  });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = 'none';
    const overflowMenu = _modalEl.querySelector('#applicant-debug-overflow-menu');
    if (overflowMenu) overflowMenu.classList.add('hidden');
  }
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('debug');
}

// Exported so other modules/tests can close Debug without reaching into its
// private state, mirroring openApplicantDebug's public export.
export function closeApplicantDebug() {
  _close();
}

function _body() { return _modalEl.querySelector('#applicant-debug-body'); }

// `host` defaults to the whole tab body; the Config pane's sub-sections pass
// their own sub-host so one section's offline/gated state doesn't blank out
// its siblings (#86).
function _renderOffline(msg, host) {
  (host || _body()).innerHTML = `<div class="admin-card" style="opacity:0.85;">${esc(msg || 'The Applicant engine is not reachable right now. This view will fill in once it is connected.')}</div>`;
}

// A GATED response (engine is UP, but setup is incomplete / a precondition isn't
// met) is NOT offline. Show the engine's own plain-language setup message so the
// owner knows what to finish, instead of the misleading "not reachable" copy.
function _renderGated(data, host) {
  const msg = (data && data.message)
    || 'Finish onboarding and configure your model and notification channels to enable automated work.';
  (host || _body()).innerHTML = `<div class="admin-card" style="opacity:0.9;">${esc(msg)}</div>`;
}

// True only for a genuine transport-offline soft-degrade (engine unreachable),
// NOT for a gated response (which keeps engine_available true).
function _isOffline(data) { return !!data && data.engine_available === false; }
function _isGated(data) { return !!data && data.gated === true; }

function _empty(msg) {
  return `<div class="admin-toggle-sub" style="opacity:0.6;padding:8px 0;">${esc(msg)}</div>`;
}

// Render the immutable submission snapshot (#372): the exact answers, document
// versions, posting, and timestamp recorded at the stop-boundary.
function _renderSnapshot(snap) {
  if (!snap || snap.has_snapshot === false || (!snap.timestamp && !snap.answers && !snap.material_versions)) {
    return _empty('No submission record yet — it is captured when an application is submitted.');
  }
  const when = snap.timestamp ? new Date(snap.timestamp).toLocaleString() : 'unknown time';
  const answers = snap.answers || {};
  const mats = snap.material_versions || {};
  const answerRows = Object.keys(answers).length
    ? Object.entries(answers).map(([k, v]) => `<div class="admin-toggle-sub" style="opacity:0.8;">${esc(k)}: ${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</div>`).join('')
    : _empty('No answers captured.');
  const matRows = Object.keys(mats).length
    ? Object.entries(mats).map(([k, v]) => `<span class="admin-toggle-sub" style="opacity:0.8;">${esc(k)}: ${esc(v)}</span>`).join(' · ')
    : '<span class="admin-toggle-sub" style="opacity:0.6;">none</span>';
  return `<div class="admin-card" style="margin-top:4px;background:var(--bg-subtle,#0001);">
    <div class="admin-toggle-sub" style="opacity:0.7;">Recorded ${esc(when)}</div>
    ${snap.posting_url ? `<div class="admin-toggle-sub" style="opacity:0.7;">Posting: ${esc(snap.posting_url)}</div>` : ''}
    <div class="admin-toggle-sub" style="margin-top:4px;"><strong>Documents</strong>: ${matRows}</div>
    <div class="admin-toggle-sub" style="margin-top:4px;"><strong>Answers</strong></div>
    ${answerRows}
  </div>`;
}

// ── Campaign picker ───────────────────────────────────────────────────────────

async function _loadCampaigns() {
  // Reuse the chat proxy's campaign list (already auth-protected, soft-degrading).
  let data;
  try {
    data = await _fetchJSON('/api/applicant/chat/campaigns');
  } catch {
    data = { engine_available: false, campaigns: [] };
  }
  const sel = _modalEl.querySelector('#applicant-debug-campaign');
  const campaigns = Array.isArray(data && data.campaigns) ? data.campaigns : [];
  sel.innerHTML = campaigns.length
    ? campaigns.map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.id)}</option>`).join('')
    : '<option value="">No job searches yet</option>';
  if (!_campaignId && campaigns.length) _campaignId = campaigns[0].id;
  if (_campaignId) sel.value = _campaignId;
  return data && data.engine_available !== false;
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

// Stale-response guard: each re-render bumps a token, so a slow tab/campaign
// fetch that resolves AFTER the user has switched tab or job-search is discarded
// instead of overwriting the now-current view with stale rows.
let _renderToken = 0;

function _renderIsStale(token) {
  return token !== _renderToken;
}

async function _renderTab() {
  const map = {
    activity: _renderActivity,
    insights: _renderInsights,
    logs: _renderLogs,
    variants: _renderVariants,
    run: _renderRun,
    config: _renderConfig,
  };
  const token = ++_renderToken;
  const tabLabel = (TABS.find(([k]) => k === _activeTab) || [])[1] || 'this view';
  const body = _body();
  // aria-busy + a short plain-language live-status line around the fetch/
  // render (design audit #11/#12) — the tabpanel's own content swap stays
  // silent (too verbose to read whole-hog on every switch); this narrates
  // just the loading/settled transition.
  if (body) body.setAttribute('aria-busy', 'true');
  body.innerHTML = loadingHTML('Loading…');
  _announce(`Loading ${tabLabel}…`);
  try {
    await (map[_activeTab] || _renderActivity)(token);
    if (_renderIsStale(token)) return;
    if (body) body.setAttribute('aria-busy', 'false');
    _announce(`${tabLabel} loaded.`);
  } catch (e) {
    if (_renderIsStale(token)) return;
    if (body) body.setAttribute('aria-busy', 'false');
    if (e && (e.status === 403 || e.kind === 'forbidden')) {
      // Admin gate: a Retry can't fix a permissions block, so show the message
      // without a retry affordance (keeps the gate honest).
      _renderOffline('This view is available to admins only.');
      _announce('This view is available to admins only.');
    } else {
      // Everything else dead-ended on error text before — give an inline Retry
      // so the user recovers without closing the surface.
      _body().innerHTML = errorHTML(_errLine(e));
      wireRetry(_body(), _renderTab);
      _announce(`Could not load ${tabLabel}.`);
    }
  }
}

// Map a kit error (with .kind) to a plain-language line for the retry card.
function _errLine(err) {
  if (err && (err.kind === 'offline' || err.kind === 'network')) {
    return 'The Applicant engine is not reachable right now. This view will fill in once it is connected.';
  }
  return errText(err);
}

function _needCampaign() {
  if (!_campaignId) {
    _body().innerHTML = _empty('Pick a job search above to see its activity.');
    return false;
  }
  return true;
}

// Host-scoped variant of _needCampaign — for the Config pane's Sources
// sub-section, which needs a campaign while its Tools/Update siblings don't, so
// a missing campaign can't blank out the whole pane.
function _needCampaignIn(host) {
  if (!_campaignId) {
    host.innerHTML = _empty('Pick a job search above to see its sources.');
    return false;
  }
  return true;
}

// ── Audit-log export ─────────────────────────────────────────────────────────

async function _downloadAuditLog() {
  if (!_campaignId) {
    _toast('Pick a job search above first.');
    return;
  }
  try {
    const resp = await fetch(`${ADMIN}/audit-log/${encodeURIComponent(_campaignId)}/export.json`, { credentials: 'same-origin' });
    if (!resp.ok) {
      if (resp.status === 403) { _toast('This is available to admins only.'); return; }
      const detail = await resp.text().catch(() => '');
      throw new Error(detail || `Unexpected response (${resp.status})`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-log-${_campaignId}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    _toast('Downloaded.');
  } catch (e) {
    _toast(e.message || 'Could not download the activity log right now.');
  }
}

// #93/#94/#100: was one bordered `.admin-card` tile per application (glass-on-
// glass stacking) with two equally-weighted buttons. Now one flat list with
// hairline row dividers; "Details" (navigation) is the primary action, "I
// submitted this" (an infrequent, secondary action) is demoted to a plain
// text-style affordance.
async function _renderActivity(token) {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${ADMIN}/history/${encodeURIComponent(_campaignId)}`);
  // Discard a late response whose tab/job-search is no longer the current one.
  if (token != null && _renderIsStale(token)) return;
  if (data.engine_available === false) { _renderOffline(); return; }
  const apps = data.applications || [];
  if (!apps.length) { _body().innerHTML = _empty('No applications recorded for this job search yet.'); return; }
  const rows = apps.map((a) => {
    const id = a.application_id || a.id || '';
    const title = a.role_name || a.job_title || id || 'Application';
    const shots = a.screenshot_count != null ? a.screenshot_count : (a.screenshots || []).length;
    return `<div class="applicant-debug-list-row">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(title)}</div>
        <div class="admin-toggle-sub" style="margin:2px 0 0;opacity:0.7;">
          ${esc(a.status || 'unknown')} · ${esc(a.work_mode || '—')} · ${esc(shots)} screenshots${(a.outcomes || []).length ? ` · ${esc((a.outcomes || []).map((o) => o.type).join(', '))}` : ''}
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;">
        <button type="button" class="applicant-debug-row-secondary applicant-debug-marksub" data-app="${esc(id)}" title="Record that you completed/submitted this yourself so it teaches the system">I submitted this</button>
        <button class="admin-btn-sm applicant-debug-detail" data-app="${esc(id)}">Details</button>
      </div>
    </div>`;
  }).join('');
  _body().innerHTML = `<div id="applicant-debug-detail-host"></div><div class="applicant-debug-list">${rows}</div>`;
  _body().querySelectorAll('.applicant-debug-detail').forEach((b) => {
    b.addEventListener('click', () => _showAppDetail(b.dataset.app, b));
  });
  _body().querySelectorAll('.applicant-debug-marksub').forEach((b) => {
    b.addEventListener('click', () => _markSubmitted(b.dataset.app, b));
  });
}

// `triggerBtn` (the row's "Details" button) is remembered so closing the
// drill-in can hand focus back to it — without this, the innerHTML swap that
// tears down the panel (including its own Close button) drops keyboard focus
// to `<body>` with no way back in via Tab (design audit #6).
async function _showAppDetail(appId, triggerBtn) {
  const host = _body().querySelector('#applicant-debug-detail-host');
  if (!host || !appId) return;
  if (triggerBtn) host._applicantDebugTrigger = triggerBtn;
  host.innerHTML = loadingHTML('Loading details…');
  let shots = { screenshots: [] }, wf = { steps: [] }, outcomes = { outcomes: [] };
  let anyErr = null;
  let snapshot = { has_snapshot: false };
  try { shots = await _fetchJSON(`${ADMIN}/screenshots/${encodeURIComponent(appId)}`); } catch (e) { anyErr = anyErr || e; }
  try { wf = await _fetchJSON(`${ADMIN}/workflow/${encodeURIComponent(appId)}`); } catch (e) { anyErr = anyErr || e; }
  try { outcomes = await _fetchJSON(`${ADMIN}/outcomes/${encodeURIComponent(appId)}`); } catch (e) { anyErr = anyErr || e; }
  try { snapshot = await _fetchJSON(`${ADMIN}/snapshot/${encodeURIComponent(appId)}`); } catch { /* snapshot is optional */ }
  if (anyErr && !shots.screenshots.length && !(wf.completed_steps || wf.steps || []).length && !outcomes.outcomes.length) {
    host.innerHTML = `<div class="admin-card">${_empty(anyErr.message || 'Could not load application details.')}</div>`;
    return;
  }
  const shotList = (shots.screenshots || []);
  const steps = (wf.completed_steps || wf.steps || []);
  const evs = (outcomes.outcomes || []);
  host.innerHTML = `<div class="admin-card" style="border:1px solid var(--border,#3334);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong>Application ${esc(appId)}</strong>
      <button class="admin-btn-sm" id="applicant-debug-detail-close">Close</button>
    </div>
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Screenshots</strong> (${shotList.length})</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;">
      ${shotList.length ? shotList.map((s) => {
          const label = s.page_ref || s.page || s.label || 'page';
          const src = _screenshotImgUrl(appId, s.id);
          if (!src) {
            // No id to build an image URL from — fall back to the plain-text label.
            return `<span class="admin-toggle-sub" style="opacity:0.7;" title="${esc(s.page_url || '')}">${esc(label)}</span>`;
          }
          return `<img class="applicant-debug-shot-thumb" src="${esc(src)}" alt="${esc(label)}" title="${esc(s.page_url || label)}" data-full="${esc(src)}" data-label="${esc(label)}" loading="lazy" tabindex="0" role="button" aria-label="View screenshot: ${esc(label)}" style="width:96px;height:64px;object-fit:cover;border-radius:6px;border:1px solid var(--border,#3334);cursor:zoom-in;" />`;
        }).join('') : _empty('No screenshots captured.')}
    </div>
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Workflow steps</strong></div>
    ${steps.length ? `<div class="admin-toggle-sub" style="opacity:0.7;">${steps.map((s) => esc(typeof s === 'string' ? s : (s.name || s.step || JSON.stringify(s)))).join(' → ')}</div>${wf.pending_recovery ? '<div class="admin-toggle-sub" style="color:var(--warn,#c80);">Pending recovery</div>' : ''}` : _empty('No durable workflow recorded.')}
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Outcomes</strong></div>
    ${evs.length ? `<div class="admin-toggle-sub" style="opacity:0.7;">${evs.map((e) => `${esc(e.type)} (${esc(e.source)})`).join(', ')}</div>` : _empty('No outcomes recorded yet.')}
    <div class="admin-toggle-sub" style="margin-top:8px;" title="An immutable record of exactly what was submitted: the answers, the document versions, the posting, and when."><strong>Submission record</strong></div>
    ${_renderSnapshot(snapshot)}
  </div>`;
  host.querySelector('#applicant-debug-detail-close').addEventListener('click', () => {
    host.innerHTML = '';
    const trigger = host._applicantDebugTrigger;
    if (trigger && document.body.contains(trigger)) trigger.focus();
  });
  host.querySelectorAll('.applicant-debug-shot-thumb').forEach((img) => {
    img.addEventListener('click', () => _openScreenshotLightbox(img.dataset.full, img.dataset.label, img));
    // Enter/Space activation (design audit lens 01/05 — keyboard operability
    // on custom controls): the thumbnail is a real `role="button"` + tabindex
    // now, so it needs the same native-button activation keys wired by hand.
    img.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
      e.preventDefault();
      _openScreenshotLightbox(img.dataset.full, img.dataset.label, img);
    });
    // The capture may already be gone (ephemeral /tmp, reclaimed after a restart) —
    // swap a broken thumbnail for the plain-text label rather than a blank icon.
    img.addEventListener('error', () => {
      const fallback = document.createElement('span');
      fallback.className = 'admin-toggle-sub';
      fallback.style.opacity = '0.7';
      fallback.title = img.title;
      fallback.textContent = img.dataset.label || 'page';
      img.replaceWith(fallback);
    }, { once: true });
  });
}

// Real screenshot pixels, not just a filename label (dark-engine audit #28):
// build the URL for one screenshot's raw image bytes. Returns '' when the
// record has no id to address (nothing to fetch).
function _screenshotImgUrl(appId, screenshotId) {
  if (!appId || !screenshotId) return '';
  return `${ADMIN}/screenshots/${encodeURIComponent(appId)}/${encodeURIComponent(screenshotId)}/image`;
}

// Full-size click-to-enlarge overlay for a screenshot thumbnail. Mirrors the
// chat attachment lightbox (chatRenderer.js `_openImageLightbox`) — same
// `.attach-lightbox` styling, reused rather than hand-rolled — simplified to a
// single image URL (screenshots have no separate thumb/full variant).
// `triggerEl` (the thumbnail that opened this) gets focus back on close —
// otherwise the overlay's removal drops keyboard focus to `<body>` with no
// way back to the Details panel via Tab (design audit #6's "re-renders
// destroy the focused element" pattern, same fix applied here).
function _openScreenshotLightbox(url, label, triggerEl) {
  if (!url) return;
  const overlay = document.createElement('div');
  overlay.className = 'attach-lightbox';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', label || 'Screenshot');
  overlay.tabIndex = -1;
  const img = document.createElement('img');
  img.alt = label || '';
  img.src = url;
  overlay.appendChild(img);
  const _onKey = (e) => { if (e.key === 'Escape') _close(); };
  const _close = () => {
    document.removeEventListener('keydown', _onKey);
    overlay.remove();
    if (triggerEl && document.body.contains(triggerEl)) triggerEl.focus();
  };
  overlay.addEventListener('click', _close);
  document.addEventListener('keydown', _onKey);
  document.body.appendChild(overlay);
  overlay.focus();
}

async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

async function _markSubmitted(appId, btn) {
  if (!appId || _busySubmit) return;
  _busySubmit = true;
  if (btn) btn.disabled = true;
  try {
    const ok = await _confirm(
      'Record that you submitted this application yourself? This helps the system learn which details convert.',
      { confirmText: 'Record it', cancelText: 'Cancel' });
    if (!ok) return;
    await _post(`${ADMIN}/applications/${encodeURIComponent(appId)}/mark-submitted`, {});
    _toast('Recorded — thanks, this helps the system learn.');
    _renderActivity();
  } catch (e) {
    _toast(e.message || 'Could not record that right now.');
  } finally {
    _busySubmit = false;
    if (btn) btn.disabled = false;
  }
}

// #102: an aligned key/value mini-grid instead of dot-joined prose ("N matched
// · N approved…") so the numbers compare down a column. `pairs` is
// [[label, value], …].
function _statGrid(pairs) {
  return `<div class="applicant-debug-statgrid">${pairs.map(([k, v]) => `
    <span class="applicant-debug-statgrid-k">${esc(k)}</span><span class="applicant-debug-statgrid-v">${esc(v)}</span>`).join('')}</div>`;
}

// Insights — a read-only window onto what the system has learned for this job
// search: overall conversion, each source's funnel ranked by how well it
// converts, the roles that actually convert, and the exploration knob. Plain
// language only; mirrors the Sources/Run card style.
async function _renderInsights() {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${ADMIN}/learning/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const s = data.summary || {};
  const sources = data.sources || [];
  const roles = data.converting_roles || [];
  const num = (v) => (v != null ? v : 0);

  const summaryCard = `<div class="admin-card">
    <div style="font-weight:600;">Conversion so far</div>
    ${_statGrid([
      ['Matched', num(s.total_matched)],
      ['Approved', num(s.total_approved)],
      ['Submitted', num(s.total_submitted)],
      ['Sources seen', num(s.sources_seen)],
    ])}
    <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:6px;">This is what the system uses to decide which sources and roles to favour next.</span>
  </div>`;

  const rolesCard = `<div class="admin-card">
    <div style="font-weight:600;">Roles that convert</div>
    ${roles.length
      ? `<div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">${roles.map((r) => esc(r)).join(' · ')}</div>`
      : _empty('Not enough approved/submitted roles yet to spot a pattern.')}
    <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:6px;">Discovery and scoring lean toward roles that look like these.</span>
  </div>`;

  const budgetCard = data.exploration_budget != null
    ? `<div class="admin-card">
        <div style="font-weight:600;">Exploration budget</div>
        <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">
          ${esc(Math.round(Number(data.exploration_budget) * 100))}% — share of effort spent trying new or under-used sources instead of the proven ones.
        </div>
        <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:6px;">Change this under Config → Sources.</span>
      </div>`
    : '';

  // #100: was one bordered `.admin-card` tile per source (same glass-on-glass
  // stacking as the #93 Sources/Tools toggle rows) — one flat list with
  // hairline row dividers instead.
  let sourcesCard;
  if (!sources.length) {
    sourcesCard = `<div class="admin-card"><div style="font-weight:600;">Best sources</div>${_empty('No source results recorded for this job search yet.')}</div>`;
  } else {
    const rows = sources.map((src) => {
      const rate = src.conversion_rate != null ? `${esc(src.conversion_rate)}% convert` : 'no rate yet';
      return `<div class="applicant-debug-list-row" style="align-items:flex-start;">
        <div style="min-width:0;">
          <div style="font-weight:600;">${esc(src.source)}</div>
          ${_statGrid([
            ['Matched', num(src.matched)],
            ['Approved', num(src.approved)],
            ['Submitted', num(src.submitted)],
          ])}
        </div>
        <div class="admin-toggle-sub" style="opacity:0.75;flex-shrink:0;">${esc(rate)}</div>
      </div>`;
    }).join('');
    sourcesCard = `<div class="admin-toggle-sub" style="opacity:0.7;margin:10px 0 6px;">Best sources (ranked by how well they convert)</div><div class="applicant-debug-list">${rows}</div>`;
  }

  _body().innerHTML = summaryCard + rolesCard + budgetCard + sourcesCard;
}

// Best-effort split of one raw log entry into { time, level, message } so it can
// render as a structured row. Falls back to putting the whole thing in
// `message` when the shape/format isn't recognized — never throws or drops data.
function _parseLogEntry(e) {
  if (e && typeof e === 'object') {
    const time = e.timestamp || e.time || e.ts || e.created_at || '';
    const level = e.level || e.lvl || e.severity || '';
    const message = e.message || e.msg || e.text || JSON.stringify(e);
    return { time: String(time), level: String(level).toUpperCase(), message: String(message) };
  }
  const line = String(e == null ? '' : e);
  const m = line.match(/^([\d:\-.TZ+]{8,32})\s*[[(]?(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL)[\])]?\s*[:\-]?\s*(.*)$/i);
  if (m) return { time: m[1].trim(), level: m[2].toUpperCase(), message: (m[3] || '').trim() || line };
  return { time: '', level: '', message: line };
}

function _logLevelColor(level) {
  const l = String(level || '').toLowerCase();
  if (l === 'error' || l === 'critical') return 'var(--color-error, #ff4444)';
  if (l === 'warn' || l === 'warning') return 'var(--color-warning, #f0ad4e)';
  return 'var(--color-muted, #888)';
}

// #95: logs used to render as one raw `<pre>` blob. Structured rows (time ·
// level chip · plain message) instead — the raw text is still one click away
// via Download, for anyone who wants to grep/attach the whole thing.
//
// lens 12 #35: this used to hardcode `?limit=100` against the engine's
// `deque(maxlen=500)` ring (src/applicant/observability/logging.py) with no
// way to see more or narrow down — precisely the crash a self-hoster most
// wants to diagnose could scroll off both the view and the download. Fetch
// the fuller ring (up to the 500 the engine keeps; `admin.py`'s `/logs` route
// clamps `limit` to 1000 anyway) and add a lightweight client-side level +
// text filter over the fetched entries — download still exports everything
// fetched, not just what's currently filtered into view.
async function _renderLogs() {
  const data = await _fetchJSON(`${ADMIN}/logs?limit=500`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const entries = data.entries || [];
  if (!entries.length) { _body().innerHTML = _empty('No recent activity logs.'); return; }
  const raw = entries.map((e) => (typeof e === 'string' ? e : JSON.stringify(e))).join('\n');
  const parsed = entries.map(_parseLogEntry);
  const levels = Array.from(new Set(parsed.map((p) => p.level).filter(Boolean))).sort();
  const levelOptions = ['<option value="">All levels</option>']
    .concat(levels.map((l) => `<option value="${esc(l)}">${esc(l)}</option>`))
    .join('');
  _body().innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px;">
      <select id="applicant-logs-level" class="settings-input" style="width:auto;" title="Show only this log level" aria-label="Filter logs by level">${levelOptions}</select>
      <input type="text" id="applicant-logs-q" class="settings-input" placeholder="Filter by text…" style="flex:1;min-width:140px;" title="Only show log lines containing this text" aria-label="Filter logs by text" />
      <span id="applicant-logs-count" class="admin-toggle-sub" style="opacity:0.6;white-space:nowrap;"></span>
      <button class="cal-btn" id="applicant-logs-download" title="Download all fetched logs as a text file">Download logs</button>
    </div>
    <div class="applicant-debug-list" id="applicant-logs-rows"></div>`;
  const levelSel = _body().querySelector('#applicant-logs-level');
  const qInput = _body().querySelector('#applicant-logs-q');
  const rowsEl = _body().querySelector('#applicant-logs-rows');
  const countEl = _body().querySelector('#applicant-logs-count');
  const renderRows = () => {
    const level = levelSel ? levelSel.value : '';
    const q = qInput ? qInput.value.trim().toLowerCase() : '';
    const filtered = parsed.filter((p) => {
      if (level && p.level !== level) return false;
      if (q && !p.message.toLowerCase().includes(q) && !p.time.toLowerCase().includes(q)) return false;
      return true;
    });
    if (countEl) countEl.textContent = `${filtered.length} of ${parsed.length}`;
    if (!rowsEl) return;
    rowsEl.innerHTML = filtered.length
      ? filtered.map((p) => {
        const when = p.time ? (_relWhen(p.time) || p.time) : '';
        const color = _logLevelColor(p.level);
        const chip = p.level
          ? `<span style="flex-shrink:0;font-size:10px;font-weight:600;padding:1px 6px;border-radius:4px;color:${color};background:color-mix(in srgb, ${color} 15%, transparent);">${esc(p.level)}</span>`
          : '';
        return `<div class="applicant-debug-list-row" style="align-items:flex-start;">
          <span class="admin-toggle-sub" style="opacity:0.55;flex-shrink:0;min-width:60px;">${esc(when)}</span>
          ${chip}
          <span style="flex:1;min-width:0;word-break:break-word;">${esc(p.message)}</span>
        </div>`;
      }).join('')
      : _empty('No log entries match this filter.');
  };
  renderRows();
  if (levelSel) levelSel.addEventListener('change', renderRows);
  if (qInput) qInput.addEventListener('input', renderRows);
  const downloadBtn = _body().querySelector('#applicant-logs-download');
  if (downloadBtn) downloadBtn.addEventListener('click', () => _downloadText(raw, `applicant-logs-${_campaignId || 'engine'}.txt`));
}

// Copy a value to the clipboard, reusing the workspace copy helper (which shows
// its own "Copied" toast) when present; otherwise fall back with our own toast.
function _copy(text) {
  try {
    if (uiModule && typeof uiModule.copyToClipboard === 'function') { uiModule.copyToClipboard(text); return; }
  } catch { /* fall through */ }
  try { navigator.clipboard.writeText(text); _toast('Copied.'); } catch { _toast('Could not copy.'); }
}

// Download a plain-text blob — used by Logs (#95) to keep the raw text one
// click away even though the visible view is now structured rows.
function _downloadText(text, filename) {
  try {
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch {
    _toast('Could not download the logs right now.');
  }
}

// A short, plain-language label for a variant row — shared by the row list and
// the A/B nudge so both name the same variant the same way.
function _variantLabel(v) {
  return v.is_root ? 'Base resume' : (v.variant_id || v.id || 'Variant');
}

// design-audit Top-25 #19 (per-variant A/B scoreboard): when two-or-more
// variants have enough tracked uses to compare AND one is clearly converting
// to interviews more often than another, surface a one-line plain-language
// nudge. Deliberately conservative — both sides need at least 2 tracked uses
// and the gap must be at least 20 percentage points — so a single lucky/unlucky
// application can't produce a confident-sounding claim from noise. Returns ''
// when there isn't a clean enough signal to say anything.
function _variantNudge(variants) {
  const comparable = variants.filter((v) => (v.uses || 0) >= 2 && v.interview_rate != null);
  if (comparable.length < 2) return '';
  const sorted = [...comparable].sort((a, b) => b.interview_rate - a.interview_rate);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];
  if (best.interview_rate - worst.interview_rate < 20) return '';
  const bestLabel = esc(_variantLabel(best));
  const worstLabel = esc(_variantLabel(worst));
  const msg = worst.interview_rate > 0
    ? `${bestLabel} converts to interviews ${(best.interview_rate / worst.interview_rate).toFixed(1)}x more often than ${worstLabel} — consider using it more.`
    : `${bestLabel} is converting to interviews while ${worstLabel} hasn't yet — consider using ${bestLabel} more.`;
  return `<div class="admin-toggle-sub" style="opacity:0.85;margin:2px 0 10px;padding:8px 10px;border-radius:6px;background:color-mix(in srgb, var(--color-success, #4caf50) 12%, transparent);">${msg}</div>`;
}

// #100: was one bordered `.admin-card` tile per variant (same glass-on-glass
// stacking as the #93 Sources/Tools toggle rows) — one flat list with
// hairline row dividers instead, self-contained (this tab renders straight
// to _body(), so it owns its own `.applicant-debug-list` box).
// design-audit Top-25 #19: each row now also shows how many times the variant
// was actually submitted and, once the outcome trail has enough data, its
// interview rate — plus a top-of-tab nudge (`_variantNudge`) when one variant
// is clearly outperforming another.
async function _renderVariants() {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${ADMIN}/variants/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const variants = data.variants || [];
  if (!variants.length) { _body().innerHTML = _empty('No resume variants built for this job search yet.'); return; }
  const nudge = _variantNudge(variants);
  const rows = variants.map((v) => {
    const id = v.variant_id || v.id || 'Variant';
    const scores = v.fit_scores || {};
    const scoreVals = Object.values(scores);
    const scoreText = scoreVals.length
      ? `best fit ${esc(Math.max(...scoreVals.map(Number)).toFixed(2))}`
      : (v.score != null ? `score ${esc(v.score)}` : 'not scored');
    const approved = v.approved === true ? 'approved' : (v.approval_state || 'awaiting review');
    const uses = v.uses || 0;
    const usesText = uses === 1 ? '1 use' : `${esc(uses)} uses`;
    const rateText = v.interview_rate != null ? `${esc(v.interview_rate)}% interview rate` : 'not enough data yet';
    return `<div class="applicant-debug-list-row">
    <div style="min-width:0;">
      <div style="font-weight:600;">${esc(v.is_root ? 'Base resume' : id)}</div>
      <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">
        ${esc(scoreText)} · ${esc(approved)}${v.lineage_depth ? ` · ${esc(v.lineage_depth)} edits deep` : ''}${v.parent_id ? ` · from ${esc(v.parent_id)}` : ''}
      </div>
      <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">
        ${usesText} · ${rateText}
      </div>
    </div>
  </div>`;
  }).join('');
  _body().innerHTML = `${nudge}<div class="applicant-debug-list">${rows}</div>`;
}

const RUN_MODES = [
  ['continuous', 'Around the clock'],
  ['fixed_duration', 'Fixed window'],
  ['until_n_viable', 'Until target reached'],
];

// Plain-language mapping for the engine's machine skip/stop reasons (dark-engine
// audit #64) — shared by the "Run now" result toast and the "Why nothing's
// happening right now" note on the Run controls tab, so the same machine code
// always reads the same way wherever it surfaces.
const _SKIP_REASON_LABELS = {
  budget_exhausted: "Today's application limit is reached — it'll resume tomorrow.",
  automated_work_gated: 'Waiting on setup — finish connecting a model and your profile before I can start new work.',
  campaign_not_found: 'That job search no longer exists.',
  run_mode_stop: 'Paused — your run schedule says to hold off starting new work right now.',
};

// Short relative time from an ISO timestamp, e.g. "12s ago" / "in 48s" / "3m ago".
// Returns '' for missing/unparseable input so callers can omit the line cleanly.
function _relWhen(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (isNaN(t)) return '';
  let secs = Math.round((t - Date.now()) / 1000);
  const future = secs > 0;
  secs = Math.abs(secs);
  let txt;
  if (secs < 60) txt = `${secs}s`;
  else if (secs < 3600) txt = `${Math.round(secs / 60)}m`;
  else if (secs < 86400) txt = `${Math.round(secs / 3600)}h`;
  else txt = `${Math.round(secs / 86400)}d`;
  return future ? `in ${txt}` : `${txt} ago`;
}

// A coloured live-status chip (Running / Idle / Paused / Setup needed) for the
// Run controls tab, built from the engine status payload (FR-AGENT-7/FR-OBS-2).
// #88: the label itself carries no colour (neutral ink) — only the dot does,
// and it's a plain system-token fill now, no raw hex and no perpetual pulse.
function _statusChip(status) {
  const sched = status.scheduler || {};
  let label;
  let color;
  if (status.paused === true || status.active === false) {
    label = 'Paused'; color = 'var(--color-warning, #f0ad4e)';
  } else if (sched.running === true) {
    label = 'Working now'; color = 'var(--color-success, #4caf50)';
  } else {
    label = 'Idle'; color = 'var(--color-muted, #8b949e)';
  }
  const dot = `<span aria-hidden="true" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${color};margin-right:7px;"></span>`;
  const bits = [];
  if (sched.last_tick) bits.push(`last run ${esc(_relWhen(sched.last_tick))}`);
  if (sched.next_tick && status.paused !== true) bits.push(`next ${esc(_relWhen(sched.next_tick))}`);
  if (status.applied_today != null) {
    const cap = status.daily_budget != null ? status.daily_budget : status.throughput_target;
    bits.push(`${esc(status.applied_today)}${cap != null ? ` / ${esc(cap)}` : ''} today`);
  }
  // Per-campaign tick failures / overlap-skips (dark-engine audit #73) — omitted
  // entirely when this campaign has never failed or been skipped (the common
  // case), so a healthy campaign's chip is unchanged.
  const health = sched.campaign;
  let healthLine = '';
  if (health && typeof health === 'object') {
    const parts = [];
    if (health.failure_count) {
      const when = _relWhen(health.last_error_at);
      parts.push(`last error${when ? ` ${when}` : ''}${health.last_error ? `: ${health.last_error}` : ''}`);
    }
    if (health.skipped_count) {
      parts.push(`skipped ${health.skipped_count} time${health.skipped_count === 1 ? '' : 's'} — a previous run was still in progress`);
    }
    if (parts.length) {
      healthLine = `<div class="admin-toggle-sub" style="opacity:0.8;color:var(--orange, #ffb86c);margin-top:6px;">${esc(parts.join(' · '))}</div>`;
    }
  }
  return `
    <div class="admin-card">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;font-weight:600;">${dot}${esc(label)}</div>
        <div class="admin-toggle-sub" style="opacity:0.75;">${bits.join(' · ')}</div>
      </div>
      ${healthLine}
    </div>`;
}

// Recent runs mini-table (dark-engine audit #75): every tick already persists
// per-run stats (discovered / shortlisted / pre-filling / handed off / completed
// / today's budget remaining, or a plain skip reason when nothing started) to
// ``agent_runs``, and this SAME ops proxy already returns the full list — but
// the Run controls tab only ever read ``items[0]`` for the config defaults
// above and silently dropped the rest. Mirrors applicantActivity.js's own
// "Recently I…" run-history rendering (same stat vocabulary, same tone).
function _runStatLine(stats) {
  if (!stats || typeof stats !== 'object') return '';
  if (stats.skip_reason) {
    return _SKIP_REASON_LABELS[stats.skip_reason] || 'Skipped — nothing started this run.';
  }
  const parts = [];
  const push = (n, label) => {
    const v = Number(n);
    if (Number.isFinite(v) && v > 0) parts.push(`${label} ${v}`);
  };
  push(stats.discovered, 'Discovered');
  push(stats.digest_rows, 'shortlisted');
  push(stats.pipelines_started, 'pre-filling');
  push(stats.handoffs, 'handed to you');
  push(stats.completed, 'completed');
  return parts.join(' · ');
}

function _recentRunsCard(items) {
  if (!items.length) return '';
  // The engine returns runs oldest-first; show the newest handful, newest on top.
  const rows = items.slice(-8).reverse().map((r) => {
    const when = _relWhen(r.timestamp) || '';
    const line = _runStatLine(r.stats) || r.intent || 'Ran.';
    return `<div class="applicant-debug-list-row" style="align-items:flex-start;">
      <div style="min-width:0;">${esc(line)}</div>
      <span class="admin-toggle-sub" style="opacity:0.55;flex-shrink:0;">${esc(when)}</span>
    </div>`;
  }).join('');
  return `
    <div class="applicant-debug-list" style="margin-top:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Recent runs</div>
      ${rows}
    </div>`;
}

async function _renderRun() {
  if (!_needCampaign()) return;
  let intent = { intent: null };
  let runs = { items: [] };
  let status = {};
  try { status = await _fetchJSON(`${OPS}/runs/${encodeURIComponent(_campaignId)}/status`); } catch { /* soft */ }
  try { intent = await _fetchJSON(`${OPS}/runs/${encodeURIComponent(_campaignId)}/intent`); } catch { /* soft */ }
  try { runs = await _fetchJSON(`${OPS}/runs/${encodeURIComponent(_campaignId)}`); } catch { /* soft */ }
  // A setup gate (engine up, automated work blocked until setup is finished) is
  // honestly surfaced as the setup message, not "not reachable".
  if (_isGated(status) || _isGated(runs) || _isGated(intent)) {
    _renderGated(status.gated ? status : (runs.gated ? runs : intent)); return;
  }
  if (_isOffline(intent) && _isOffline(runs) && _isOffline(status)) {
    _renderOffline(); return;
  }
  const last = (runs.items || [])[0] || {};
  // Prefer the live status payload for the config defaults; fall back to the latest run.
  const curMode = status.run_mode || last.run_mode;
  const curTarget = status.throughput_target != null ? status.throughput_target : last.throughput_target;
  const intentText = intent.intent || status.latest_intent;
  const paused = status.paused === true || status.active === false;
  const haveStatus = status.engine_available !== false && status.campaign_id;
  // Dark-engine audit #64: a run whose stats carry a machine ``skip_reason``
  // (the engine now persists ONE of these per gate transition, not per tick)
  // means the intent sentence is explaining why nothing is happening right now,
  // not narrating active work — head the card accordingly instead of the
  // generic "What the agent is doing" label.
  const skipReason = status.latest_stats && status.latest_stats.skip_reason;
  const doingTitle = skipReason ? "Why nothing's happening right now" : 'What the agent is doing';
  _body().innerHTML = `
    ${haveStatus ? _statusChip(status) : ''}
    <div class="admin-card">
      <div style="font-weight:600;">${esc(doingTitle)}</div>
      <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">${esc(intentText || 'No run yet — use “Run now” or set a mode and target below to start.')}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">
        <button class="cal-btn cal-btn-primary" id="applicant-run-now">Run now</button>
        <button class="cal-btn" id="applicant-run-pause">${paused ? 'Resume' : 'Pause'}</button>
      </div>
      <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:8px;">“Run now” discovers, scores and refreshes the digest immediately instead of waiting for the next scheduled pass.</span>
    </div>
    <div class="admin-card">
      <div style="font-weight:600;margin-bottom:8px;">Run controls</div>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:8px;">How it runs
        <select id="applicant-run-mode" class="ow-select" style="display:block;margin-top:4px;min-width:220px;">
          ${RUN_MODES.map(([k, label]) => `<option value="${k}"${(curMode === k) ? ' selected' : ''}>${esc(label)}</option>`).join('')}
        </select>
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:8px;">Applications per day (target)
        <input type="number" id="applicant-run-target" class="settings-select" min="0" value="${esc(curTarget != null ? curTarget : '')}" style="display:block;margin-top:4px;width:120px;" />
      </label>
      <span class="admin-toggle-sub" style="opacity:0.6;display:block;">Targets above the safe daily cap are clamped automatically.</span>
      <button class="cal-btn cal-btn-primary" id="applicant-run-save" style="margin-top:10px;">Save run settings</button>
    </div>
    ${_recentRunsCard(runs.items || [])}`;
  _body().querySelector('#applicant-run-save').addEventListener('click', async (ev) => {
    if (_busySave) return;
    _busySave = true;
    const saveBtn = ev.currentTarget;
    if (saveBtn) saveBtn.disabled = true;
    const mode = _body().querySelector('#applicant-run-mode').value;
    const tRaw = _body().querySelector('#applicant-run-target').value;
    const body = { run_mode: mode };
    if (tRaw !== '') body.throughput_target = parseInt(tRaw, 10);
    try {
      const res = await _put(`${OPS}/runs/${encodeURIComponent(_campaignId)}/config`, body);
      _toast(`Saved. Daily target: ${res.throughput_target != null ? res.throughput_target : '—'}${res.hard_cap != null ? ` (cap ${res.hard_cap})` : ''}.`);
      _renderRun();
    } catch (e) {
      _toast(e.message || 'Could not save run settings.');
    } finally {
      _busySave = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  });
  const runNowBtn = _body().querySelector('#applicant-run-now');
  if (runNowBtn) runNowBtn.addEventListener('click', async () => {
    runNowBtn.disabled = true;
    const prev = runNowBtn.textContent;
    runNowBtn.textContent = 'Running…';
    try {
      const res = await _post(`${OPS}/runs/${encodeURIComponent(_campaignId)}/run`, {});
      if (res.ran === false) {
        // Map the engine's machine reason to the SAME plain-language message the
        // "Why nothing's happening right now" note uses (dark-engine audit #64).
        _toast(_SKIP_REASON_LABELS[res.reason] || res.reason || 'Nothing to run right now.');
      } else {
        const found = res.discovered != null ? `Found ${res.discovered} posting(s).` : 'Run complete.';
        _toast(found);
      }
    } catch (e) {
      _toast(e.message || 'Could not run now.');
    } finally {
      runNowBtn.disabled = false;
      runNowBtn.textContent = prev;
      _renderRun();
    }
  });
  const pauseBtn = _body().querySelector('#applicant-run-pause');
  if (pauseBtn) pauseBtn.addEventListener('click', async () => {
    pauseBtn.disabled = true;
    try {
      await _post(`${OPS}/runs/${encodeURIComponent(_campaignId)}/${paused ? 'resume' : 'pause'}`, {});
      _toast(paused ? 'Resumed automated work.' : 'Paused automated work.');
    } catch (e) {
      _toast(e.message || 'Could not change run state.');
    } finally {
      pauseBtn.disabled = false;
      _renderRun();
    }
  });
}

async function _renderSources(host) {
  host = host || _body();
  if (!_needCampaignIn(host)) return;
  const data = await _fetchJSON(`${OPS}/discovery/${encodeURIComponent(_campaignId)}`);
  if (_isGated(data)) { _renderGated(data, host); return; }
  if (_isOffline(data)) { _renderOffline(undefined, host); return; }
  const items = data.items || [];
  // Exploration budget (FR-LEARN-6): the explore/exploit knob. Shown above the
  // source list. Editable when the engine reports it; read-only note otherwise.
  const hasBudget = data.exploration_budget != null && !isNaN(Number(data.exploration_budget));
  // Percent-based (0-100), matching Campaign settings' "Trying new sources" field
  // (applicantCampaignSettings.js) so the same knob teaches one mental model
  // everywhere it appears (lens 12 #10). The engine stores/expects a 0.0-1.0
  // fraction (criteria.py `set_exploration_budget`), so the UI boundary here
  // converts on the way in and back out.
  const budgetPct = hasBudget ? Math.round(Number(data.exploration_budget) * 100) : 0;
  const budgetCard = hasBudget
    ? `<div class="admin-card" style="margin-bottom:10px;">
        <div style="font-weight:600;">Exploration budget</div>
        <div class="admin-toggle-sub" style="opacity:0.7;margin:2px 0 8px;">How much effort to spend trying new or under-used sources instead of the proven ones. 0% sticks to what works; 100% explores the most.</div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="number" id="applicant-explore-budget" class="settings-input" min="0" max="100" step="5" value="${esc(String(budgetPct))}" style="width:90px;" title="A percentage between 0 and 100." aria-label="Exploration budget, a percentage between 0 and 100" />
          <span class="admin-toggle-sub" style="opacity:0.7;">%</span>
          <button class="cal-btn" id="applicant-explore-save" title="Save the exploration budget">Save</button>
          <span id="applicant-explore-msg" class="admin-toggle-sub" style="opacity:0.7;"></span>
        </div>
      </div>`
    : '';
  if (!items.length) {
    host.innerHTML = budgetCard + _empty('No job-discovery sources available for this job search.');
    _wireExploreBudget(host);
    return;
  }
  // #93: one flat list with hairline row dividers (`.applicant-debug-list-row`)
  // instead of one bordered `.admin-card` tile per source. The host is already
  // hosted inside _renderConfig's own `.applicant-debug-list` section box, so
  // the rows render directly (no second nested list box) — the exploration
  // budget above stays its own standalone card (a distinct input+button
  // control, not a toggle row in the list).
  const rows = items.map((s) => {
    const ys = s.yield_stats || {};
    const hasFunnel = ys.matches != null || ys.approvals != null || ys.submissions != null;
    const stat = hasFunnel
      ? `${ys.matches != null ? ys.matches : 0} matched · ${ys.approvals != null ? ys.approvals : 0} approved · ${ys.submissions != null ? ys.submissions : 0} submitted`
      : 'no yield data yet';
    return `<div class="applicant-debug-list-row">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(s.source_key)}</div>
        <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">${esc(stat)}</div>
      </div>
      <label class="admin-switch" style="flex-shrink:0;" title="Turn this source on or off">
        <input type="checkbox" class="applicant-source-toggle" data-key="${esc(s.source_key)}"${s.enabled ? ' checked' : ''} aria-label="Turn ${esc(s.source_key)} on or off" />
        <span class="admin-slider"></span>
      </label>
    </div>`;
  }).join('');
  host.innerHTML = budgetCard + rows;
  host.querySelectorAll('.applicant-source-toggle').forEach((cb) => {
    cb.addEventListener('change', async () => {
      // Disable for the round-trip so a fast double-toggle can't race two
      // in-flight requests against each other (micro-interactions audit —
      // busy/disabled affordance on a control that mutates immediately).
      cb.disabled = true;
      try {
        await _put(`${OPS}/discovery/${encodeURIComponent(_campaignId)}/${encodeURIComponent(cb.dataset.key)}`, { enabled: cb.checked });
        _toast(`${cb.dataset.key} ${cb.checked ? 'on' : 'off'}.`);
      } catch (e) {
        cb.checked = !cb.checked; // revert on failure
        _toast(e.message || 'Could not change that source.');
      } finally {
        cb.disabled = false;
      }
    });
  });
  _wireExploreBudget(host);
}

function _wireExploreBudget(host) {
  host = host || _body();
  const input = host.querySelector('#applicant-explore-budget');
  const btn = host.querySelector('#applicant-explore-save');
  const msg = host.querySelector('#applicant-explore-msg');
  if (!input || !btn) return; // read-only / not exposed by the engine
  btn.addEventListener('click', async () => {
    const pct = parseFloat(input.value);
    if (isNaN(pct) || pct < 0 || pct > 100) {
      if (msg) msg.textContent = 'Enter a percentage between 0 and 100.';
      return;
    }
    // UI boundary conversion: Campaign settings and this control both speak
    // percent (0-100); the engine's exploration-budget endpoint stores/expects
    // a 0.0-1.0 fraction (criteria.py `set_exploration_budget`).
    const val = Math.max(0, Math.min(pct, 100)) / 100;
    btn.disabled = true;
    if (msg) msg.textContent = 'Saving…';
    try {
      await _put(`${OPS}/discovery/${encodeURIComponent(_campaignId)}/exploration-budget`, { exploration_budget: val });
      if (msg) msg.textContent = 'Saved.';
      _toast('Exploration budget saved.');
    } catch (e) {
      if (msg) msg.textContent = e.message || 'Could not save that.';
    } finally {
      btn.disabled = false;
    }
  });
}

// Detection events — dark-engine audit #26: DetectionEvent.signal_type/detail
// (bot-checks/blocks the automated browser hit while filling in an application)
// was already persisted and proxied (${ADMIN}/detections/{campaign_id}) but had
// zero JS consumers anywhere. Campaign-scoped, mirrors the Sources sub-section's
// need-a-campaign guard just above.
const _DETECTION_LABELS = {
  captcha: 'A CAPTCHA challenge appeared',
  turnstile: 'A Cloudflare Turnstile challenge appeared',
  datadome: 'A bot-detection challenge (DataDome) appeared',
  cloudflare: 'A Cloudflare security check appeared',
  rate_limited: 'The site rate-limited the automated browser',
  blocked_403: 'The site blocked the automated browser',
  account_friction: 'The site flagged repeated attempts (a lockout-style warning)',
  anomalous_redirect: 'The automated browser landed on an unexpected page',
};

// Plain-language sentence for one detection's `signal_type` — falls back to a
// still-honest generic line (never the raw machine code alone) for a type not
// in the table above, so a new engine-side signal never renders as jargon.
function _detectionLabel(signalType) {
  const key = String(signalType || '').toLowerCase();
  return _DETECTION_LABELS[key] || 'This site may have detected automated browsing';
}

async function _renderDetections(host) {
  host = host || _body();
  if (!_needCampaignIn(host)) return;
  const data = await _fetchJSON(`${ADMIN}/detections/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const entries = data.detections || [];
  const intro = `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Moments this job search's automated browsing was challenged or blocked by a site — so a pattern of blocks is visible instead of silently retried.</div>`;
  if (!entries.length) {
    host.innerHTML = intro + _empty('No detection events recorded for this job search yet.');
    return;
  }
  const rows = entries.map((e) => {
    const when = e.timestamp ? (_relWhen(e.timestamp) || e.timestamp) : '';
    const detail = e.detail && typeof e.detail === 'object'
      ? Object.entries(e.detail)
        .filter(([k, v]) => k !== 'body' && v != null && v !== '')
        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join(' · ')
      : '';
    return `<div class="applicant-debug-list-row" style="align-items:flex-start;">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(_detectionLabel(e.signal_type))}</div>
        ${detail ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">${esc(detail)}</div>` : ''}
      </div>
      <span class="admin-toggle-sub" style="opacity:0.55;flex-shrink:0;">${esc(when)}</span>
    </div>`;
  }).join('');
  host.innerHTML = intro + `<div class="applicant-debug-list">${rows}</div>`;
}

async function _renderTools(host) {
  host = host || _body();
  // Engine-wide tool registry (not campaign-scoped): list every tool with an
  // on/off switch. Mirrors the Sources tab's switch rendering.
  const data = await _fetchJSON(`${ADMIN}/tools`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const tools = data.tools || [];
  if (!tools.length) { host.innerHTML = _empty('No tools reported by the engine.'); return; }
  // #93: one flat list with hairline row dividers (`.applicant-debug-list-row`)
  // instead of one bordered `.admin-card` tile per tool — mirrors the Sources
  // fix above. The host is already hosted inside _renderConfig's own
  // `.applicant-debug-list` section box, so the rows render directly (no
  // second nested list box).
  host.innerHTML =
    `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Turn the assistant's tools on or off. Disabled tools are never used while it works.</div>` +
    tools.map((t) => {
      const key = t.key != null ? t.key : '';
      const label = t.label || key;
      return `<div class="applicant-debug-list-row">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(label)}</div>
        ${t.description ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">${esc(t.description)}</div>` : ''}
      </div>
      <label class="admin-switch" style="flex-shrink:0;" title="Turn this tool on or off">
        <input type="checkbox" class="applicant-tool-toggle" data-key="${esc(key)}"${t.enabled ? ' checked' : ''} aria-label="Turn ${esc(label)} on or off" />
        <span class="admin-slider"></span>
      </label>
    </div>`;
    }).join('');
  host.querySelectorAll('.applicant-tool-toggle').forEach((cb) => {
    cb.addEventListener('change', async () => {
      // Same busy-disable guard as the Sources toggle above.
      cb.disabled = true;
      try {
        await _post(`${ADMIN}/tools/${encodeURIComponent(cb.dataset.key)}`, { enabled: cb.checked });
        _toast(`${cb.dataset.key} ${cb.checked ? 'on' : 'off'}.`);
      } catch (e) {
        cb.checked = !cb.checked; // revert on failure
        _toast(e.message || 'Could not change that tool.');
      } finally {
        cb.disabled = false;
      }
    });
  });
}

// Diagnostics — dark-engine audit #34: pre-fill silently degrades a credential
// lookup crash, an all-scopes vault outage, an LLM-mapping failure, or a
// transient browser error during login (it never crashes the run) but banks a
// plain-language trace instead of losing it. Engine-wide (not campaign-scoped),
// mirrors the Tools sub-section rendering just above.
async function _renderDiagnostics(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/prefill-diagnostics`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const entries = data.diagnostics || [];
  if (!entries.length) {
    host.innerHTML =
      `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Recent issues where filling in an application ran into trouble but kept going instead of stopping — so nothing gets lost silently.</div>` +
      _empty('No issues recorded recently.');
    return;
  }
  host.innerHTML =
    `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Recent issues where filling in an application ran into trouble but kept going instead of stopping — so nothing gets lost silently.</div>` +
    `<div class="applicant-debug-list">${entries.map((msg) => `<div class="applicant-debug-list-row">
      <span style="flex:1;min-width:0;word-break:break-word;">${esc(String(msg))}</span>
    </div>`).join('')}</div>`;
}

// Stealth posture — dark-engine audit #27: GET /api/admin/stealth reports the
// live egress posture (connection mode / residential attestation / proxy) plus
// the honest best-effort caveat, and is already proxied (${ADMIN}/stealth), but
// only the single caveat line was ever read (the narrow `/caveat` lane used by
// applicantRemote.js / applicantToday.js / applicantPortal.js near the takeover
// surface) — the fuller posture had zero consumers anywhere. Engine-wide (not
// campaign-scoped), mirrors the Diagnostics sub-section just above.
function _egressModeLabel(mode) {
  const m = String(mode || '').toLowerCase().replace(/_/g, '-');
  return m === 'residential-proxy' ? 'Residential proxy' : 'Direct connection';
}

async function _renderStealth(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/stealth`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const egress = data.egress || {};
  const rows = [
    ['Connection', _egressModeLabel(egress.mode)],
    ['Looks like a home internet connection', egress.is_direct_residential ? 'Yes' : 'No'],
    ['Using a proxy', egress.proxy_configured ? 'Yes' : 'No'],
  ];
  const caveat = data.caveat || data.egress_caveat;
  host.innerHTML =
    `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">What the automated browser presents to job sites right now — the honest, best-effort picture; no anti-detection setup is ever guaranteed to be undetectable.</div>` +
    _statGrid(rows) +
    (caveat ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:8px;">${esc(caveat)}</div>` : '');
}

// Background connection (workspace bridge) — dark-engine audit #71:
// ``HttpWorkspaceClient.ping`` existed exactly for a health probe but nothing
// called it and no surface showed whether the shared secret is even configured
// — a missing/wrong token silently disables calendar-interview sync,
// deep-research, and the memory/skills bridge with nothing telling the owner
// why any of those quietly do nothing. Engine-wide (not campaign-scoped),
// mirrors the Stealth posture sub-section just above.
async function _renderBridge(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/workspace-bridge`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const intro = `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Whether the assistant's background link to this workspace — used for calendar sync, deep research, and shared memory — is set up and actually working.</div>`;
  if (!data.configured) {
    host.innerHTML = intro + _empty('Not set up yet — calendar sync, deep research, and shared memory are unavailable until it is.');
    return;
  }
  const rows = [
    ['Set up', 'Yes'],
    ['Reachable right now', data.reachable ? 'Yes' : 'No'],
  ];
  const detail = !data.reachable && data.detail ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:8px;">${esc(String(data.detail))}</div>` : '';
  host.innerHTML = intro + _statGrid(rows) + detail;
}

// Captcha handling — dark-engine audit #67: the captcha strategy is
// configurable (CAPTCHA_STRATEGY) and the composite solver decides
// avoid/solve/handoff, but nothing showed which strategy is active or
// whether it's doing anything. Reports the configured strategy plus, only
// when a solver is actually wired, its REAL process-lived attempt/outcome
// counts — never a fabricated number. Engine-wide (not campaign-scoped),
// mirrors the Background connection sub-section just above.
const _CAPTCHA_STRATEGY_LABELS = {
  human: 'Hand off to you',
  avoid: 'Avoid automatically (stealth)',
  service: 'Solve automatically (paid service)',
};

async function _renderCaptcha(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/captcha-status`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const intro = `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">How the assistant handles a captcha it runs into while filling out an application.</div>`;
  const strategyLabel = _CAPTCHA_STRATEGY_LABELS[data.strategy] || data.strategy || 'Hand off to you';
  const rows = [
    ['Strategy', strategyLabel],
    ['Currently active', data.active ? 'Yes' : 'No (default hand-off)'],
  ];
  if (data.strategy === 'service') {
    rows.push(['Solving service', data.service || 'Not set']);
    rows.push(['Service key configured', data.key_configured ? 'Yes' : 'No']);
  }
  if (data.active && typeof data.attempts === 'number') {
    rows.push(['Captchas seen', data.attempts]);
    rows.push(['Solved', data.solved || 0]);
    rows.push(['Avoided', data.avoided || 0]);
    rows.push(['Handed off to you', data.handed_off || 0]);
  }
  host.innerHTML = intro + _statGrid(rows);
}

// Automation capacity — dark-engine audit #72: CapacityService admits/defers
// a sandbox slot for every application every tick (the browser-concurrency
// cap + pivot-around-blocker), but a deferred admission only ever logged
// "sandbox_admission_deferred" with nothing telling the owner how many
// applications are waiting for a slot right now. Engine-wide (not
// campaign-scoped), mirrors the Captcha handling sub-section just above.
async function _renderCapacity(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/capacity`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const intro = `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">How many applications currently hold a live browser, versus how many are waiting for one to free up.</div>`;
  if (!data.supported) {
    host.innerHTML = intro + _empty('Not available on the current automation backend.');
    return;
  }
  const rows = [
    ['Applications with a browser open', data.active_count || 0],
    ['Applications waiting for one', data.waiting_count || 0],
  ];
  host.innerHTML = intro + _statGrid(rows);
}

// Matching engine (embedding backend) — dark-engine audit #79: LocalEmbedding
// is a deterministic offline hashing-trick backend powering dedup, resume-
// variant scoring, and conversion-signature learning, but nothing disclosed
// that semantic-match quality is the basic offline fallback rather than a
// trained model. Engine-wide (not campaign-scoped), mirrors the Automation
// capacity sub-section just above.
async function _renderEmbedding(host) {
  host = host || _body();
  const data = await _fetchJSON(`${ADMIN}/embedding-backend`);
  if (data.engine_available === false) { _renderOffline(undefined, host); return; }
  const rows = [
    ['Matching engine', data.model_backed ? 'Model-backed' : 'Basic (offline)'],
    ['Quality', data.quality_tier || 'unknown'],
  ];
  const detail = data.detail ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:8px;">${esc(String(data.detail))}</div>` : '';
  host.innerHTML = _statGrid(rows) + detail;
}

async function _renderUpdate(host) {
  host = host || _body();
  let status = { engine_available: true };
  try { status = await _fetchJSON(`${OPS}/update`); } catch { status = { engine_available: false }; }
  if (status.engine_available === false) { _renderOffline(undefined, host); return; }
  host.innerHTML = `
    <div class="admin-card">
      <div style="font-weight:600;">Update Applicant</div>
      <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">
        Runs the safe one-click update: backs up your data, applies the latest version, and restarts.
        No command line needed. If updates aren't enabled on this install, it will tell you what it would do.
      </div>
      <button class="cal-btn cal-btn-primary" id="applicant-update-go" style="margin-top:12px;">Check for &amp; install update</button>
      <div id="applicant-update-result" class="admin-toggle-sub" style="margin-top:10px;"></div>
    </div>`;
  const updateBtn = host.querySelector('#applicant-update-go');
  if (updateBtn) updateBtn.addEventListener('click', async () => {
    const ok = await _confirm(
      'Update now? Your data is backed up first, then the latest version is applied and the app restarts.',
      { confirmText: 'Update now', cancelText: 'Cancel' });
    if (!ok) return;
    const out = host.querySelector('#applicant-update-result');
    updateBtn.disabled = true;
    if (out) out.textContent = 'Working…';
    try {
      const res = await _post(`${OPS}/update/trigger`, {});
      if (out) out.textContent = res.message || (res.started ? 'Update started.' : 'Nothing to do.');
    } catch (e) {
      if (out) out.textContent = e.message || 'Could not start the update right now.';
    } finally {
      updateBtn.disabled = false;
    }
  });
}

// #86: the Config pane hosts the former Sources/Tools/Update top-level tabs as
// independently-rendered sub-sections, each with its own host element so one
// section's error/offline/gated state can't blank out its siblings. Diagnostics
// (dark-engine audit #34) joins them the same way rather than adding a 7th
// top-level tab, keeping the tab strip within the 5-7 ceiling (#86). Detection
// events and Stealth posture (dark-engine audit #26/#27) join them the same
// way — both were already proxied but had no JS consumer at all.
async function _renderConfig() {
  const host = _body();
  host.innerHTML = `
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Sources</div>
      <div id="applicant-config-sources">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Detection events</div>
      <div id="applicant-config-detections">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Tools</div>
      <div id="applicant-config-tools">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Stealth posture</div>
      <div id="applicant-config-stealth">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Diagnostics</div>
      <div id="applicant-config-diagnostics">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;" title="Background agent health">Background connection</div>
      <div id="applicant-config-bridge">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Captcha handling</div>
      <div id="applicant-config-captcha">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Automation capacity</div>
      <div id="applicant-config-capacity">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list" style="margin-bottom:16px;">
      <div style="font-weight:600;margin-bottom:8px;">Matching engine</div>
      <div id="applicant-config-embedding">${loadingHTML('Loading…')}</div>
    </div>
    <div class="applicant-debug-list">
      <div style="font-weight:600;margin-bottom:8px;">Update</div>
      <div id="applicant-config-update">${loadingHTML('Loading…')}</div>
    </div>`;
  const sourcesHost = host.querySelector('#applicant-config-sources');
  const detectionsHost = host.querySelector('#applicant-config-detections');
  const toolsHost = host.querySelector('#applicant-config-tools');
  const stealthHost = host.querySelector('#applicant-config-stealth');
  const diagnosticsHost = host.querySelector('#applicant-config-diagnostics');
  const bridgeHost = host.querySelector('#applicant-config-bridge');
  const captchaHost = host.querySelector('#applicant-config-captcha');
  const capacityHost = host.querySelector('#applicant-config-capacity');
  const embeddingHost = host.querySelector('#applicant-config-embedding');
  const updateHost = host.querySelector('#applicant-config-update');
  const sections = [
    [sourcesHost, _renderSources],
    [detectionsHost, _renderDetections],
    [toolsHost, _renderTools],
    [stealthHost, _renderStealth],
    [diagnosticsHost, _renderDiagnostics],
    [bridgeHost, _renderBridge],
    [captchaHost, _renderCaptcha],
    [capacityHost, _renderCapacity],
    [embeddingHost, _renderEmbedding],
    [updateHost, _renderUpdate],
  ];
  for (const [sectionHost, renderFn] of sections) {
    try {
      await renderFn(sectionHost);
    } catch (e) {
      sectionHost.innerHTML = errorHTML(_errLine(e));
      wireRetry(sectionHost, () => renderFn(sectionHost));
    }
  }
}

// ── Open / launcher ─────────────────────────────────────────────────────────

// #87: the "Engine offline" note used to be a header-row badge (one more group
// crowding an already-packed row) — it now lives as a banner just above the
// tab strip, in the body area, separate from the header's leading/trailing
// controls.
function _setEngineBanner(modal, up) {
  const banner = modal.querySelector('#applicant-debug-engine-banner');
  if (!banner) return;
  if (up) {
    banner.style.display = 'none';
    banner.textContent = '';
  } else {
    banner.textContent = 'Engine offline — this view will fill in once it is connected.';
    banner.style.display = 'block';
  }
}

// Keyboard a11y: trap focus inside the modal, move focus in, Escape closes
// the overflow popover first (if open) or the modal next, and focus is
// restored to whatever launched Debug when it closes. Called fresh from
// EVERY open (openApplicantDebug / openApplicantDebugDetail) rather than
// once at first creation — design audit #1 names this modal as one of six
// that used to lose all focus management on every open after the first,
// because the old wiring lived behind `_ensureModalEl`'s "already built"
// early-return guard.
function _wireA11y(modal) {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  const overflowMenu = modal.querySelector('#applicant-debug-overflow-menu');
  const overflowBtn = modal.querySelector('#applicant-debug-overflow-btn');
  const closeOverflow = () => {
    if (!overflowMenu) return;
    overflowMenu.classList.add('hidden');
    if (overflowBtn) overflowBtn.setAttribute('aria-expanded', 'false');
  };
  _modalA11yCleanup = uiModule.initModalA11y(modal, () => {
    if (overflowMenu && !overflowMenu.classList.contains('hidden')) { closeOverflow(); return; }
    _close();
  });
}

// Visually-hidden aria-live status line (design audit #11/#12 — Debug is one
// of the many applicant surfaces with zero live regions, so its own tab-body
// load/error/result transitions are otherwise inaudible). Kept separate from
// the tabpanel itself so a full content swap isn't read in its entirety on
// every tab switch — just a short plain-language status line.
function _announce(msg) {
  const live = _modalEl && _modalEl.querySelector('#applicant-debug-live');
  if (live) live.textContent = msg;
}

export async function openApplicantDebug(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _wireA11y(modal);
  if (!(opts && opts.skipHashUpdate)) setHash('debug');
  _body().innerHTML = loadingHTML('Loading…');
  try {
    const up = await _loadCampaigns();
    _setEngineBanner(modal, up);
    await _renderTab();
  } catch (err) {
    _body().innerHTML = errorHTML(_errLine(err));
    wireRetry(_body(), openApplicantDebug);
  }
}

// #98: lets another surface (Compare) deep-link a specific application into the
// Debug/Activity detail drill-in instead of dead-ending on a bare id. Opens the
// modal, selects the given campaign (when known) and jumps straight to that
// application's detail card on the Activity tab.
export async function openApplicantDebugDetail(campaignId, appId) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _wireA11y(modal);
  _body().innerHTML = loadingHTML('Loading…');
  try {
    const up = await _loadCampaigns();
    _setEngineBanner(modal, up);
    if (campaignId) {
      _campaignId = campaignId;
      const sel = modal.querySelector('#applicant-debug-campaign');
      if (sel) sel.value = campaignId;
    }
    _activeTab = 'activity';
    _syncTabActiveUI('activity');
    await _renderTab();
    if (appId) await _showAppDetail(appId);
  } catch (err) {
    _body().innerHTML = errorHTML(_errLine(err));
    wireRetry(_body(), () => openApplicantDebugDetail(campaignId, appId));
  }
}

function _wireLauncher() {
  const btn = document.getElementById('tool-debug-btn');
  if (!btn || btn._applicantDebugWired) return;
  btn._applicantDebugWired = true;
  btn.addEventListener('click', () => {
    // Respect the feature-activation lock — if app.js greyed the launcher, its
    // capture-phase guard already stopped this handler; reaching here = active.
    openApplicantDebug();
  });
}

function _boot() {
  _wireLauncher();
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('tool-debug-btn')?._applicantDebugWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#debug' deep-links straight into the Activity /
// Debug page — a refresh/shared-link/back-forward on that hash opens/closes
// it. Registered at module-eval time (runs as soon as app.js's dynamic
// import resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('debug', { open: openApplicantDebug, close: _close });

const applicantDebugModule = { openApplicantDebug, closeApplicantDebug, openApplicantDebugDetail };
try { window.applicantDebugModule = applicantDebugModule; } catch { /* no-op */ }

// Exported so the submission-record drill-in renderer (#372) is unit-renderable.
export { _renderSnapshot };
export default applicantDebugModule;
