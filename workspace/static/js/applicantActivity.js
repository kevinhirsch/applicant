// static/js/applicantActivity.js
//
// Agent-activity feed — surfaces the engine's EXISTING plain-language account of
// what the job agent is doing, in two front-door surfaces:
//
//   1. An always-visible STATUS STRIP in the app chrome (the chat top bar):
//      a compact first-person "<current action>" pill with a live/paused dot.
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
// .memory-toolbar-btn / .hwfit-loading / .applicant-status-strip). Refresh
// deliberately does NOT reuse .close-btn (SR-S1-1): sharing that class made
// the frosted theme render Refresh as a second, pixel-identical red
// close-disc next to the real Close control -- .memory-toolbar-btn is the
// same "small icon button in a modal header" treatment Portal/Vault/Today
// already use for their own Refresh buttons, so it reads as an action, not
// a window control.

import uiModule from './ui.js';
import {
  esc, _fetchJSON, _post, _toast, errText, loadingHTML, emptyHTML, errorHTML, gatedHTML,
  wireRetry, pollVisible,
} from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const API = '/api/applicant/activity';
// Global pause / kill-switch — fans out over the owner's campaigns engine-side.
const CONTROL_API = '/api/applicant/control';
// Slow poll for the always-visible strip — mirrors the Portal's BADGE_POLL_MS.
const STATUS_POLL_MS = 45000;

let _modalEl = null;
let _modalA11yCleanup = null;
let _statusPollStop = null;
let _runsLoading = false;
let _pauseBusy = false;



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
function _pauseBtnEl() { return document.getElementById('applicant-pause-toggle'); }
function _railEl() { return document.getElementById('rail-activity'); }

// ── Global pause / kill-switch (always-visible strip affordance) ─────────────
//
// A one-tap toggle sitting next to the status strip: Pause-all when the agent is
// live, Resume-all when it's paused. It reflects the live/paused state, shares the
// strip's visibility (hidden when there's no campaign / the engine is offline),
// and is a full ≥44px hit target with a visible focus ring (styled in style.css).

// Reflect running/paused on the toggle, or hide it when there's nothing to pause.
function _setPauseBtn(running, visible) {
  const btn = _pauseBtnEl();
  if (!btn) return;
  if (!visible) { btn.style.display = 'none'; return; }
  btn.style.display = 'inline-flex';
  btn.dataset.state = running ? 'live' : 'paused';
  const label = running ? 'Pause' : 'Resume';
  const aria = running
    ? "Pause me — I'll stop all automated work"
    : "Resume me — I'll restart automated work";
  btn.setAttribute('aria-label', aria);
  btn.setAttribute('aria-pressed', running ? 'false' : 'true');
  btn.title = aria;
  const lbl = btn.querySelector('.applicant-pause-label');
  if (lbl) lbl.textContent = label; else btn.textContent = label;
}

// Optimistically paint the strip + toggle to a target running/paused state before
// the network round-trip settles (reverted on error).
function _applyPauseOptimistic(running) {
  const strip = _stripEl();
  if (strip) {
    strip.classList.toggle('is-live', running);
    strip.classList.toggle('is-paused', !running);
  }
  const text = _stripTextEl();
  if (text && !running) text.textContent = 'Paused';
  _setPauseBtn(running, true);
}

async function _onPauseToggle() {
  const btn = _pauseBtnEl();
  if (!btn || _pauseBusy) return;
  const wasRunning = btn.dataset.state !== 'paused';
  // Confirm the global stop (one-tap resume needs no confirmation).
  if (wasRunning
      && !window.confirm("Pause all automated work? I'll stop everything until you resume.")) {
    return;
  }
  // Full path segments (leading slash) so the reachability contract sees the
  // literal /pause-all + /resume-all consumers, not a runtime-concatenated path.
  const action = wasRunning ? '/pause-all' : '/resume-all';
  _pauseBusy = true;
  btn.disabled = true;
  _applyPauseOptimistic(!wasRunning); // paused becomes the inverse of running
  try {
    await _post(`${CONTROL_API}${action}`);
    refreshStatus(); // reconcile with the engine's authoritative state
  } catch (e) {
    _applyPauseOptimistic(wasRunning); // revert
    _toast(errText(e));
  } finally {
    _pauseBusy = false;
    btn.disabled = false;
  }
}

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
  _setPauseBtn(false, false); // nothing to pause when the strip is hidden
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
  text.textContent = sentence;
  strip.title = `${text.textContent} — open Activity`;
  strip.style.display = 'inline-flex';
  // Keep the global pause/resume toggle in step with the live/paused state
  // (skipped mid-toggle so an in-flight optimistic click isn't clobbered).
  if (!_pauseBusy) _setPauseBtn(running, true);
  // There's activity → reveal the Activity nav entry too.
  _setActivityVisible(true);
}

// A transient fetch failure used to HIDE the strip, which reads as "the assistant
// is dead". Instead, if the strip is already on screen, keep it and show a neutral
// "· reconnecting…" note so a blip reads as a hiccup, not a death. Only hide when
// the strip was never shown (nothing to reconnect to yet).
function _renderReconnecting() {
  const strip = _stripEl();
  const text = _stripTextEl();
  if (!strip || !text) return false;
  const visible = strip.style.display && strip.style.display !== 'none';
  if (!visible) return false;
  strip.classList.remove('is-live');
  strip.classList.add('is-paused');
  text.textContent = 'Reconnecting…';
  strip.title = 'Reconnecting — open Activity';
  return true;
}

async function refreshStatus() {
  try {
    const data = await _fetchJSON(`${API}/status`);
    _renderStrip(data);
  } catch {
    // Proxy/engine error — keep a visible strip in a neutral "reconnecting" state
    // rather than vanishing (which reads as dead). Hide only if never shown.
    if (!_renderReconnecting()) _hideStrip();
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
          <button type="button" id="applicant-activity-back-portal" title="Back to Pending" aria-label="Back to Pending — everything across your job search that needs your attention" style="display:none;background:none;border:none;color:var(--accent, var(--red));font:inherit;font-size:11px;font-weight:600;cursor:pointer;padding:0;margin-right:8px;vertical-align:1px;">&larr; Pending</button>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          Activity
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button type="button" class="memory-toolbar-btn" id="applicant-activity-refresh" title="Refresh the activity feed" aria-label="Refresh the activity feed" style="width:26px;height:26px;padding:0;flex-shrink:0;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </button>
          <button class="close-btn" id="applicant-activity-close" title="Close" aria-label="Close">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>
      <div id="applicant-activity-snapshot" style="flex:0 0 auto;"></div>
      <div class="modal-body" id="applicant-activity-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
      <div id="applicant-activity-learning" style="flex:0 0 auto;"></div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Escape is handled by initModalA11y above (topmost-modal arbiter,
  // design-audit item #17) — do not add a second local Escape listener here.
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-activity-close').addEventListener('click', _close);
  modal.querySelector('#applicant-activity-refresh').addEventListener('click', () => { _loadSnapshot(); _loadRuns(true); _loadLearning(); });
  // "← Back to Pending" (audit #7's reverse of the redline "Continue to
  // submit" CTA): only shown when this page was reached via a deep link
  // (see openApplicantActivity's `viaRoute` flag) — i.e. the user didn't
  // navigate here from within the app, so Portal (the home base) isn't
  // one click behind them the way it normally would be.
  modal.querySelector('#applicant-activity-back-portal').addEventListener('click', () => {
    _close();
    if (window.applicantPortalModule && window.applicantPortalModule.openApplicantPortal) {
      window.applicantPortalModule.openApplicantPortal();
    }
  });
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _setBackToPendingVisible(show) {
  const btn = document.getElementById('applicant-activity-back-portal');
  if (btn) btn.style.display = show ? '' : 'none';
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  // Hash routing (audit #7): only clears when the hash is actually ours —
  // safe to call even when Activity closed for an unrelated reason while
  // some other hash (a session id, a different route) is current.
  clearHash('activity');
}

// Exported so other modules/tests can close Activity without reaching into
// its private state, mirroring openApplicantActivity's public export.
export function closeApplicantActivity() {
  _close();
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
  // Hierarchy from weight, not all-caps micro-type: the label stays sentence-case
  // (the strings passed in already are — "Now" / "Up next") at a Medium/Semibold
  // weight so it reads as a label without shouting.
  return `
    <div style="margin:2px 0;font-size:12px;line-height:1.4;">
      <span style="opacity:0.65;font-size:11px;font-weight:600;">${esc(label)}</span>
      <div style="font-weight:500;">${esc(sentence)}${tail}</div>
    </div>`;
}

// Loop-health chip (dark-engine audit #63): the scheduler already tracks
// operational metrics across ticks — total/succeeded/failed counts, the
// consecutive-failure streak, and whether the stall alert is currently armed
// — and this data already reaches the browser inside the status/snapshot
// payloads (engine `scheduler.state()` → the read-only status proxy's
// `scheduler.metrics`, and the consolidated snapshot's `now.metrics`), but
// nothing rendered it. `_loopMetrics` finds the metrics object wherever the
// caller's payload put it; `_healthChipText`/`_healthWarningText` turn the
// raw counters into plain language — no jargon, no fabricated numbers (a
// chip only renders once at least one tick has actually happened).
function _loopMetrics(data) {
  const m = (data && data.now && data.now.metrics) || (data && data.scheduler && data.scheduler.metrics);
  return (m && typeof m === 'object') ? m : null;
}

function _healthChipText(m) {
  const total = Number(m.ticks_total);
  if (!Number.isFinite(total) || total <= 0) return '';
  const failed = Number(m.ticks_failed) || 0;
  const runs = `${total} run${total === 1 ? '' : 's'}`;
  if (failed === 0) return `${runs} · no failures yet`;
  if (m.last_tick_success === false && m.last_heartbeat) {
    const when = _relTime(m.last_heartbeat);
    return `${runs} · last failure ${when || 'recently'}`;
  }
  return `${runs} · ${failed} failure${failed === 1 ? '' : 's'} so far`;
}

function _healthWarningText(m) {
  if (!m.alerting) return '';
  const consecutive = Number(m.consecutive_failures) || 0;
  return `Stalled — ${consecutive} run${consecutive === 1 ? '' : 's'} in a row failed. Take a look when you can.`;
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
  // System-token dot: green while live, neutral ink while paused/idle (matches the
  // always-visible strip's semantics, but this is the MODAL's own snapshot dot —
  // a separate element from #applicant-status-strip .applicant-status-dot).
  const dot = `<span style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px;background:${live ? 'var(--color-success, #4caf50)' : 'var(--color-muted, #999)'};"></span>`;
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
  // Loop-health chip: a compact, plain-language line under Now/Up next
  // ("312 runs · no failures yet"), plus a visible warning when the
  // scheduler's consecutive-failure stall alert is currently armed.
  const metrics = _loopMetrics(data);
  if (metrics) {
    const chipText = _healthChipText(metrics);
    if (chipText) {
      parts.push(`
        <div style="margin:4px 0 0;font-size:11px;opacity:0.65;">${esc(chipText)}</div>`);
    }
    const warnText = _healthWarningText(metrics);
    if (warnText) {
      parts.push(`
        <div style="margin:4px 0 0;font-size:11px;font-weight:600;color:var(--orange, #ffb86c);">${esc(warnText)}</div>`);
    }
  }
  if (!parts.length) { host.innerHTML = ''; return; }
  host.innerHTML = `
    <div class="admin-card" style="margin:0 0 8px;padding:10px 12px;">
      <div style="font-size:11px;font-weight:600;opacity:0.8;margin-bottom:4px;">${dot}Right now</div>
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
      My activity will appear here once I'm connected and running.
    </div>`;
}

// A GATED response (engine up, setup incomplete) is NOT offline — show the
// engine's own plain-language setup message so the owner knows what to finish.
function _renderGated(host, data) {
  const msg = (data && data.message)
    || "Finish setup — connect a model and fill in your profile — and I can start working for you.";
  host.innerHTML = `
    <div style="padding:18px 8px;text-align:center;font-size:12px;opacity:0.8;">${esc(msg)}</div>`;
}

function _renderEmpty(host) {
  // A hopeful first-run heartbeat rather than a flat "nothing here" — the assistant
  // is warming up, not idle.
  host.innerHTML = emptyHTML(
    'Warming up',
    "No activity yet — I'm getting ready. As soon as I start "
      + 'working on your job search, everything I do shows up here.',
  );
}

// Friendly one-line summary from a run's stats block, e.g.
// "discovered 5 · pre-filled 3 · submitted 1". Each part is included only when
// it carries a number, so a sparse run reads cleanly. Returns '' when empty.
function _statSummary(stats) {
  if (!stats || typeof stats !== 'object') return '';
  const parts = [];
  const push = (n, label) => {
    const v = Number(n);
    if (Number.isFinite(v) && v > 0) parts.push(`${label} ${v}`);
  };
  push(stats.discovered, 'discovered');
  push(stats.digest_rows, 'shortlisted');
  push(stats.pipelines_started, 'pre-filled');
  push(stats.handoffs, 'handed to you');
  push(stats.completed, 'submitted');
  let line = parts.join(' · ');
  const budget = Number(stats.budget_remaining);
  if (Number.isFinite(budget) && budget >= 0) {
    line += `${line ? ' · ' : ''}${budget} more I can send today`;
  }
  return line;
}

function _runTime(run) {
  return run.created_at || run.finished_at || run.started_at || run.last_run_at || run.timestamp || run.ts || '';
}

// ── Per-run receipt (H1 — receipts, not narration) ───────────────────────────
//
// Every row in this feed is a projection of a RECORDED run row (the engine's
// ``agent_runs`` table: a deterministic intent sentence plus a stats block of
// counters persisted when the run actually happened) — never a model
// describing what it thinks it did. This renders that recorded record as an
// inline, expandable receipt under each row, so the sentence above it can be
// checked against the exact numbers it was computed from. Pure HTML in/out
// (sliced + executed headlessly by the test harness). Honesty rules: a
// counter the record doesn't carry contributes NO line (a receipt never pads
// itself with fabricated zeros), and a run with no recorded numbers at all
// renders NO receipt rather than an empty shell that reads as one.

// Plain-language labels for the machine `skip_reason` token a no-new-work run
// records (the engine's own SKIP_REASON_SENTENCES carries the full sentence;
// this is just the receipt's short form). Unknown tokens fall back to the raw
// recorded value — showing the record beats hiding it.
const _SKIP_REASON_LABELS = {
  run_mode_stop: 'paused by your run schedule',
  automated_work_gated: 'waiting on setup',
};

function _receiptHTML(run) {
  if (!run || typeof run !== 'object') return '';
  const stats = (run.stats && typeof run.stats === 'object') ? run.stats : {};
  const rows = [];
  const pushCount = (n, label) => {
    const v = Number(n);
    if (Number.isFinite(v) && v > 0) rows.push([label, String(v)]);
  };
  pushCount(stats.discovered, 'Roles found');
  pushCount(stats.digest_rows, 'Shortlisted for you');
  pushCount(stats.pipelines_started, 'Applications started');
  pushCount(stats.handoffs, 'Handed to you');
  pushCount(stats.completed, 'Submitted');
  const budget = Number(stats.budget_remaining);
  if (Number.isFinite(budget) && budget >= 0 && ('budget_remaining' in stats)) {
    rows.push(['Left in today’s budget', String(budget)]);
  }
  pushCount(stats.llm_calls, 'Model calls');
  const cost = Number(stats.cost_usd_estimate);
  if (Number.isFinite(cost) && cost > 0) rows.push(['Estimated model cost', `~$${cost.toFixed(2)}`]);
  if (stats.skip_reason) {
    rows.push(['Why no new work started', _SKIP_REASON_LABELS[stats.skip_reason] || String(stats.skip_reason)]);
  }
  const when = _runTime(run);
  if (rows.length && when) rows.push(['Recorded at', String(when)]);
  if (!rows.length) return '';
  const lines = rows.map(([k, v]) => `
      <div style="display:flex;justify-content:space-between;gap:10px;font-size:10.5px;padding:2px 0;">
        <span style="opacity:0.65;">${esc(k)}</span>
        <span style="font-variant-numeric:tabular-nums;">${esc(v)}</span>
      </div>`).join('');
  return `
    <details class="applicant-run-receipt" style="margin-top:4px;">
      <summary style="cursor:pointer;font-size:10px;opacity:0.55;list-style-position:inside;"
        title="This line is computed from a recorded run — these are the exact numbers it came from">Receipt</summary>
      <div style="margin-top:3px;padding:5px 8px;border:1px solid var(--border);border-radius:5px;">${lines}</div>
    </details>`;
}

// Dark-engine audit #59: the engine's ``AgentRun``/intent-sentence history
// (``core/entities/agent_run.py``, persisted with a timestamp per run) is
// real history, not just "the latest line" -- but this page previously
// rendered ``items`` exactly as the engine returned them: OLDEST first,
// unbounded (a campaign that has run for weeks could return thousands of
// rows). That defeated the "Recently I…" heading and buried the actual
// recent trail at the bottom of a very long scroll. The engine's own ordering
// contract is oldest-first (see ``AgentRunRepository.list_for_campaign``,
// contract-tested) -- every consumer is expected to reverse/cap client-side,
// exactly like the sibling admin debug "Recent runs" mini-table already does
// (dark-engine audit #75, ``applicantDebug.js`` ``_recentRunsCard``:
// "items.slice(-8).reverse()"). This is that same fix for the dedicated
// Activity page's fuller "intent timeline": the most recent
// ``_RECENT_RUNS_CAP`` runs, newest first, in a short scrollable list.
const _RECENT_RUNS_CAP = 25;

function _renderRuns(host, items) {
  if (!items.length) { _renderEmpty(host); return; }
  const recent = items.slice(-_RECENT_RUNS_CAP).reverse();
  const rows = recent.map((run) => {
    const intent = run.intent || run.summary || 'Worked on your job search';
    const summary = _statSummary(run.stats);
    const when = _relTime(_runTime(run));
    const meta = [summary, when].filter(Boolean).join(' · ');
    // H1 (receipts, not narration): the recorded run record behind this row,
    // expandable in place — see _receiptHTML's own header comment.
    const receipt = _receiptHTML(run);
    return `
      <div class="memory-item og-card" style="display:block;padding:9px 10px;border-bottom:1px solid var(--border);">
        <div style="font-size:12px;font-weight:500;line-height:1.35;">${esc(intent)}</div>
        ${meta ? `<div class="memory-item-meta" style="font-size:10.5px;opacity:0.6;margin-top:3px;">${esc(meta)}</div>` : ''}
        ${receipt}
      </div>`;
  });
  const heading = `
    <div style="padding:4px 10px 6px;font-size:11px;font-weight:600;opacity:0.6;"
      title="Each row is one pass I took through your job search, newest first">
      Recently I…
    </div>`;
  host.innerHTML = `<div>${heading}${rows.join('')}</div>`;
}

async function _loadRuns(showSpinner) {
  if (_runsLoading) return;
  _runsLoading = true;
  const host = _body();
  if (host && showSpinner) host.innerHTML = loadingHTML('Loading activity…');
  try {
    const data = await _fetchJSON(`${API}/runs`);
    if (!host) return;
    if (data && data.gated === true) { _renderGated(host, data); return; }
    if (data && data.engine_available === false) { _renderOffline(host); return; }
    const items = (data && data.items) || [];
    _renderRuns(host, items);
  } catch (e) {
    if (host) {
      host.innerHTML = errorHTML(errText(e));
      wireRetry(host, () => _loadRuns(true));
    }
  } finally {
    _runsLoading = false;
  }
}

// ── "What I'm learning" section (P1-12 — the learning loop's narrative home) ─
//
// The engine's learning/outcomes loop (LearningService.build_summary — which
// sources convert, which roles convert, what the owner's own decline feedback
// keeps saying) already existed as a read-model but was reachable only behind
// the admin-gated Debug modal. This renders it at the foot of the Activity
// page — where the owner already watches the agent work — through the
// owner-scoped `/api/applicant/activity/learning` proxy. Honest by
// construction: the proxy's `has_learning` is true only when there is REAL
// recorded volume/feedback, so this section renders nothing (no card, no
// heading) for a fresh campaign — the absence of learning never renders as
// learning.

function _learningHost() { return _modalEl && _modalEl.querySelector('#applicant-activity-learning'); }

// Pure line-builder (exported for headless tests): turns the learning payload
// into plain-language sentences, each included only when its data is real.
export function _learningLines(data) {
  const lines = [];
  if (!data || typeof data !== 'object') return lines;
  const sources = Array.isArray(data.sources) ? data.sources : [];
  const best = sources.find((s) => {
    if (!s || typeof s !== 'object' || !s.source) return false;
    return ['matched', 'approved', 'submitted'].some((k) => Number(s[k]) > 0);
  });
  if (best) {
    const matched = Number(best.matched) || 0;
    const submitted = Number(best.submitted) || 0;
    if (submitted > 0 && matched > 0) {
      lines.push(`Best source so far: ${best.source} — ${submitted} of ${matched} matches there went on to a submission, so I look there first.`);
    } else if (matched > 0) {
      lines.push(`Most matches so far come from ${best.source} (${matched} so far), so I look there first.`);
    }
  }
  const roles = (Array.isArray(data.converting_roles) ? data.converting_roles : [])
    .filter((r) => typeof r === 'string' && r.trim()).slice(0, 3);
  if (roles.length) {
    lines.push(`Roles like “${roles.join('”, “')}” have converted for you, so similar ones score higher now.`);
  }
  const reasons = (Array.isArray(data.decline_reasons) ? data.decline_reasons : [])
    .map((r) => (r && typeof r === 'object' ? String(r.reason || '') : ''))
    .filter(Boolean).slice(0, 3);
  if (reasons.length) {
    lines.push(`When you pass on a role, “${reasons.join('”, “')}” come up most — I weigh those against new matches.`);
  }
  return lines;
}

function _renderLearning(host, data) {
  if (!host) return;
  if (!data || data.engine_available === false || data.has_learning !== true) {
    host.innerHTML = '';
    return;
  }
  const lines = _learningLines(data);
  if (!lines.length) { host.innerHTML = ''; return; }
  const rows = lines.map((l) => `<div style="margin:2px 0;font-size:11.5px;line-height:1.45;">${esc(l)}</div>`).join('');
  host.innerHTML = `
    <div class="admin-card" style="margin:8px 0 0;padding:10px 12px;">
      <div style="font-size:11px;font-weight:600;opacity:0.8;margin-bottom:4px;"
        title="Learned from your approvals, declines, and real outcomes — it adjusts what I look for next">
        What I’m learning
      </div>
      ${rows}
    </div>`;
}

async function _loadLearning() {
  const host = _learningHost();
  if (!host) return;
  try {
    const data = await _fetchJSON(`${API}/learning`);
    _renderLearning(host, data);
  } catch {
    host.innerHTML = ''; // bonus section — hide silently, never a broken panel
  }
}

// `opts.viaRoute` marks an open that came from the hash router (a deep
// link/shared link/back-forward on '#activity', or a refresh landing on
// that hash) rather than an in-app click — it shows the "← Back to
// Pending" affordance, since the user didn't navigate here from Portal the
// way an in-app click normally implies. `opts.skipHashUpdate` is for the
// router's own registered `open` callback: the hash already equals
// 'activity' by the time it fires, so there's nothing to update.
export async function openApplicantActivity(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('activity');
  _setBackToPendingVisible(!!(opts && opts.viaRoute));
  // The live "now / next" header, the "recently" history, and the
  // "What I'm learning" footer load together.
  _loadSnapshot();
  _loadLearning();
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
  const pauseBtn = _pauseBtnEl();
  if (pauseBtn && !pauseBtn._applicantPauseWired) {
    pauseBtn._applicantPauseWired = true;
    // Sibling of the strip button — stop propagation so pausing doesn't also
    // open the Activity page.
    pauseBtn.addEventListener('click', (e) => { e.stopPropagation(); _onPauseToggle(); });
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
  // Keep the strip fresh on a slow poll — but only while the tab is visible, so a
  // backgrounded tab doesn't keep hitting the proxy (quick-wins #1). pollVisible
  // fires once immediately, so it also seeds the strip.
  if (_statusPollStop) _statusPollStop();
  _statusPollStop = pollVisible(refreshStatus, STATUS_POLL_MS);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#activity' deep-links straight into the
// Activity page — a refresh/shared-link/back-forward on that hash
// opens/closes it. `viaRoute: true` flags the open as hash-driven so the
// "← Back to Pending" affordance shows (see openApplicantActivity above).
// Registered at module-eval time (runs as soon as app.js's dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('activity', { open: () => openApplicantActivity({ viaRoute: true }), close: _close });

const applicantActivityModule = { openApplicantActivity, closeApplicantActivity, refreshStatus };

// Expose for deep-links / other modules without import coupling.
try { window.applicantActivityModule = applicantActivityModule; } catch { /* no-op */ }

export default applicantActivityModule;
