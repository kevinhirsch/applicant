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
  esc, _fetchJSON, errText, loadingHTML, emptyHTML, errorHTML, gatedHTML,
  wireRetry, pollVisible,
} from './applicantCore.js';

const API = '/api/applicant/results';

let _modalEl = null;
let _modalA11yCleanup = null;
let _pollStop = null;
let _loading = false;


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
          <button class="close-btn" id="applicant-results-close" title="Close">✖</button>
        </div>
      </div>
      <div class="modal-body" id="applicant-results-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') _close(); });
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
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-results-body'); }

// ── Section renderers ────────────────────────────────────────────────────────

// One tooltip-bearing section label.
function _sectionHead(title, tip) {
  return `<div style="display:flex;align-items:center;gap:6px;padding:2px 0 8px;">
      <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">${esc(title)}</span>
      ${tip ? `<span title="${esc(tip)}" style="cursor:help;opacity:0.4;font-size:11px;" aria-label="${esc(tip)}">ⓘ</span>` : ''}
    </div>`;
}

// The matched → approved → submitted funnel. Each step shows its count and, from
// the second step on, the share of the PREVIOUS step it kept (the pass-through
// rate) so the drop-off is visible at a glance.
function _renderFunnel(summary) {
  const matched = _num(summary.total_matched);
  const approved = _num(summary.total_approved);
  const submitted = _num(summary.total_submitted);
  const steps = [
    { label: 'Matched', tip: 'Roles the assistant found that fit your criteria.', value: matched, of: null },
    { label: 'Approved', tip: 'Roles you approved to move forward.', value: approved, of: matched },
    { label: 'Submitted', tip: 'Applications that were submitted.', value: submitted, of: approved },
  ];
  const max = Math.max(matched, approved, submitted, 1);
  const rows = steps.map((s) => {
    const w = Math.max(2, Math.round((100 * _num(s.value)) / max));
    const rate = s.of != null ? _pct(s.value, s.of) : '';
    const rateLabel = rate ? `<span style="opacity:0.55;font-size:10.5px;margin-left:6px;">${esc(rate)} of prior</span>` : '';
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
  const overallLine = overall
    ? `<div style="font-size:10.5px;opacity:0.6;margin-top:6px;">Overall, ${esc(overall)} of matched roles were submitted.</div>`
    : '';
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('Your funnel', 'How roles move from found, to approved by you, to submitted.')}
      ${rows.join('')}
      ${overallLine}
    </div>`;
}

// Per-source conversion: each place the assistant looks, ranked by how well it
// converts (submitted per matched), as a readable bar. The engine already ranks
// the list; we render it in order.
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
      ${_sectionHead('Where your roles come from', 'Each source the assistant searches, ranked by how well it converts for you.')}
      ${rows.join('')}
    </div>`;
}

// The learned "what converts for you" role signature — role titles only, the
// plain-language bias the assistant applies.
function _renderSignature(roles, samples) {
  if (!roles.length) return '';
  const chips = roles.map((r) => `
    <span style="display:inline-block;padding:3px 9px;margin:0 6px 6px 0;border-radius:12px;border:1px solid var(--border);font-size:11px;">${esc(String(r))}</span>`);
  const sub = (samples != null && _num(samples) > 0)
    ? `<div style="font-size:10px;opacity:0.55;margin-bottom:8px;">Learned from ${esc(String(_num(samples)))} converting application${_num(samples) === 1 ? '' : 's'}.</div>`
    : '';
  return `
    <div class="admin-card" style="margin:0 0 4px;padding:12px;">
      ${_sectionHead('What converts for you', 'The kinds of roles that actually move forward — the bias the assistant learns and applies.')}
      ${sub}
      <div>${chips.join('')}</div>
    </div>`;
}

function _renderResults(host, data) {
  const summary = (data && data.summary) || {};
  const sources = (data && data.sources) || [];
  const roles = (data && data.converting_roles) || [];
  const parts = [
    _renderFunnel(summary),
    _renderSources(sources),
    _renderSignature(roles, data && data.converting_samples),
  ].filter(Boolean);
  host.innerHTML = parts.join('');
}

// Designed empty state for a brand-new user: reachable engine + a campaign, but no
// submissions yet. Hopeful, not a flat "nothing here".
function _renderEmpty(host) {
  host.innerHTML = emptyHTML(
    'No results yet',
    'Your results appear here once your assistant has submitted a few applications. '
    + 'You\'ll see how roles move from found, to approved, to submitted — plus which '
    + 'sources convert best and what kinds of roles move forward for you.',
  );
}

function _renderOffline(host) {
  host.innerHTML = emptyHTML(
    'Results are offline',
    'Your results will appear here once your assistant is connected and running.',
  );
}

// A GATED response (engine up, setup incomplete) is NOT offline — show the engine's
// own plain-language setup message so the owner knows what to finish.
function _renderGated(host, data) {
  const msg = (data && data.message)
    || 'Finish onboarding and connect a model to start collecting results.';
  host.innerHTML = gatedHTML(msg);
}

async function _load(showSpinner) {
  if (_loading) return;
  _loading = true;
  const host = _body();
  if (host && showSpinner) host.innerHTML = loadingHTML('Loading your results…');
  try {
    const data = await _fetchJSON(API);
    if (!host) return;
    if (data && data.gated === true) { _renderGated(host, data); return; }
    if (data && data.engine_available === false) { _renderOffline(host); return; }
    if (!data || data.has_data === false) { _renderEmpty(host); return; }
    _renderResults(host, data);
  } catch (e) {
    if (host) {
      host.innerHTML = errorHTML(errText(e));
      wireRetry(host, () => _load(true));
    }
  } finally {
    _loading = false;
  }
}

export async function openApplicantResults() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  await _load(true);
  // Keep it fresh while open (only while the tab is visible).
  if (_pollStop) _pollStop();
  _pollStop = pollVisible(() => _load(false), 60000);
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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantResultsModule = { openApplicantResults };

// Expose for deep-links / other modules without import coupling.
try { window.applicantResultsModule = applicantResultsModule; } catch { /* no-op */ }
try { window.openApplicantResults = openApplicantResults; } catch { /* no-op */ }

export default applicantResultsModule;
