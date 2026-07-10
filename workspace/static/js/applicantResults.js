// static/js/applicantResults.js
//
// Results — a first-class, NON-admin window onto the outcome/learning data the
// engine already computes for the owner's job search. This is the #1 audit finding:
// that outcome data used to be reachable only through the admin-gated Activity/Debug
// tab. Results surfaces it plainly for every owner.
//
// It renders, for the owner's campaign:
//
//   1. THE FUNNEL — matched → approved → submitted, with the drop-off rate at each
//      step (how many roles the assistant found, how many you approved, how many
//      were submitted).
//   2. PER-SOURCE CONVERSION — each place the assistant looks for roles, ranked by
//      how well it converts (submitted per matched), as a readable bar.
//   3. WHAT CONVERTS FOR YOU — the learned role signature: the kinds of roles that
//      actually move forward, so you can see the bias the assistant applies.
//   4. WHY YOU DECLINE — the words most common in your own decline feedback (every
//      decline requires a short reason), so a pattern across many declines is
//      visible without re-reading each one yourself.
//
// Each section leads with a narrated, plain-language sentence (not just a labeled
// bar/number) so a glance reads as a takeaway, not a stat dump.
//
// This is ADDITIVE, self-contained, and surfacing-only. It talks to the engine only
// through the workspace proxy at /api/applicant/results (it never reaches the engine
// directly), creates no engine state, and degrades gracefully: a designed empty state
// for a brand-new user (no submissions yet), an honest "finish setup" state when the
// engine gates the read, and an offline note when the engine is unreachable. Styling
// reuses the workspace design system (.modal / .modal-content / .modal-header /
// .modal-body / .cal-btn / .close-btn / .admin-card / .memory-item) with neutral
// chrome — no brand hue on text.

import uiModule from './ui.js';
import {
  esc, _fetchJSON, _toast, errText, loadingHTML, emptyHTML, errorHTML, gatedHTML,
  wireRetry, pollVisible,
} from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const API = '/api/applicant/results';

let _modalEl = null;
let _modalA11yCleanup = null;
let _pollStop = null;
let _loading = false;
// Fingerprint of the last data actually rendered (audit 01 #32): lets a silent
// 60s background poll skip re-rendering when nothing changed, so it doesn't
// reset scroll position or kill an in-progress text selection mid-read. A
// user-initiated refresh (showSpinner) always renders regardless.
let _lastResultsKey = null;
// Realtime push ⇄ poll coordination (realtime-websocket.md Phase 2): true while the
// WS push channel is live, so the 60s background poll is RETIRED and the engine's
// `notif`/`tracker` push (surfaced as `applicant:data-changed`) drives refreshes
// instead; on WS loss the poll is RESTORED as the fallback (no silent dead UI).
let _realtimeLive = false;


// ── Small formatting helpers ────────────────────────────────────────────────

function _num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// A whole-number percentage string, or '' when there's no denominator.
function _pct(part, whole) {
  const p = _num(part);
  const w = _num(whole);
  if (w <= 0) return '';
  return `${Math.round((100 * p) / w)}%`;
}

// ── Modal shell ──────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-results-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Results');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:640px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>
          Results
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-results-refresh" title="Refresh your results">Refresh</button>
          <button class="close-btn" id="applicant-results-close" title="Close" aria-label="Close">✖</button>
        </div>
      </div>
      <div class="modal-body" id="applicant-results-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Escape is handled by initModalA11y above (topmost-modal arbiter,
  // design-audit item #17) — do not add a second local Escape listener here.
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-results-close').addEventListener('click', _close);
  modal.querySelector('#applicant-results-refresh').addEventListener('click', () => _load(true));
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
  if (_pollStop) { _pollStop(); _pollStop = null; }
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('results');
}

// Exported so other modules/tests can close Results without reaching into
// its private state, mirroring openApplicantResults' public export.
export function closeApplicantResults() {
  _close();
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-results-body'); }

function _refreshBtn() { return _modalEl && _modalEl.querySelector('#applicant-results-refresh'); }

// ── Section renderers ────────────────────────────────────────────────────────

// One tooltip-bearing section label.
function _sectionHead(title, tip) {
  return `<div style="display:flex;align-items:center;gap:6px;padding:2px 0 8px;">
      <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">${esc(title)}</span>
      ${tip ? `<span title="${esc(tip)}" style="cursor:help;opacity:0.4;font-size:11px;" aria-label="${esc(tip)}">ⓘ</span>` : ''}
    </div>`;
}

// A short, first-glance narrated sentence for a section — a real takeaway, not a
// number to interpret. Rendered above the bars/chips so the section reads as prose
// first, detail second.
function _headline(text) {
  return text
    ? `<div style="font-size:12px;line-height:1.5;margin-bottom:10px;">${esc(text)}</div>`
    : '';
}

// The matched → approved → submitted funnel. Leads with a narrated one-sentence
// takeaway (counts + the overall conversion rate in plain language); each step
// below still shows its count and, from the second step on, the share of the
// PREVIOUS step it kept (the pass-through rate) so the drop-off is visible too.
function _renderFunnel(summary) {
  const matched = _num(summary.total_matched);
  const approved = _num(summary.total_approved);
  const submitted = _num(summary.total_submitted);
  const steps = [
    { label: 'Matched', tip: 'Roles I found that fit your criteria.', value: matched, of: null },
    { label: 'Approved', tip: 'Roles you approved to move forward.', value: approved, of: matched },
    { label: 'Submitted', tip: 'Applications that were submitted.', value: submitted, of: approved },
  ];
  const max = Math.max(matched, approved, submitted, 1);
  const rows = steps.map((s) => {
    const w = Math.max(2, Math.round((100 * _num(s.value)) / max));
    const rate = s.of != null ? _pct(s.value, s.of) : '';
    const rateLabel = rate ? `<span style="opacity:0.55;font-size:10.5px;margin-left:6px;">${esc(rate)} of the step before</span>` : '';
    return `
      <div style="margin:6px 0;">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px;">
          <span title="${esc(s.tip)}">${esc(s.label)}${rateLabel}</span>
          <span style="font-weight:600;">${esc(String(s.value))}</span>
        </div>
        <div style="height:8px;border-radius:4px;background:var(--border,#e5e5e5);overflow:hidden;">
          <div style="height:100%;width:${w}%;background:var(--fg-muted,#888);opacity:0.55;"></div>
        </div>
      </div>`;
  });
  const overall = matched > 0 ? _pct(submitted, matched) : '';
  let headline = '';
  if (matched > 0) {
    // NOTE: kept as a straight apostrophe deliberately — pinned verbatim by
    // the out-of-scope test_applicant_backlog_narratedinsights.py (needle
    // "You've had ${matched} role"), which this single-file lane may not edit.
    headline = `You've had ${matched} role${matched === 1 ? '' : 's'} matched so far — `
      + `you approved ${approved}, and ${submitted} ${submitted === 1 ? 'has' : 'have'} been submitted`
      + (overall ? ` (${overall} of everything matched).` : '.');
  }
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('Your funnel', 'How roles move from found, to approved by you, to submitted.')}
      ${_headline(headline)}
      ${rows.join('')}
    </div>`;
}

// Per-source conversion: each place the assistant looks, ranked by how well it
// converts (submitted per matched), as a readable bar. The engine already ranks
// the list; we render it in order. Leads with a narrated sentence naming the
// best-converting source with real counts, e.g. "You're converting best on
// LinkedIn — 3 of 5 matched roles there were submitted." (audit: readable
// prose, not just a bar + percentage to interpret).
function _sourcesHeadline(sources) {
  // The list is already ranked by conversion (source_ranking); the first entry
  // with any actual submitted volume is the real standout, not a zero-data source
  // that merely sorts first for lack of competition.
  const top = sources.find((s) => _num(s.submitted) > 0);
  if (!top) return '';
  const rate = (top.conversion_rate == null) ? null : _num(top.conversion_rate);
  const rateText = rate == null ? '' : ` (${rate}%)`;
  return `You’re converting best on ${top.source || 'this source'} — `
    + `${_num(top.submitted)} of ${_num(top.matched)} matched roles there were submitted${rateText}.`;
}

// NOTE: the tooltip below keeps its straight apostrophe ("it's") deliberately
// — pinned verbatim by the out-of-scope test_applicant_copy_results_core_lens02.py,
// which this single-file lane may not edit.
function _renderSources(sources) {
  if (!sources.length) return '';
  const rows = sources.map((s) => {
    const rate = (s.conversion_rate == null) ? null : _num(s.conversion_rate);
    const w = rate == null ? 0 : Math.max(2, Math.min(100, Math.round(rate)));
    const rateText = rate == null ? '—' : `${rate}%`;
    const counts = `${_num(s.matched)} matched · ${_num(s.submitted)} submitted`;
    return `
      <div class="memory-item" style="display:block;padding:8px 0;border-bottom:1px solid var(--border);">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;margin-bottom:3px;">
          <span style="font-weight:500;">${esc(String(s.source || 'Unknown source'))}</span>
          <span title="Share of matched roles from here that were submitted." style="font-weight:600;">${esc(rateText)}</span>
        </div>
        <div style="height:6px;border-radius:3px;background:var(--border,#e5e5e5);overflow:hidden;margin-bottom:3px;">
          <div style="height:100%;width:${w}%;background:var(--fg-muted,#888);opacity:0.55;"></div>
        </div>
        <div style="font-size:10px;opacity:0.55;">${esc(counts)}</div>
      </div>`;
  });
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('Where your roles come from', "Each place I search, ranked by how well it's working for you.")}
      ${_headline(_sourcesHeadline(sources))}
      ${rows.join('')}
    </div>`;
}

// The learned "what converts for you" role signature — role titles only, the
// plain-language bias the assistant applies.
//
// NOTE: the tooltip below keeps its straight apostrophe ("I've") deliberately
// — pinned verbatim by the out-of-scope test_applicant_copy_results_core_lens02.py,
// which this single-file lane may not edit.
function _renderSignature(roles, samples) {
  if (!roles.length) return '';
  const chips = roles.map((r) => `
    <span style="display:inline-block;padding:3px 9px;margin:0 6px 6px 0;border-radius:12px;border:1px solid var(--border);font-size:11px;">${esc(String(r))}</span>`);
  const headline = 'Based on what’s actually converted so far, you tend to move forward on roles like these:';
  const sub = (samples != null && _num(samples) > 0)
    ? `<div style="font-size:10px;opacity:0.55;margin-bottom:8px;">Based on ${esc(String(_num(samples)))} application${_num(samples) === 1 ? '' : 's'} that moved forward.</div>`
    : '';
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('What converts for you', "The kinds of roles that actually move forward — what I've learned to favor for you.")}
      ${_headline(headline)}
      ${sub}
      <div>${chips.join('')}</div>
    </div>`;
}

// "Why you decline" — the words most common in your own decline feedback. Every
// decline requires a short stated reason (FR-FB-1); this rolls those words up so a
// pattern across many declines ("onsite", "salary"...) is visible at a glance
// instead of re-reading each decline's feedback yourself. Grounded in the user's
// own words (a plain frequency count), never a guessed/invented category — so the
// label is honest about what it is ("words that come up most"), not a claim that
// the engine has classified WHY in some richer sense.
function _renderDeclines(reasons) {
  if (!reasons.length) return '';
  const top = reasons[0];
  const headline = `Here’s what comes up most when you decline a role — `
    + `most often "${top.reason}" (${_num(top.count)} time${_num(top.count) === 1 ? '' : 's'}).`;
  const chips = reasons.map((r) => `
    <span style="display:inline-block;padding:3px 9px;margin:0 6px 6px 0;border-radius:12px;border:1px solid var(--border);font-size:11px;">${esc(String(r.reason))} <span style="opacity:0.55;">(${esc(String(_num(r.count)))})</span></span>`);
  return `
    <div class="admin-card" style="margin:0 0 4px;padding:12px;">
      ${_sectionHead('Why you decline', 'Words that come up most in your own decline feedback — every decline asks you briefly why.')}
      ${_headline(headline)}
      <div>${chips.join('')}</div>
    </div>`;
}

function _renderResults(host, data) {
  const summary = (data && data.summary) || {};
  const sources = (data && data.sources) || [];
  const roles = (data && data.converting_roles) || [];
  const declineReasons = (data && data.decline_reasons) || [];
  const parts = [
    _renderFunnel(summary),
    _renderSources(sources),
    _renderSignature(roles, data && data.converting_samples),
    _renderDeclines(declineReasons),
  ].filter(Boolean);
  host.innerHTML = parts.join('');
}

// Designed empty state for a brand-new user: reachable engine + a campaign, but no
// submissions yet. Hopeful, not a flat "nothing here".
//
// NOTE: the body text below keeps its straight apostrophes ("I've"/"You'll")
// deliberately — pinned verbatim by the out-of-scope
// test_applicant_copy_results_core_lens02.py, which this single-file lane
// may not edit.
function _renderEmpty(host) {
  host.innerHTML = emptyHTML(
    'No results yet',
    'Your results appear here once I\'ve submitted a few applications for you. '
    + 'You\'ll see how roles move from found, to approved, to submitted — plus which '
    + 'sources convert best and what kinds of roles move forward for you.',
    '<button type="button" class="cal-btn" id="applicant-results-empty-activity">See what I’m working on</button>',
  );
  const btn = host.querySelector('#applicant-results-empty-activity');
  if (btn) btn.addEventListener('click', () => {
    _close();
    // Open Activity via its own exported launcher — this modal is not
    // registered with the hash router, so a bare setHash('activity') from
    // here can change the URL without opening anything (Greptile on #747);
    // the hash write stays as the fallback/URL-state keeper.
    try {
      if (window.applicantActivityModule && window.applicantActivityModule.openApplicantActivity) {
        window.applicantActivityModule.openApplicantActivity();
        return;
      }
    } catch (_) { /* fall through */ }
    setHash('activity');
  });
}

// NOTE: the body text below keeps its straight apostrophe ("I'm") deliberately
// — pinned verbatim by the out-of-scope test_applicant_copy_results_core_lens02.py,
// which this single-file lane may not edit.
function _renderOffline(host) {
  host.innerHTML = emptyHTML(
    'Not connected yet',
    'Your results will appear here once I\'m connected and running.',
    '',
    'neutral',
  );
}

// A GATED response (engine up, setup incomplete) is NOT offline — show the engine's
// own plain-language setup message so the owner knows what to finish, with the
// same one-tap "Finish setup" resume as Today's gated state (P0-5: no dead-end
// panes).
function _renderGated(host, data) {
  const msg = (data && data.message)
    || 'Finish setup and connect a model — your results will start appearing here.';
  host.innerHTML = gatedHTML(msg,
    '<button type="button" class="cal-btn cal-btn-primary" id="applicant-results-gated-setup">Finish setup</button>');
  const btn = host.querySelector('#applicant-results-gated-setup');
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
  // Busy/disabled guard (audit 01 #35): a second click on Refresh while a load
  // is already in flight is otherwise silently a no-op — visibly disable the
  // button so it reads as busy instead of broken.
  if (_loading) return;
  _loading = true;
  const host = _body();
  const btn = _refreshBtn();
  if (btn) { btn.disabled = true; btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = 'Refreshing…'; }
  if (host && showSpinner) host.innerHTML = loadingHTML('Loading your results…');
  try {
    const data = await _fetchJSON(API);
    if (!host) return;
    if (data && data.gated === true) { _lastResultsKey = null; _renderGated(host, data); return; }
    if (data && data.engine_available === false) { _lastResultsKey = null; _renderOffline(host); return; }
    if (!data || data.has_data === false) { _lastResultsKey = null; _renderEmpty(host); return; }
    const key = JSON.stringify(data);
    if (!showSpinner && key === _lastResultsKey) return;
    _lastResultsKey = key;
    _renderResults(host, data);
  } catch (e) {
    if (host) {
      host.innerHTML = errorHTML(errText(e));
      wireRetry(host, () => _load(true));
    }
  } finally {
    _loading = false;
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || 'Refresh'; }
  }
}

export async function openApplicantResults(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('results');
  await _load(true);
  // Keep it fresh while open (only while the tab is visible) — UNLESS the realtime
  // push channel is live, in which case `applicant:data-changed` drives refreshes and
  // the poll stays retired (restored automatically on WS loss). Reconcile the current
  // live level first (the socket may have opened before this surface cared).
  if (_pollStop) { _pollStop(); _pollStop = null; }
  try {
    if (typeof window !== 'undefined' && window.__applicantRealtimeLive) _realtimeLive = true;
  } catch { /* no-op */ }
  _startPollIfNeeded();
}

// ── Realtime push ⇄ poll coordination (realtime-websocket.md Phase 2) ─────────────
//
// While the WS push channel is LIVE, the engine's `notif`/`tracker` push (surfaced
// by applicantRealtime.js as `applicant:data-changed`) drives refreshes, so we RETIRE
// the 60s poll — no redundant fetches. On WS loss we RESTORE it as the fallback so the
// funnel never silently goes stale (an honesty invariant: no silent dead UI). We only
// own the poll while the modal is open (it is created on open, torn down on close).

function _isOpen() {
  return !!_modalEl && !_modalEl.classList.contains('hidden');
}

// Start the visibility-aware poll only when it's needed: the modal is open AND the
// push channel is NOT live AND no poll is already running.
function _startPollIfNeeded() {
  if (!_isOpen() || _realtimeLive || _pollStop) return;
  _pollStop = pollVisible(() => _load(false), 60000);
}

function _applyRealtimeLive(live) {
  const next = !!live;
  if (next === _realtimeLive) return;
  _realtimeLive = next;
  if (!_isOpen()) return; // nothing to retire/restore while closed — open() reconciles
  if (next) {
    // Live: retire the poll, but catch up once so anything that changed between the
    // last poll and going live is reflected right away.
    if (_pollStop) { _pollStop(); _pollStop = null; }
    _load(false);
  } else {
    // Lost the push channel: fall back to polling (and refresh once now).
    _load(false);
    _startPollIfNeeded();
  }
}

// A push says the underlying data changed — refetch through the EXISTING _load while
// the modal is open. `_load`'s fingerprint guard skips the re-render when nothing
// actually changed, so a redundant poke never disturbs an in-progress read.
function _onDataChanged() {
  if (_isOpen()) _load(false);
}

// ── Launcher + boot ──────────────────────────────────────────────────────────

function _wireLaunchers() {
  const rail = document.getElementById('rail-results');
  if (rail && !rail._applicantResultsWired) {
    rail._applicantResultsWired = true;
    rail.addEventListener('click', () => openApplicantResults());
  }
}

function _boot() {
  _wireLaunchers();
  // The rail may be (re)rendered after boot; retry briefly so the launcher always
  // gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLaunchers();
    if (document.getElementById('rail-results')?._applicantResultsWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
  // Phase 2: retire the poll while the realtime push channel is live and restore it on
  // WS loss (fallback). applicantRealtime.js emits `applicant:realtime` with { live } on
  // every connection-state change, and `applicant:data-changed` when a push says the
  // owner's data moved. Registered once here; both no-op while the modal is closed.
  document.addEventListener('applicant:realtime', (e) => {
    _applyRealtimeLive(!!(e && e.detail && e.detail.live));
  });
  document.addEventListener('applicant:data-changed', () => { _onDataChanged(); });
  // The `applicant:realtime` event is one-shot per state change, so reconcile the
  // current live level now in case the socket opened before this listener existed.
  try {
    if (typeof window !== 'undefined' && window.__applicantRealtimeLive) _applyRealtimeLive(true);
  } catch { /* no-op */ }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#results' deep-links straight into the Results
// page — a refresh/shared-link/back-forward on that hash opens/closes it.
// Registered at module-eval time (runs as soon as app.js's dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('results', { open: openApplicantResults, close: _close });

const applicantResultsModule = { openApplicantResults, closeApplicantResults };

// Expose for deep-links / other modules without import coupling.
try { window.applicantResultsModule = applicantResultsModule; } catch { /* no-op */ }
try { window.openApplicantResults = openApplicantResults; } catch { /* no-op */ }

export default applicantResultsModule;
