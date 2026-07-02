// static/js/applicantTracker.js
//
// Tracker — the front-door window onto the engine's post-submission lifecycle
// (design-audit Top-25 #4). ``PostSubmissionService`` already runs the real
// state machine end to end (applied -> awaiting response -> interview/offer
// signals -> rejected / ghosted / archived) with automated rejection-signal
// detection and ghosting sweeps — it just had no front-door surface. This
// module is that surface: a simple board, grouped by where each application
// stands, with a plain "record what happened" affordance so the assistant
// learns from what actually happened even when it never saw the outcome
// itself (an interview invite that arrived by phone, a rejection over a call).
//
// This is the product's "variable reward" surface, so a recorded interview
// invite or offer gets a small, tasteful positive badge — no falling-particle
// celebration effects, no animation, just a warm color and a plain-language
// label. Everything else
// (loading / empty / gated / offline states, the modal chrome) reuses the
// same shared kit and design system as the Results/Activity/Gallery surfaces.
//
// Talks to the engine only through the workspace proxy at
// /api/applicant/tracker (it never reaches the engine directly), creates no
// engine state beyond the explicit "record what happened" write, and degrades
// gracefully: a designed empty state for a brand-new user (nothing submitted
// yet), an honest "finish setup" state when the engine gates the read, and an
// offline note when the engine is unreachable.

import uiModule from './ui.js';
import {
  esc, _fetchJSON, _post, _toast, errText, loadingHTML, emptyHTML, errorHTML,
  gatedHTML, wireRetry, pollVisible,
} from './applicantCore.js';

const API = '/api/applicant/tracker';

let _modalEl = null;
let _modalA11yCleanup = null;
let _pollStop = null;
let _loading = false;
let _busyIds = new Set();

// ── Buckets + manual-outcome options ────────────────────────────────────────

//: §7 status -> the tracker bucket it renders under. Anything not listed here
//: never reaches this surface (the proxy already only forwards tracker rows).
const BUCKETS = [
  { key: 'applied', title: 'Applied', statuses: ['SUBMITTED_BY_USER', 'FINISHED_BY_ENGINE', 'POST_SUBMISSION'] },
  { key: 'awaiting', title: 'Awaiting response', statuses: ['AWAITING_RESPONSE', 'FOLLOWING_UP'] },
  { key: 'rejected', title: 'Not moving forward', statuses: ['REJECTED'] },
  { key: 'ghosted', title: 'Went quiet', statuses: ['GHOSTED'] },
  { key: 'archived', title: 'Archived', statuses: ['ARCHIVED'] },
];

//: Recognized manual outcome types this surface offers (a subset of the
//: engine's OUTCOME_TYPES — "submitted"/"converted" are already how an
//: application arrives here in the first place, not something to record).
const OUTCOME_OPTIONS = [
  { value: 'interview_invited', label: 'Got an interview' },
  { value: 'offer', label: 'Got an offer' },
  { value: 'rejected', label: 'Got rejected' },
  { value: 'ghosted', label: "Haven't heard back" },
];

const SIGNAL_LABEL = { interview_invited: 'Interview', offer: 'Offer' };

function _bucketFor(status) {
  const b = BUCKETS.find((x) => x.statuses.includes(status));
  return b ? b.key : 'awaiting';
}

// ── Modal shell ──────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-tracker-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Tracker');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:680px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Tracker
        </h4>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="cal-btn" id="applicant-tracker-refresh" title="Refresh your tracker">Refresh</button>
          <button class="close-btn" id="applicant-tracker-close" title="Close">✖</button>
        </div>
      </div>
      <div class="modal-body" id="applicant-tracker-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-tracker-close').addEventListener('click', _close);
  modal.querySelector('#applicant-tracker-refresh').addEventListener('click', () => _load(true));
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

function _body() { return _modalEl && _modalEl.querySelector('#applicant-tracker-body'); }

// ── Row + section renderers ─────────────────────────────────────────────────

function _roleLabel(app) {
  return String(app.job_title || app.role_name || 'A role').trim() || 'A role';
}

function _signalBadges(app) {
  const signals = Array.isArray(app.signals) ? app.signals : [];
  return signals.map((s) => {
    const label = SIGNAL_LABEL[s] || s;
    return `<span style="display:inline-block;padding:2px 8px;margin-right:4px;border-radius:10px;font-size:10px;font-weight:600;background:color-mix(in srgb, var(--green,#50fa7b) 18%, transparent);color:var(--green,#1a7f37);">${esc(label)}</span>`;
  }).join('');
}

function _optionsHTML(currentStatus) {
  // Rejected/ghosted/archived applications are already at (or past) that
  // outcome — offering to re-record the same terminal state again is noise.
  const skip = { REJECTED: 'rejected', GHOSTED: 'ghosted' }[currentStatus];
  return OUTCOME_OPTIONS
    .filter((o) => o.value !== skip)
    .map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`)
    .join('');
}

function _renderRow(app) {
  const id = esc(String(app.application_id || ''));
  const campaign = app.campaign_name ? `<span style="opacity:0.5;">· ${esc(app.campaign_name)}</span>` : '';
  const busy = _busyIds.has(String(app.application_id));
  const label = esc(_roleLabel(app));
  return `
    <div class="memory-item ow-list-row" data-tracker-row="${id}" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:8px 4px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12.5px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label} ${campaign}</div>
        <div style="margin-top:3px;">${_signalBadges(app)}</div>
      </div>
      <select class="cal-btn" data-tracker-record="${id}" style="font-size:11px;" ${busy ? 'disabled' : ''} aria-label="Record what happened for ${label}">
        <option value="">Record what happened…</option>
        ${_optionsHTML(app.status)}
      </select>
      ${_scanEmailHTML(id, label)}
    </div>`;
}

// A per-row, collapsed-by-default disclosure so an owner can paste in one
// email (a rejection/interview/offer that arrived by mail and the automated
// detectors never saw) and have it scanned against THIS specific application
// — never an automatic, ambiguous inbox-to-application guess. Uses the native
// <details>/<summary> disclosure (same pattern as the onboarding wizard's
// "What Applicant never does" / "Advanced" sections) so it stays out of the
// way until the owner actually wants it, with zero extra JS for the open/close
// state itself.
function _scanEmailHTML(id, label) {
  return `
    <details class="ow-list-row" data-tracker-scan="${id}" style="flex-basis:100%;margin:2px 0 0;">
      <summary style="cursor:pointer;font-size:11px;opacity:0.7;list-style:revert;">Check an email</summary>
      <div style="margin:8px 0 4px;display:flex;flex-direction:column;gap:6px;">
        <input type="text" class="cal-input" data-scan-subject="${id}" placeholder="Subject (optional)" style="font-size:11px;padding:5px 8px;" aria-label="Email subject for ${label}" />
        <textarea class="cal-input" data-scan-body="${id}" placeholder="Paste the email text here…" rows="3" style="font-size:11px;padding:5px 8px;" aria-label="Email body for ${label}"></textarea>
        <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;">
          <span data-scan-result="${id}" style="font-size:11px;flex:1;min-width:0;"></span>
          <button class="cal-btn" type="button" data-scan-submit="${id}" style="font-size:11px;">Check email</button>
        </div>
      </div>
    </details>`;
}

function _renderBucket(bucket, rows) {
  if (!rows.length) return '';
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:10px 12px;">
      <div style="display:flex;align-items:center;gap:6px;padding:2px 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">${esc(bucket.title)}</span>
        <span style="font-size:9.5px;opacity:0.4;">(${rows.length})</span>
      </div>
      ${rows.map(_renderRow).join('')}
    </div>`;
}

function _renderBoard(host, applications) {
  const grouped = {};
  BUCKETS.forEach((b) => { grouped[b.key] = []; });
  (applications || []).forEach((app) => {
    if (!app || typeof app !== 'object') return;
    grouped[_bucketFor(app.status)].push(app);
  });
  const html = BUCKETS.map((b) => _renderBucket(b, grouped[b.key])).filter(Boolean).join('');
  host.innerHTML = html || emptyHTML(
    'Nothing to track yet',
    'Once your assistant submits an application, it shows up here so you can follow where it stands.',
  );
  host.querySelectorAll('[data-tracker-record]').forEach((select) => {
    select.addEventListener('change', () => _recordOutcome(select));
  });
  host.querySelectorAll('[data-scan-submit]').forEach((btn) => {
    btn.addEventListener('click', () => _scanEmail(btn));
  });
}

// Designed empty state for a brand-new user: reachable engine + a campaign,
// but nothing submitted yet. Same wording as the board's own inline empty
// case so the state reads the same whether the fetch is empty or the board
// itself is.
function _renderEmpty(host) {
  host.innerHTML = emptyHTML(
    'Nothing to track yet',
    'Once your assistant submits an application, it shows up here — applied, awaiting a response, '
    + 'an interview or offer, or a result — so you always know where things stand.',
  );
}

function _renderOffline(host) {
  host.innerHTML = emptyHTML(
    'Tracker is offline',
    'Your tracker will appear here once your assistant is connected and running.',
  );
}

function _renderGated(host, data) {
  const msg = (data && data.message)
    || 'Finish onboarding and connect a model to start tracking your applications.';
  host.innerHTML = gatedHTML(msg);
}

// ── Data flow ────────────────────────────────────────────────────────────────

async function _load(showSpinner) {
  if (_loading) return;
  _loading = true;
  const host = _body();
  if (host && showSpinner) host.innerHTML = loadingHTML('Loading your tracker…');
  try {
    const data = await _fetchJSON(API);
    if (!host) return;
    if (data && data.gated === true) { _renderGated(host, data); return; }
    if (data && data.engine_available === false) { _renderOffline(host); return; }
    if (!data || data.has_data === false) { _renderEmpty(host); return; }
    _renderBoard(host, data.applications);
  } catch (e) {
    if (host) {
      host.innerHTML = errorHTML(errText(e));
      wireRetry(host, () => _load(true));
    }
  } finally {
    _loading = false;
  }
}

async function _recordOutcome(select) {
  const outcomeType = select.value;
  const applicationId = select.getAttribute('data-tracker-record');
  if (!outcomeType || !applicationId) return;
  _busyIds.add(applicationId);
  select.disabled = true;
  try {
    await _post(`${API}/applications/${encodeURIComponent(applicationId)}/outcome`, { outcome_type: outcomeType });
    _toast('Recorded — thanks for letting me know.');
    await _load(false);
  } catch (e) {
    _toast(errText(e));
    select.disabled = false;
  } finally {
    _busyIds.delete(applicationId);
  }
}

// Plain-language labels for what `_scanEmail` may have detected — mirrors the
// engine's own `outcome_type` values (see ScanEmailIn / scan_email in
// post_submission.py) so the toast reads the same language as the "Record
// what happened" dropdown above.
const SCAN_OUTCOME_LABEL = {
  rejected: 'a rejection',
  interview_invited: 'an interview invite',
  offer: 'an offer',
};

// The "Check an email" affordance's submit handler: paste-and-scan ONE email
// against the specific application the owner already picked (the disclosure
// this button lives inside is per-row, so there is never any ambiguity about
// which application it applies to). Shows the plain-language result inline
// and, only when the engine actually recorded something, re-renders the whole
// board so the new signal/bucket shows up immediately — same pattern as
// `_recordOutcome`.
async function _scanEmail(btn) {
  const id = btn.getAttribute('data-scan-submit');
  const details = btn.closest('[data-tracker-scan]');
  if (!id || !details || _busyIds.has(id)) return;
  const subjectEl = details.querySelector('[data-scan-subject]');
  const bodyEl = details.querySelector('[data-scan-body]');
  const resultEl = details.querySelector('[data-scan-result]');
  const subject = subjectEl ? subjectEl.value.trim() : '';
  const body = bodyEl ? bodyEl.value.trim() : '';
  if (!subject && !body) {
    if (resultEl) resultEl.textContent = 'Paste some email text first.';
    return;
  }
  _busyIds.add(id);
  btn.disabled = true;
  if (resultEl) resultEl.textContent = 'Checking…';
  try {
    const data = await _post(`${API}/applications/${encodeURIComponent(id)}/scan-email`, { subject, body });
    if (data && data.detected && data.recorded) {
      const label = SCAN_OUTCOME_LABEL[data.outcome_type] || 'an outcome';
      _toast(`Found ${label} in that email — recorded.`);
      await _load(false);
      return; // the row this button lives on is about to be replaced
    }
    if (resultEl) {
      resultEl.textContent = (data && data.detected)
        ? 'Found some signal, but not confident enough to record automatically — use "Record what happened" above if you know for sure.'
        : "Didn't recognize anything in that email.";
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = errText(e);
  } finally {
    _busyIds.delete(id);
    btn.disabled = false;
  }
}

export async function openApplicantTracker() {
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
  const rail = document.getElementById('rail-tracker');
  if (rail && !rail._applicantTrackerWired) {
    rail._applicantTrackerWired = true;
    rail.addEventListener('click', () => openApplicantTracker());
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
    if (document.getElementById('rail-tracker')?._applicantTrackerWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantTrackerModule = { openApplicantTracker };

// Expose for deep-links / other modules without import coupling.
try { window.applicantTrackerModule = applicantTrackerModule; } catch { /* no-op */ }
try { window.openApplicantTracker = openApplicantTracker; } catch { /* no-op */ }

export default applicantTrackerModule;
