// static/js/applicantActivity.js
//
// Agent-activity feed — surfaces the engine's EXISTING plain-language account of
// what the job agent is doing, in two front-door surfaces:
//
//   1. An always-visible STATUS STRIP in the app chrome (the chat top bar):
//      a compact "Applicant is: <current action>" pill with a live/paused dot.
//      Polls /api/applicant/activity/status on a slow interval; clicking it opens
//      the Activity page. It hides itself gracefully when there is no campaign,
//      the engine is unreachable, or there is no activity yet.
//
//   2. A dedicated ACTIVITY PAGE (a top-level rail entry → modal) showing the
//      chronological run history: each row is the engine's own "verb-noun" intent
//      sentence plus a friendly one-line stat summary derived from its stats block
//      and a relative timestamp.
//
// This is ADDITIVE, self-contained, and surfacing-only. It talks to the engine
// only through the workspace proxy at /api/applicant/activity/* (it never reaches
// the engine directly), creates no engine state, and degrades gracefully when the
// engine is offline. Styling reuses the workspace design system (.modal /
// .modal-content / .modal-header / .modal-body / .cal-btn / .close-btn /
// .hwfit-loading / .applicant-status-strip).

import uiModule from './ui.js';
import { esc, _fetchJSON } from './applicantCore.js';

const API = '/api/applicant/activity';
// Slow poll for the always-visible strip — mirrors the Portal's BADGE_POLL_MS.
const STATUS_POLL_MS = 45000;

let _modalEl = null;
let _modalA11yCleanup = null;
let _statusPollIv = null;
let _runsLoading = false;



// Compact relative time ("just now", "5m ago", "3h ago", "2d ago"). Accepts an
// ISO string, an epoch-seconds number, or an epoch-ms number. Returns '' when the
// input is missing/unparseable so the caller can omit it cleanly.
function _relTime(value) {
  if (value == null || value === '') return '';
  let ms = null;
  if (typeof value === 'number') {
    ms = value < 1e12 ? value * 1000 : value; // seconds vs ms heuristic
  } else {
    const t = Date.parse(value);
    if (!Number.isNaN(t)) ms = t;
  }
  if (ms == null) return '';
  const diff = Date.now() - ms;
  if (!Number.isFinite(diff)) return '';
  const s = Math.round(diff / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  try { return new Date(ms).toLocaleDateString(); } catch { return ''; }
}

// ── Status strip (always-visible chrome) ────────────────────────────────────

function _stripEl() { return document.getElementById('applicant-status-strip'); }
function _stripTextEl() { return document.getElementById('applicant-status-text'); }
function _railEl() { return document.getElementById('rail-activity'); }

// The rail nav entry and the strip share one visibility signal: both appear only
// when the engine reports there IS activity. This keeps the nav from showing a
// dead "Activity" entry before the assistant has done anything.
function _setActivityVisible(visible) {
  const rail = _railEl();
  if (rail) rail.style.display = visible ? '' : 'none';
}

function _hideStrip() {
  const strip = _stripEl();
  if (strip) strip.style.display = 'none';
  _setActivityVisible(false);
}

// Pick the best plain-language sentence the engine gives us for the strip. The
// status payload carries `latest_intent`; fall back to a generic running/paused
// label so the strip still reads sensibly if the sentence is absent.
function _statusSentence(data) {
  const intent = data && (data.latest_intent || data.intent);
  if (intent && String(intent).trim()) return String(intent).trim();
  const running = _isRunning(data);
  return running ? 'Working on your job search' : 'Paused';
}

function _isRunning(data) {
  const sched = (data && data.scheduler) || {};
  // `scheduler.running` is the authoritative live/paused signal; `active` is the
  // campaign's own run flag. Treat the agent as live only when both agree it is.
  if (typeof sched.running === 'boolean') {
    return sched.running && (data.active !== false);
  }
  return Boolean(data && data.active);
}

function _renderStrip(data) {
  const strip = _stripEl();
  const text = _stripTextEl();
  if (!strip || !text) return;
  // Hide gracefully when there's nothing to show.
  if (!data || data.engine_available === false || data.has_activity === false) {
    _hideStrip();
    return;
  }
  const running = _isRunning(data);
  strip.classList.toggle('is-live', running);
  strip.classList.toggle('is-paused', !running);
  const sentence = _statusSentence(data);
  text.textContent = running ? `Applicant is: ${sentence}` : sentence;
  strip.title = `${text.textContent} — open Activity`;
  strip.style.display = 'inline-flex';
  // There's activity → reveal the Activity nav entry too.
  _setActivityVisible(true);
}

async function refreshStatus() {
  try {
    const data = await _fetchJSON(`${API}/status`);
    _renderStrip(data);
  } catch {
    // Proxy/engine error — hide rather than show a broken strip.
    _hideStrip();
  }
}

// ── Activity page (run history modal) ────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-activity-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Activity');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:640px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Activity
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-activity-refresh" title="Refresh the activity feed">Refresh</button>
          <button class="close-btn" id="applicant-activity-close" title="Close">✖</button>
        </div>
      </div>
      <div id="applicant-activity-snapshot" style="flex:0 0 auto;"></div>
      <div class="modal-body" id="applicant-activity-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') _close(); });
  modal.querySelector('#applicant-activity-close').addEventListener('click', _close);
  modal.querySelector('#applicant-activity-refresh').addEventListener('click', () => { _loadSnapshot(); _loadRuns(true); });
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-activity-body'); }
function _snapshotHost() { return _modalEl && _modalEl.querySelector('#applicant-activity-snapshot'); }

// ── "Now / Next" snapshot panel (the live status header) ─────────────────────
//
// Renders the engine's consolidated, first-person snapshot ("Right now I'm…",
// "Next I'll…") at the top of the Activity modal. Every field is optional — the
// engine omits anything it can't truthfully report, so each line renders only
// when present (no fabricated activity).

function _snapshotLine(label, sentence, extra) {
  const tail = extra ? `<span style="opacity:0.6;font-weight:400;"> ${esc(extra)}</span>` : '';
  return `
    <div style="margin:2px 0;font-size:12px;line-height:1.4;">
      <span style="opacity:0.55;text-transform:uppercase;font-size:9.5px;letter-spacing:0.04em;">${esc(label)}</span>
      <div style="font-weight:500;">${esc(sentence)}${tail}</div>
    </div>`;
}

function _renderSnapshot(host, data) {
  if (!host) return;
  if (!data || data.engine_available === false || data.has_activity === false) {
    host.innerHTML = '';
    return;
  }
  const now = (data && data.now) || {};
  const next = (data && data.next) || {};
  const live = Boolean(now.running);
  const dot = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px;background:${live ? 'var(--accent, #3a8)' : '#999'};"></span>`;
  const parts = [];
  if (now.sentence) {
    parts.push(_snapshotLine('Now', now.sentence));
  }
  if (next.sentence) {
    let extra = '';
    const pending = Number(next.pending_actions);
    if (Number.isFinite(pending) && pending > 0) {
      extra = `${pending} item${pending === 1 ? '' : 's'} waiting on you`;
    }
    parts.push(_snapshotLine('Up next', next.sentence, extra));
  }
  if (!parts.length) { host.innerHTML = ''; return; }
  host.innerHTML = `
    <div class="admin-card" style="margin:0 0 8px;padding:10px 12px;">
      <div style="font-size:11px;font-weight:600;opacity:0.8;margin-bottom:4px;">${dot}Agent status</div>
      ${parts.join('')}
    </div>`;
}

async function _loadSnapshot() {
  const host = _snapshotHost();
  if (!host) return;
  try {
    const data = await _fetchJSON(`${API}/snapshot`);
    _renderSnapshot(host, data);
  } catch {
    host.innerHTML = ''; // hide silently rather than show a broken panel
  }
}

function _renderOffline(host) {
  host.innerHTML = `
    <div style="padding:18px 8px;text-align:center;font-size:12px;opacity:0.75;">
      Your assistant's activity will appear here once it's connected and running.
    </div>`;
}

function _renderEmpty(host) {
  host.innerHTML = `
    <div style="padding:18px 8px;text-align:center;font-size:12px;opacity:0.75;">
      No activity yet. Once your assistant starts working on your job search, what it
      does will show up here.
    </div>`;
}

// Friendly one-line summary from a run's stats block, e.g.
// "Discovered 5 · pre-filling 3 · completed 1". Each part is included only when
// it carries a number, so a sparse run reads cleanly. Returns '' when empty.
function _statSummary(stats) {
  if (!stats || typeof stats !== 'object') return '';
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
  let line = parts.join(' · ');
  const budget = Number(stats.budget_remaining);
  if (Number.isFinite(budget) && budget >= 0) {
    line += `${line ? ' · ' : ''}${budget} left in today's budget`;
  }
  return line;
}

function _runTime(run) {
  return run.created_at || run.finished_at || run.started_at || run.last_run_at || run.timestamp || run.ts || '';
}

function _renderRuns(host, items) {
  if (!items.length) { _renderEmpty(host); return; }
  const rows = items.map((run) => {
    const intent = run.intent || run.summary || 'Worked on your job search';
    const summary = _statSummary(run.stats);
    const when = _relTime(_runTime(run));
    const meta = [summary, when].filter(Boolean).join(' · ');
    return `
      <div class="memory-item" style="display:block;padding:9px 10px;border-bottom:1px solid var(--border);">
        <div style="font-size:12px;font-weight:500;line-height:1.35;">${esc(intent)}</div>
        ${meta ? `<div class="memory-item-meta" style="font-size:10.5px;opacity:0.6;margin-top:3px;">${esc(meta)}</div>` : ''}
      </div>`;
  });
  const heading = `
    <div style="padding:4px 10px 6px;font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">
      Recently I…
    </div>`;
  host.innerHTML = `<div>${heading}${rows.join('')}</div>`;
}

async function _loadRuns(showSpinner) {
  if (_runsLoading) return;
  _runsLoading = true;
  const host = _body();
  if (host && showSpinner) host.innerHTML = '<div class="hwfit-loading">Loading…</div>';
  try {
    const data = await _fetchJSON(`${API}/runs`);
    if (!host) return;
    if (data && data.engine_available === false) { _renderOffline(host); return; }
    const items = (data && data.items) || [];
    _renderRuns(host, items);
  } catch {
    if (host) _renderOffline(host);
  } finally {
    _runsLoading = false;
  }
}

export async function openApplicantActivity() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  // The live "now / next" header and the "recently" history load together.
  _loadSnapshot();
  await _loadRuns(true);
  // Opening the page is a natural moment to refresh the strip too.
  refreshStatus();
}

// ── Launcher + boot ────────────────────────────────────────────────────────────

function _wireLaunchers() {
  const rail = document.getElementById('rail-activity');
  if (rail && !rail._applicantActivityWired) {
    rail._applicantActivityWired = true;
    rail.addEventListener('click', () => openApplicantActivity());
  }
  const strip = _stripEl();
  if (strip && !strip._applicantActivityWired) {
    strip._applicantActivityWired = true;
    strip.addEventListener('click', () => openApplicantActivity());
  }
}

function _boot() {
  _wireLaunchers();
  // The rail/strip may be (re)rendered after boot; retry briefly so the launchers
  // always get wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLaunchers();
    const railWired = document.getElementById('rail-activity')?._applicantActivityWired;
    const stripWired = _stripEl()?._applicantActivityWired;
    if ((railWired && stripWired) || tries > 20) clearInterval(iv);
  }, 500);
  // Seed the strip, then keep it fresh on a slow poll.
  refreshStatus();
  if (_statusPollIv) clearInterval(_statusPollIv);
  _statusPollIv = setInterval(refreshStatus, STATUS_POLL_MS);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantActivityModule = { openApplicantActivity, refreshStatus };

// Expose for deep-links / other modules without import coupling.
try { window.applicantActivityModule = applicantActivityModule; } catch { /* no-op */ }

export default applicantActivityModule;
