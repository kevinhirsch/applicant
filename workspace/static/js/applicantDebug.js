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
//   • Run        — run mode + daily target controls and the latest plain-language
//                  "what the agent is doing right now" intent (writes config).
//   • Sources    — turn each job-discovery source on/off + see its yield.
//   • Tools      — enable/disable the engine's tools (engine-wide; writes).
//   • Update     — a one-click Update button with confirm + status.
//
// Activation: the launcher (tool-debug-btn) is greyed + click-guarded by the
// feature-activation layer in app.js until the engine reports it's configured
// (the `debug` section). We still render a graceful offline state if opened while
// the engine is unreachable or the caller isn't an admin.

import uiModule from './ui.js';

const ADMIN = '/api/applicant/admin';
const OPS = '/api/applicant/ops';

let _modalEl = null;
let _activeTab = 'activity';
let _campaignId = null;

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

function _put(url, body) {
  return _fetchJSON(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ── Modal scaffold ──────────────────────────────────────────────────────────

const TABS = [
  ['activity', 'Activity'],
  ['insights', 'Insights'],
  ['logs', 'Logs'],
  ['variants', 'Variants'],
  ['run', 'Run controls'],
  ['sources', 'Sources'],
  ['tools', 'Tools'],
  ['update', 'Update'],
];

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-debug-modal';
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content" style="max-width:860px;width:97%;display:flex;flex-direction:column;max-height:88vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          Activity
        </h4>
        <button class="close-btn" id="applicant-debug-close" title="Close">✖</button>
      </div>
      <div style="padding:8px 14px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <label class="admin-toggle-sub" style="margin:0;display:flex;gap:6px;align-items:center;">
          Job search
          <select id="applicant-debug-campaign" class="settings-select" style="min-width:180px;"></select>
        </label>
        <span id="applicant-debug-engine" class="admin-toggle-sub" style="margin:0;opacity:0.6;"></span>
        <button class="cal-btn" id="applicant-debug-chat" title="Open the assistant beside this so you can ask about what the agent is doing" style="margin-left:auto;">Ask the assistant</button>
      </div>
      <div class="admin-tabs" id="applicant-debug-tabs" style="padding:8px 14px 0;">
        ${TABS.map(([k, label], i) => `<button class="admin-tab${i === 0 ? ' active' : ''}" data-tab="${k}">${esc(label)}</button>`).join('')}
      </div>
      <div class="modal-body" id="applicant-debug-body" style="flex:1;overflow-y:auto;padding:14px;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector('#applicant-debug-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  modal.querySelectorAll('#applicant-debug-tabs .admin-tab').forEach((b) => {
    b.addEventListener('click', () => {
      modal.querySelectorAll('#applicant-debug-tabs .admin-tab').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      _activeTab = b.dataset.tab;
      _renderTab();
    });
  });
  modal.querySelector('#applicant-debug-campaign').addEventListener('change', (e) => {
    _campaignId = e.target.value || null;
    _renderTab();
  });
  // Dual view: open the Job Assistant beside this window (both are scrim-less,
  // draggable tool windows, so they sit side by side) — watch the agent on one
  // side, ask it questions on the other.
  const chatBtn = modal.querySelector('#applicant-debug-chat');
  if (chatBtn) chatBtn.addEventListener('click', () => {
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
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = 'none';
  }
}

function _body() { return _modalEl.querySelector('#applicant-debug-body'); }

function _renderOffline(msg) {
  _body().innerHTML = `<div class="admin-card" style="opacity:0.85;">${esc(msg || 'The Applicant engine is not reachable right now. This view will fill in once it is connected.')}</div>`;
}

function _empty(msg) {
  return `<div class="admin-toggle-sub" style="opacity:0.6;padding:8px 0;">${esc(msg)}</div>`;
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
  const campaigns = (data && data.campaigns) || [];
  sel.innerHTML = campaigns.length
    ? campaigns.map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.id)}</option>`).join('')
    : '<option value="">No job searches yet</option>';
  if (!_campaignId && campaigns.length) _campaignId = campaigns[0].id;
  if (_campaignId) sel.value = _campaignId;
  return data && data.engine_available !== false;
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

async function _renderTab() {
  const map = {
    activity: _renderActivity,
    insights: _renderInsights,
    logs: _renderLogs,
    variants: _renderVariants,
    run: _renderRun,
    sources: _renderSources,
    tools: _renderTools,
    update: _renderUpdate,
  };
  _body().innerHTML = '<div class="hwfit-loading">Loading…</div>';
  try {
    await (map[_activeTab] || _renderActivity)();
  } catch (e) {
    if (e && e.status === 403) {
      _renderOffline('This view is available to admins only.');
    } else {
      _renderOffline();
    }
  }
}

function _needCampaign() {
  if (!_campaignId) {
    _body().innerHTML = _empty('Pick a job search above to see its activity.');
    return false;
  }
  return true;
}

async function _renderActivity() {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${ADMIN}/history/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const apps = data.applications || [];
  if (!apps.length) { _body().innerHTML = _empty('No applications recorded for this job search yet.'); return; }
  const rows = apps.map((a) => {
    const id = a.application_id || a.id || '';
    const title = a.role_name || a.job_title || id || 'Application';
    const shots = a.screenshot_count != null ? a.screenshot_count : (a.screenshots || []).length;
    return `<div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(title)}</div>
        <div class="admin-toggle-sub" style="margin:2px 0 0;opacity:0.7;">
          ${esc(a.status || 'unknown')} · ${esc(a.work_mode || '—')} · ${esc(shots)} screenshots${(a.outcomes || []).length ? ` · ${esc((a.outcomes || []).map((o) => o.type).join(', '))}` : ''}
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-shrink:0;">
        <button class="admin-btn-sm applicant-debug-detail" data-app="${esc(id)}">Details</button>
        <button class="admin-btn-sm applicant-debug-marksub" data-app="${esc(id)}" title="Record that you completed/submitted this yourself so it teaches the system">I submitted this</button>
      </div>
    </div>`;
  }).join('');
  _body().innerHTML = `<div id="applicant-debug-detail-host"></div>${rows}`;
  _body().querySelectorAll('.applicant-debug-detail').forEach((b) => {
    b.addEventListener('click', () => _showAppDetail(b.dataset.app));
  });
  _body().querySelectorAll('.applicant-debug-marksub').forEach((b) => {
    b.addEventListener('click', () => _markSubmitted(b.dataset.app));
  });
}

async function _showAppDetail(appId) {
  const host = _body().querySelector('#applicant-debug-detail-host');
  if (!host || !appId) return;
  host.innerHTML = '<div class="hwfit-loading">Loading details…</div>';
  let shots = { screenshots: [] }, wf = { steps: [] }, outcomes = { outcomes: [] };
  try { shots = await _fetchJSON(`${ADMIN}/screenshots/${encodeURIComponent(appId)}`); } catch { /* soft */ }
  try { wf = await _fetchJSON(`${ADMIN}/workflow/${encodeURIComponent(appId)}`); } catch { /* soft */ }
  try { outcomes = await _fetchJSON(`${ADMIN}/outcomes/${encodeURIComponent(appId)}`); } catch { /* soft */ }
  const shotList = (shots.screenshots || []);
  const steps = (wf.completed_steps || wf.steps || []);
  const evs = (outcomes.outcomes || []);
  host.innerHTML = `<div class="admin-card" style="border:1px solid var(--border,#3334);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <strong>Application ${esc(appId)}</strong>
      <button class="admin-btn-sm" id="applicant-debug-detail-close">Close</button>
    </div>
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Screenshots</strong> (${shotList.length})</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">
      ${shotList.length ? shotList.map((s) => `<span class="admin-toggle-sub" style="opacity:0.7;" title="${esc(s.page_url || '')}">${esc(s.page_ref || s.page || s.label || 'page')}</span>`).join(' · ') : _empty('No screenshots captured.')}
    </div>
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Workflow steps</strong></div>
    ${steps.length ? `<div class="admin-toggle-sub" style="opacity:0.7;">${steps.map((s) => esc(typeof s === 'string' ? s : (s.name || s.step || JSON.stringify(s)))).join(' → ')}</div>${wf.pending_recovery ? '<div class="admin-toggle-sub" style="color:var(--warn,#c80);">Pending recovery</div>' : ''}` : _empty('No durable workflow recorded.')}
    <div class="admin-toggle-sub" style="margin-top:8px;"><strong>Outcomes</strong></div>
    ${evs.length ? `<div class="admin-toggle-sub" style="opacity:0.7;">${evs.map((e) => `${esc(e.type)} (${esc(e.source)})`).join(', ')}</div>` : _empty('No outcomes recorded yet.')}
  </div>`;
  host.querySelector('#applicant-debug-detail-close').addEventListener('click', () => { host.innerHTML = ''; });
}

async function _markSubmitted(appId) {
  if (!appId) return;
  if (!window.confirm('Record that you submitted this application yourself? This helps the system learn which details convert.')) return;
  try {
    await _post(`${ADMIN}/applications/${encodeURIComponent(appId)}/mark-submitted`, {});
    _toast('Recorded — thanks, this helps the system learn.');
    _renderActivity();
  } catch (e) {
    _toast(e.message || 'Could not record that right now.');
  }
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
    <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">
      ${esc(num(s.total_matched))} matched · ${esc(num(s.total_approved))} approved · ${esc(num(s.total_submitted))} submitted
      across ${esc(num(s.sources_seen))} source${num(s.sources_seen) === 1 ? '' : 's'}.
    </div>
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
          ${esc(Number(data.exploration_budget))} — share of effort spent trying new or under-used sources instead of the proven ones.
        </div>
        <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:6px;">Change this on the Sources tab.</span>
      </div>`
    : '';

  let sourcesCard;
  if (!sources.length) {
    sourcesCard = `<div class="admin-card"><div style="font-weight:600;">Best sources</div>${_empty('No source results recorded for this job search yet.')}</div>`;
  } else {
    const rows = sources.map((src) => {
      const rate = src.conversion_rate != null ? `${esc(src.conversion_rate)}% convert` : 'no rate yet';
      return `<div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
        <div style="min-width:0;">
          <div style="font-weight:600;">${esc(src.source)}</div>
          <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">
            ${esc(num(src.matched))} matched · ${esc(num(src.approved))} approved · ${esc(num(src.submitted))} submitted
          </div>
        </div>
        <div class="admin-toggle-sub" style="opacity:0.75;flex-shrink:0;">${esc(rate)}</div>
      </div>`;
    }).join('');
    sourcesCard = `<div class="admin-toggle-sub" style="opacity:0.7;margin:10px 0 6px;">Best sources (ranked by how well they convert)</div>${rows}`;
  }

  _body().innerHTML = summaryCard + rolesCard + budgetCard + sourcesCard;
}

async function _renderLogs() {
  const data = await _fetchJSON(`${ADMIN}/logs?limit=100`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const entries = data.entries || [];
  if (!entries.length) { _body().innerHTML = _empty('No recent activity logs.'); return; }
  _body().innerHTML = `<pre style="white-space:pre-wrap;font-size:12px;line-height:1.45;margin:0;">${entries.map((e) => esc(typeof e === 'string' ? e : JSON.stringify(e))).join('\n')}</pre>`;
}

async function _renderVariants() {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${ADMIN}/variants/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const variants = data.variants || [];
  if (!variants.length) { _body().innerHTML = _empty('No resume variants built for this job search yet.'); return; }
  _body().innerHTML = variants.map((v) => {
    const id = v.variant_id || v.id || 'Variant';
    const scores = v.fit_scores || {};
    const scoreVals = Object.values(scores);
    const scoreText = scoreVals.length
      ? `best fit ${esc(Math.max(...scoreVals.map(Number)).toFixed(2))}`
      : (v.score != null ? `score ${esc(v.score)}` : 'not scored');
    const approved = v.approved === true ? 'approved' : (v.approval_state || 'awaiting review');
    return `<div class="admin-card">
    <div style="font-weight:600;">${esc(v.is_root ? 'Base resume' : id)}</div>
    <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">
      ${esc(scoreText)} · ${esc(approved)}${v.lineage_depth ? ` · ${esc(v.lineage_depth)} edits deep` : ''}${v.parent_id ? ` · from ${esc(v.parent_id)}` : ''}
    </div>
  </div>`;
  }).join('');
}

const RUN_MODES = [
  ['continuous', 'Around the clock'],
  ['fixed_duration', 'Fixed window'],
  ['until_n_viable', 'Until target reached'],
];

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
function _statusChip(status) {
  const sched = status.scheduler || {};
  let label;
  let color;
  let pulse = false;
  if (status.paused === true || status.active === false) {
    label = 'Paused'; color = '#d29922';
  } else if (sched.running === true) {
    label = 'Working now'; color = '#3fb950'; pulse = true;
  } else {
    label = 'Idle'; color = '#8b949e';
  }
  const dot = `<span aria-hidden="true" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${color};margin-right:7px;${pulse ? 'box-shadow:0 0 0 0 ' + color + ';animation:applicantPulse 1.4s infinite;' : ''}"></span>`;
  const bits = [];
  if (sched.last_tick) bits.push(`last run ${esc(_relWhen(sched.last_tick))}`);
  if (sched.next_tick && status.paused !== true) bits.push(`next ${esc(_relWhen(sched.next_tick))}`);
  if (status.applied_today != null) {
    const cap = status.daily_budget != null ? status.daily_budget : status.throughput_target;
    bits.push(`${esc(status.applied_today)}${cap != null ? ` / ${esc(cap)}` : ''} today`);
  }
  return `
    <div class="admin-card" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
      <div style="display:flex;align-items:center;font-weight:600;">${dot}${esc(label)}</div>
      <div class="admin-toggle-sub" style="opacity:0.75;">${bits.join(' · ')}</div>
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
  if (intent.engine_available === false && runs.engine_available === false && status.engine_available === false) {
    _renderOffline(); return;
  }
  const last = (runs.items || [])[0] || {};
  // Prefer the live status payload for the config defaults; fall back to the latest run.
  const curMode = status.run_mode || last.run_mode;
  const curTarget = status.throughput_target != null ? status.throughput_target : last.throughput_target;
  const intentText = intent.intent || status.latest_intent;
  const paused = status.paused === true || status.active === false;
  const haveStatus = status.engine_available !== false && status.campaign_id;
  _body().innerHTML = `
    ${haveStatus ? _statusChip(status) : ''}
    <div class="admin-card">
      <div style="font-weight:600;">What the agent is doing</div>
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
        <select id="applicant-run-mode" class="settings-select" style="display:block;margin-top:4px;min-width:220px;">
          ${RUN_MODES.map(([k, label]) => `<option value="${k}"${(curMode === k) ? ' selected' : ''}>${esc(label)}</option>`).join('')}
        </select>
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:8px;">Applications per day (target)
        <input type="number" id="applicant-run-target" class="settings-select" min="0" value="${esc(curTarget != null ? curTarget : '')}" style="display:block;margin-top:4px;width:120px;" />
      </label>
      <span class="admin-toggle-sub" style="opacity:0.6;display:block;">Targets above the safe daily cap are clamped automatically.</span>
      <button class="cal-btn cal-btn-primary" id="applicant-run-save" style="margin-top:10px;">Save run settings</button>
    </div>`;
  _body().querySelector('#applicant-run-save').addEventListener('click', async () => {
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
        _toast(res.reason || 'Nothing to run right now.');
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

async function _renderSources() {
  if (!_needCampaign()) return;
  const data = await _fetchJSON(`${OPS}/discovery/${encodeURIComponent(_campaignId)}`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const items = data.items || [];
  // Exploration budget (FR-LEARN-6): the explore/exploit knob. Shown above the
  // source list. Editable when the engine reports it; read-only note otherwise.
  const hasBudget = data.exploration_budget != null && !isNaN(Number(data.exploration_budget));
  const budgetCard = hasBudget
    ? `<div class="admin-card" style="margin-bottom:10px;">
        <div style="font-weight:600;">Exploration budget</div>
        <div class="admin-toggle-sub" style="opacity:0.7;margin:2px 0 8px;">How much effort to spend trying new or under-used sources instead of the proven ones. 0 sticks to what works; 1 explores the most.</div>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="number" id="applicant-explore-budget" class="settings-input" min="0" max="1" step="0.05" value="${esc(Number(data.exploration_budget))}" style="width:90px;" title="A number between 0 and 1." />
          <button class="cal-btn" id="applicant-explore-save" title="Save the exploration budget">Save</button>
          <span id="applicant-explore-msg" class="admin-toggle-sub" style="opacity:0.7;"></span>
        </div>
      </div>`
    : '';
  if (!items.length) {
    _body().innerHTML = budgetCard + _empty('No job-discovery sources available for this job search.');
    _wireExploreBudget();
    return;
  }
  _body().innerHTML = budgetCard + items.map((s) => {
    const ys = s.yield_stats || {};
    const hasFunnel = ys.matches != null || ys.approvals != null || ys.submissions != null;
    const stat = hasFunnel
      ? `${ys.matches != null ? ys.matches : 0} matched · ${ys.approvals != null ? ys.approvals : 0} approved · ${ys.submissions != null ? ys.submissions : 0} submitted`
      : 'no yield data yet';
    return `<div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(s.source_key)}</div>
        <div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">${esc(stat)}</div>
      </div>
      <label class="admin-switch" style="flex-shrink:0;" title="Turn this source on or off">
        <input type="checkbox" class="applicant-source-toggle" data-key="${esc(s.source_key)}"${s.enabled ? ' checked' : ''} />
        <span class="admin-slider"></span>
      </label>
    </div>`;
  }).join('');
  _body().querySelectorAll('.applicant-source-toggle').forEach((cb) => {
    cb.addEventListener('change', async () => {
      try {
        await _put(`${OPS}/discovery/${encodeURIComponent(_campaignId)}/${encodeURIComponent(cb.dataset.key)}`, { enabled: cb.checked });
        _toast(`${cb.dataset.key} ${cb.checked ? 'on' : 'off'}.`);
      } catch (e) {
        cb.checked = !cb.checked; // revert on failure
        _toast(e.message || 'Could not change that source.');
      }
    });
  });
  _wireExploreBudget();
}

function _wireExploreBudget() {
  const input = _body().querySelector('#applicant-explore-budget');
  const btn = _body().querySelector('#applicant-explore-save');
  const msg = _body().querySelector('#applicant-explore-msg');
  if (!input || !btn) return; // read-only / not exposed by the engine
  btn.addEventListener('click', async () => {
    const val = parseFloat(input.value);
    if (isNaN(val) || val < 0 || val > 1) {
      if (msg) msg.textContent = 'Enter a number between 0 and 1.';
      return;
    }
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

async function _renderTools() {
  // Engine-wide tool registry (not campaign-scoped): list every tool with an
  // on/off switch. Mirrors the Sources tab's switch rendering.
  const data = await _fetchJSON(`${ADMIN}/tools`);
  if (data.engine_available === false) { _renderOffline(); return; }
  const tools = data.tools || [];
  if (!tools.length) { _body().innerHTML = _empty('No tools reported by the engine.'); return; }
  _body().innerHTML =
    `<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:8px;">Turn the assistant's tools on or off. Disabled tools are never used while it works.</div>` +
    tools.map((t) => {
      const key = t.key != null ? t.key : '';
      const label = t.label || key;
      return `<div class="admin-card" style="display:flex;justify-content:space-between;align-items:center;gap:10px;">
      <div style="min-width:0;">
        <div style="font-weight:600;">${esc(label)}</div>
        ${t.description ? `<div class="admin-toggle-sub" style="opacity:0.7;margin-top:2px;">${esc(t.description)}</div>` : ''}
      </div>
      <label class="admin-switch" style="flex-shrink:0;" title="Turn this tool on or off">
        <input type="checkbox" class="applicant-tool-toggle" data-key="${esc(key)}"${t.enabled ? ' checked' : ''} />
        <span class="admin-slider"></span>
      </label>
    </div>`;
    }).join('');
  _body().querySelectorAll('.applicant-tool-toggle').forEach((cb) => {
    cb.addEventListener('change', async () => {
      try {
        await _post(`${ADMIN}/tools/${encodeURIComponent(cb.dataset.key)}`, { enabled: cb.checked });
        _toast(`${cb.dataset.key} ${cb.checked ? 'on' : 'off'}.`);
      } catch (e) {
        cb.checked = !cb.checked; // revert on failure
        _toast(e.message || 'Could not change that tool.');
      }
    });
  });
}

async function _renderUpdate() {
  let status = { engine_available: true };
  try { status = await _fetchJSON(`${OPS}/update`); } catch { status = { engine_available: false }; }
  if (status.engine_available === false) { _renderOffline(); return; }
  _body().innerHTML = `
    <div class="admin-card">
      <div style="font-weight:600;">Update Applicant</div>
      <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">
        Runs the safe one-click update: backs up your data, applies the latest version, and restarts.
        No command line needed. If updates aren't enabled on this install, it will tell you what it would do.
      </div>
      <button class="cal-btn cal-btn-primary" id="applicant-update-go" style="margin-top:12px;">Check for &amp; install update</button>
      <div id="applicant-update-result" class="admin-toggle-sub" style="margin-top:10px;"></div>
    </div>`;
  _body().querySelector('#applicant-update-go').addEventListener('click', async () => {
    if (!window.confirm('Update now? Your data is backed up first, then the latest version is applied and the app restarts.')) return;
    const out = _body().querySelector('#applicant-update-result');
    out.textContent = 'Working…';
    try {
      const res = await _post(`${OPS}/update/trigger`, {});
      out.textContent = res.message || (res.started ? 'Update started.' : 'Nothing to do.');
    } catch (e) {
      out.textContent = e.message || 'Could not start the update right now.';
    }
  });
}

// ── Open / launcher ─────────────────────────────────────────────────────────

export async function openApplicantDebug() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _body().innerHTML = '<div class="hwfit-loading">Loading…</div>';
  try {
    const up = await _loadCampaigns();
    const badge = modal.querySelector('#applicant-debug-engine');
    if (badge) badge.textContent = up ? '' : 'Engine offline';
    await _renderTab();
  } catch {
    _renderOffline();
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

const applicantDebugModule = { openApplicantDebug };
try { window.applicantDebugModule = applicantDebugModule; } catch { /* no-op */ }

export default applicantDebugModule;
