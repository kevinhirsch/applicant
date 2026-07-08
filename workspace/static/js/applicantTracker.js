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
import {
  getActiveCampaignId, filterByCampaign, mountCampaignSwitcher,
} from './applicantCampaignSwitcher.js';

const API = '/api/applicant/tracker';
//: Product-gaps backlog #20 — the reusable screening-answer library lives on
//: the Documents proxy (campaign-scoped), not the tracker's own API base.
const LIBRARY_API = '/api/applicant/documents/screening-answer-library';
//: P1-12 — ghosting flags + drafted (never auto-sent) follow-ups live on the
//: owner-scoped followups proxy (routes/applicant_followups_routes.py), which
//: reads the engine's post-submission attention feed per campaign.
const FOLLOWUPS_API = '/api/applicant/followups';

let _modalEl = null;
let _modalA11yCleanup = null;
let _pollStop = null;
let _loading = false;
let _busyIds = new Set();

// The board's own applications from the last successful load — the email-
// match suggestions (below) score candidates against THIS, never a fresh
// fetch of its own, so "Find responses" always reflects what the owner is
// currently looking at.
let _lastApplications = [];
// Computed candidates from the last "Find responses" run, keyed the same way
// as their card's data-suggestion-key, so a click handler can resolve back
// to the (email, application) pair without re-scanning the DOM.
let _currentCandidates = [];
let _emailMatchLoading = false;

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
  { value: 'ghosted', label: "Haven’t heard back" },
];

const SIGNAL_LABEL = { interview_invited: 'Interview', offer: 'Offer' };

function _bucketFor(status) {
  const b = BUCKETS.find((x) => x.statuses.includes(status));
  return b ? b.key : 'awaiting';
}

//: Plain-language status label for the "View details" drill-down, built from
//: the same bucket titles the board itself groups rows under, so the detail
//: view never introduces a second vocabulary for the same status.
const STATUS_LABEL = {};
BUCKETS.forEach((b) => { b.statuses.forEach((s) => { STATUS_LABEL[s] = b.title; }); });

//: Plain-language labels for the outcome-event timeline in "View details" --
//: distinct from SCAN_OUTCOME_LABEL's article-prefixed phrasing ("a
//: rejection") since these read as a list of past events, not a toast.
const OUTCOME_EVENT_LABEL = {
  submitted: 'Submitted',
  converted: 'Converted',
  interview_invited: 'Interview invited',
  offer: 'Offer received',
  rejected: 'Rejected',
  ghosted: 'Went quiet',
};

function _outcomeEventLabel(type) {
  return OUTCOME_EVENT_LABEL[type] || String(type || '').replace(/_/g, ' ');
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
          <span id="applicant-tracker-campaign" style="display:flex;align-items:center;"></span>
          <button class="cal-btn" id="applicant-tracker-find-emails" title="Look for likely replies in your inbox">Find responses in your inbox</button>
          <button class="cal-btn" id="applicant-tracker-refresh" title="Refresh your tracker">Refresh</button>
          <button class="close-btn" id="applicant-tracker-close" title="Close">✖</button>
        </div>
      </div>
      <div id="applicant-tracker-suggestions" style="display:none;flex-shrink:0;max-height:38vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div id="applicant-tracker-confirm" style="display:none;flex-shrink:0;max-height:32vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div id="applicant-tracker-stuck" style="display:none;flex-shrink:0;max-height:32vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div id="applicant-tracker-blocked" style="display:none;flex-shrink:0;max-height:32vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div id="applicant-tracker-attention" style="display:none;flex-shrink:0;max-height:36vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div class="modal-body" id="applicant-tracker-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-tracker-close').addEventListener('click', _close);
  modal.querySelector('#applicant-tracker-refresh').addEventListener('click', () => { _load(true); _loadPendingConfirmation(); _loadStuck(); _loadBlocked(); });
  const findBtn = modal.querySelector('#applicant-tracker-find-emails');
  findBtn.addEventListener('click', () => _onFindResponses(findBtn));
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

// Easy-Apply channel chip (detection only — the engine tags the posting at
// discovery time when the source board hosts its own quick-apply flow, e.g.
// LinkedIn’s built-in apply). Purely informational on the tracker row.
function _easyApplyChip(app) {
  if (!app || !app.easy_apply) return '';
  return `<span class="applicant-easy-apply-chip" title="This role’s board has a built-in quick-apply flow — usually fewer form steps" style="display:inline-block;padding:2px 8px;margin-right:4px;border-radius:10px;font-size:10px;font-weight:600;background:color-mix(in srgb, var(--color-accent,#00aaff) 16%, transparent);color:var(--color-accent,#0077cc);">Easy Apply</span>`;
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

// Dark-engine audit item 13: "Close / archive" is only offered on rows the
// engine's §7 state machine can actually move to ARCHIVED from (awaiting
// response / following up / rejected / ghosted) -- never straight from the
// just-submitted "Applied" bucket or a row that's already archived. Mirrors
// the exact same bucket check the engine itself enforces server-side
// (``can_transition``), so this never offers a button that would just 409.
function _archivableHTML(id, label) {
  return `<button class="cal-btn" type="button" data-tracker-archive="${id}" title="Close this application out — it stops showing as active" aria-label="Archive ${label}">Close / archive</button>`;
}

function _renderRow(app) {
  const id = esc(String(app.application_id || ''));
  const campaignId = esc(String(app.campaign_id || ''));
  const campaign = app.campaign_name ? `<span style="opacity:0.5;">· ${esc(app.campaign_name)}</span>` : '';
  const busy = _busyIds.has(String(app.application_id));
  const label = esc(_roleLabel(app));
  const signals = Array.isArray(app.signals) ? app.signals : [];
  const bucket = _bucketFor(app.status);
  const archivable = bucket !== 'applied' && bucket !== 'archived';
  return `
    <div class="memory-item ow-list-row" data-tracker-row="${id}" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:8px 4px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12.5px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label} ${campaign}</div>
        <div style="margin-top:3px;">${_easyApplyChip(app)}${_signalBadges(app)}</div>
      </div>
      <select class="cal-btn" data-tracker-record="${id}" style="font-size:11px;" ${busy ? 'disabled' : ''} aria-label="Record what happened for ${label}">
        <option value="">Record what happened…</option>
        ${_optionsHTML(app.status)}
      </select>
      <input type="text" class="cal-input" data-tracker-reason="${id}" placeholder="Reason (optional — used if you mark it rejected)" style="font-size:11px;padding:4px 8px;flex-basis:220px;min-width:160px;" aria-label="Optional reason for ${label}" />
      ${archivable ? _archivableHTML(id, label) : ''}
      ${_scanEmailHTML(id, label)}
      ${_historyHTML(id, label)}
      ${_screeningAnswersHTML(id, campaignId, label)}
      ${signals.includes('interview_invited') ? _interviewPrepHTML(id, label) : ''}
    </div>`;
}

// A per-row, collapsed-by-default disclosure over the drill-down detail
// (status, work mode, screenshot count, outcome timeline) behind this row --
// the same read the admin-only Debug modal's drill-down already surfaces
// (dark-engine audit #25), reached here through the owner-scoped Tracker
// instead of an admin gate. Uses the EXACT same native <details>/<summary>
// disclosure pattern as "Check an email" above -- lazy, loaded only the first
// time the owner actually opens it.
function _historyHTML(id, label) {
  return `
    <details class="ow-list-row" data-tracker-history="${id}" style="flex-basis:100%;margin:2px 0 0;">
      <summary style="cursor:pointer;font-size:11px;opacity:0.7;list-style:revert;">View details</summary>
      <div data-history-body="${id}" style="margin:8px 0 4px;font-size:11px;opacity:0.7;">Loading…</div>
    </details>`;
}

// A per-row, collapsed-by-default disclosure over the reusable screening-
// answer library (product-gaps backlog #20): screening answers generated in
// Documents for THIS campaign are saved there automatically (parallel to the
// résumé variant library, FR-RESUME-6), so a common question ("Why do you
// want to work here?") can be reused for THIS application instead of
// regenerated from scratch. Lazy — the library is only fetched the first time
// an owner actually opens the disclosure, never eagerly for every row.
function _screeningAnswersHTML(id, campaignId, label) {
  return `
    <details class="ow-list-row" data-tracker-screening="${id}" data-screening-campaign="${campaignId}" style="flex-basis:100%;margin:2px 0 0;">
      <summary style="cursor:pointer;font-size:11px;opacity:0.7;list-style:revert;">Screening answers</summary>
      <div data-screening-body="${id}" style="margin:8px 0 4px;font-size:11px;opacity:0.7;">Loading…</div>
    </details>`;
}

// A per-row disclosure that only renders once the row has actually recorded
// an interview_invited signal (product-gaps backlog #30) — never fabricates a
// brief for an application that was never invited to interview; the engine
// enforces that gate independently, this is just the reachable UI for it.
function _interviewPrepHTML(id, label) {
  return `
    <details class="ow-list-row" data-tracker-prep="${id}" style="flex-basis:100%;margin:2px 0 0;">
      <summary style="cursor:pointer;font-size:11px;opacity:0.7;list-style:revert;">Interview prep</summary>
      <div data-prep-body="${id}" style="margin:8px 0 4px;font-size:11px;opacity:0.7;">Loading…</div>
    </details>`;
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
    'Once I submit an application, it shows up here so you can follow where it stands.',
  );
  host.querySelectorAll('[data-tracker-record]').forEach((select) => {
    select.addEventListener('change', () => _recordOutcome(select));
  });
  host.querySelectorAll('[data-tracker-archive]').forEach((btn) => {
    btn.addEventListener('click', () => _archiveApplication(btn));
  });
  host.querySelectorAll('[data-scan-submit]').forEach((btn) => {
    btn.addEventListener('click', () => _scanEmail(btn));
  });
  host.querySelectorAll('[data-tracker-screening]').forEach((details) => {
    details.addEventListener('toggle', () => _onScreeningToggle(details), { once: true });
  });
  host.querySelectorAll('[data-tracker-prep]').forEach((details) => {
    details.addEventListener('toggle', () => _onPrepToggle(details), { once: true });
  });
  host.querySelectorAll('[data-tracker-history]').forEach((details) => {
    details.addEventListener('toggle', () => _onHistoryToggle(details), { once: true });
  });
}

// Designed empty state for a brand-new user: reachable engine + a campaign,
// but nothing submitted yet. Same wording as the board's own inline empty
// case so the state reads the same whether the fetch is empty or the board
// itself is.
function _renderEmpty(host) {
  host.innerHTML = emptyHTML(
    'Nothing to track yet',
    'Once I submit an application, it shows up here — applied, awaiting a response, '
    + 'an interview or offer, or a result — so you always know where things stand.',
  );
}

function _renderOffline(host) {
  host.innerHTML = emptyHTML(
    'Tracker is offline',
    'Your tracker will appear here once I’m connected and running.',
  );
}

function _renderGated(host, data) {
  const msg = (data && data.message)
    || 'Finish onboarding and connect a model to start tracking your applications.';
  host.innerHTML = gatedHTML(msg);
}

// ── Paused applications (dark-engine audit #62) ─────────────────────────────
// After 5 failed resume attempts the engine loop stops re-driving an
// application and fires ONE deduped "needs a look" notification — but nothing
// let an owner SEE the paused application or unstick it short of restarting
// the whole engine process. This is a SEPARATE section from the buckets
// above (it spans applications that never reached a submitted state at all,
// so it can never live inside a per-row "View details" disclosure) — a small
// banner-style panel above the board with a "Retry now" per row that clears
// the engine's give-up flag so the very next tick picks the application back
// up. Loaded independently of the board fetch (own panel element, own
// endpoint) so a paused application still shows even when the board itself is
// empty/gated/offline, and degrades silently (hides itself) on any failure —
// this is a bonus surface, never allowed to blank out the primary tracker.

function _stuckPanelEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-stuck');
}

function _stuckLabel(app) {
  const role = String(app.job_title || app.role_name || 'A role').trim() || 'A role';
  const company = app.company ? ` at ${app.company}` : '';
  return `${role}${company}`;
}

function _renderStuckRow(app) {
  const id = esc(String(app.application_id || ''));
  const label = esc(_stuckLabel(app));
  const failures = Number(app.failures || 0) || 0;
  const busy = _busyIds.has(String(app.application_id));
  return `
    <div class="memory-item ow-list-row" data-stuck-row="${id}" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:6px 4px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label}</div>
        <div style="margin-top:2px;font-size:10.5px;opacity:0.65;">I couldn’t resume this after ${esc(String(failures))} tries and paused work on it.</div>
      </div>
      <button class="cal-btn" type="button" data-stuck-retry="${id}" ${busy ? 'disabled' : ''} aria-label="Retry ${label}">Retry now</button>
    </div>`;
}

function _renderStuckPanel(rows) {
  return `
    <div style="padding:8px 10px;">
      <div style="display:flex;align-items:center;gap:6px;padding:2px 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.6;color:var(--red,#e5484d);">Needs a look</span>
        <span style="font-size:9.5px;opacity:0.4;">(${rows.length})</span>
      </div>
      ${rows.map(_renderStuckRow).join('')}
    </div>`;
}

async function _loadStuck() {
  const panel = _stuckPanelEl();
  if (!panel) return;
  try {
    const data = await _fetchJSON(`${API}/stuck`);
    const rows = Array.isArray(data && data.applications) ? data.applications : [];
    if (!rows.length) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      return;
    }
    panel.style.display = 'block';
    panel.innerHTML = _renderStuckPanel(rows);
    panel.querySelectorAll('[data-stuck-retry]').forEach((btn) => {
      btn.addEventListener('click', () => _retryStuck(btn));
    });
  } catch {
    // Bonus surface — never show an error banner over the primary tracker;
    // just hide the panel and try again on the next refresh/poll.
    panel.style.display = 'none';
    panel.innerHTML = '';
  }
}

async function _retryStuck(btn) {
  const id = btn.getAttribute('data-stuck-retry');
  if (!id || _busyIds.has(id)) return;
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Retrying…';
  try {
    await _post(`${API}/applications/${encodeURIComponent(id)}/retry`, {});
    _toast("Retrying — I’ll pick this back up on my next pass.");
    await _loadStuck();
  } catch (e) {
    _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
  }
}

// ── Blocked applications (dark-engine audit #61) ────────────────────────────
// G07's pre-submit safety checks (scam/ghost-job, duplicate cooldown,
// per-company volume cap, eligibility/work-authorization) run every tick
// against every APPROVED application — until now a block left the posting
// APPROVED forever with nothing an owner could see or act on. This is a
// SEPARATE panel from "Needs a look" above: a blocked application never even
// started the pipeline (it's still sitting APPROVED), so it is a distinct
// condition from a paused/given-up one. Loaded independently of the board
// fetch (own panel element, own endpoint) so it still shows even when the
// board itself is empty/gated/offline, and degrades silently (hides itself)
// on any failure — this is a bonus surface, never allowed to blank out the
// primary tracker.

function _blockedPanelEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-blocked');
}

function _blockedLabel(app) {
  const role = String(app.job_title || app.role_name || 'A role').trim() || 'A role';
  const company = app.company ? ` at ${app.company}` : '';
  return `${role}${company}`;
}

function _renderBlockedRow(app) {
  const id = esc(String(app.application_id || ''));
  const label = esc(_blockedLabel(app));
  const reason = esc(String(app.reason || 'A safety check stopped this application.'));
  const times = Number(app.times_blocked || 0) || 0;
  const timesText = times > 1 ? ` (checked ${esc(String(times))} times)` : '';
  const busy = _busyIds.has(String(app.application_id));
  return `
    <div class="memory-item ow-list-row" data-blocked-row="${id}" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:6px 4px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label}</div>
        <div style="margin-top:2px;font-size:10.5px;opacity:0.65;">${reason}${timesText}</div>
      </div>
      <button class="cal-btn" type="button" data-blocked-override="${id}" ${busy ? 'disabled' : ''} title="Start this application anyway, despite the safety flag" aria-label="Proceed anyway with ${label}">Proceed anyway</button>
    </div>`;
}

function _renderBlockedPanel(rows) {
  return `
    <div style="padding:8px 10px;">
      <div style="display:flex;align-items:center;gap:6px;padding:2px 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.6;color:var(--red,#e5484d);">Blocked by a safety check</span>
        <span style="font-size:9.5px;opacity:0.4;">(${rows.length})</span>
      </div>
      ${rows.map(_renderBlockedRow).join('')}
    </div>`;
}

async function _loadBlocked() {
  const panel = _blockedPanelEl();
  if (!panel) return;
  try {
    const data = await _fetchJSON(`${API}/blocked`);
    const rows = Array.isArray(data && data.applications) ? data.applications : [];
    if (!rows.length) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      return;
    }
    panel.style.display = 'block';
    panel.innerHTML = _renderBlockedPanel(rows);
    panel.querySelectorAll('[data-blocked-override]').forEach((btn) => {
      btn.addEventListener('click', () => _overrideBlocked(btn));
    });
  } catch {
    // Bonus surface — never show an error banner over the primary tracker;
    // just hide the panel and try again on the next refresh/poll.
    panel.style.display = 'none';
    panel.innerHTML = '';
  }
}

async function _overrideBlocked(btn) {
  const id = btn.getAttribute('data-blocked-override');
  if (!id || _busyIds.has(id)) return;
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Starting…';
  try {
    await _post(`${API}/applications/${encodeURIComponent(id)}/override-block`, {});
    _toast('Got it — I’ll start this application on my next pass.');
    await _loadBlocked();
  } catch (e) {
    _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
  }
}

// ── Needs your confirmation (dark-engine audit item 14) ─────────────────────
// The engine's one-tap "mark as submitted" / auto-detect pair existed but was
// reachable only behind an admin gate (the Debug modal) — an owner who
// finished an application by hand (or in a live takeover session the
// automated detector never confirmed) had no way to tell Applicant "yes, I
// submitted that" so it could start tracking it and teach the learning loop.
// A SEPARATE panel from "Needs a look" above: these applications are parked
// at the final-approval gate or an emergency hand-off — a genuinely earlier
// §7 state than anything the tracker board itself lists — so this is its own
// fan-out, loaded independently, degrading silently on any failure (a bonus
// surface, never allowed to blank out the primary tracker).

function _confirmPanelEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-confirm');
}

function _confirmLabel(app) {
  return String(app.job_title || app.role_name || 'A role').trim() || 'A role';
}

function _renderConfirmRow(app) {
  const id = esc(String(app.application_id || ''));
  const label = esc(_confirmLabel(app));
  const busy = _busyIds.has(String(app.application_id));
  return `
    <div class="memory-item ow-list-row" data-confirm-row="${id}" style="display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:6px 4px;">
      <div style="flex:1;min-width:0;">
        <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${label}</div>
        <div style="margin-top:2px;font-size:10.5px;opacity:0.65;">Waiting to hear whether this was actually submitted.</div>
      </div>
      <button class="cal-btn" type="button" data-confirm-detect="${id}" ${busy ? 'disabled' : ''} title="Ask me to check the live session for a confirmation page" aria-label="Try auto-detect for ${label}">Try auto-detect</button>
      <button class="cal-btn" type="button" data-confirm-submitted="${id}" ${busy ? 'disabled' : ''} aria-label="Mark ${label} as submitted">I submitted this</button>
    </div>`;
}

function _renderConfirmPanel(rows) {
  return `
    <div style="padding:8px 10px;">
      <div style="display:flex;align-items:center;gap:6px;padding:2px 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.6;">Needs your confirmation</span>
        <span style="font-size:9.5px;opacity:0.4;">(${rows.length})</span>
      </div>
      ${rows.map(_renderConfirmRow).join('')}
    </div>`;
}

async function _loadPendingConfirmation() {
  const panel = _confirmPanelEl();
  if (!panel) return;
  try {
    const data = await _fetchJSON(`${API}/pending-confirmation`);
    const rows = Array.isArray(data && data.applications) ? data.applications : [];
    if (!rows.length) {
      panel.style.display = 'none';
      panel.innerHTML = '';
      return;
    }
    panel.style.display = 'block';
    panel.innerHTML = _renderConfirmPanel(rows);
    panel.querySelectorAll('[data-confirm-detect]').forEach((btn) => {
      btn.addEventListener('click', () => _onDetectSubmission(btn));
    });
    panel.querySelectorAll('[data-confirm-submitted]').forEach((btn) => {
      btn.addEventListener('click', () => _onMarkSubmitted(btn));
    });
  } catch {
    // Bonus surface — never show an error banner over the primary tracker;
    // just hide the panel and try again on the next refresh/poll.
    panel.style.display = 'none';
    panel.innerHTML = '';
  }
}

async function _onMarkSubmitted(btn) {
  const id = btn.getAttribute('data-confirm-submitted');
  if (!id || _busyIds.has(id)) return;
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Recording…';
  try {
    await _post(`${API}/applications/${encodeURIComponent(id)}/mark-submitted`, {});
    _toast('Recorded — this will show up on your tracker.');
    await Promise.all([_loadPendingConfirmation(), _load(false)]);
  } catch (e) {
    _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
  }
}

async function _onDetectSubmission(btn) {
  const id = btn.getAttribute('data-confirm-detect');
  if (!id || _busyIds.has(id)) return;
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Checking…';
  try {
    const data = await _post(`${API}/applications/${encodeURIComponent(id)}/detect-submission`, {});
    if (data && data.detected) {
      _toast('Confirmed — this will show up on your tracker.');
      await Promise.all([_loadPendingConfirmation(), _load(false)]);
    } else {
      _toast("Couldn’t confirm it automatically — use \"I submitted this\" if you know for sure.");
      btn.disabled = false;
      btn.textContent = origLabel;
    }
  } catch (e) {
    _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
  }
}

// ── Follow-ups & quiet applications (P1-12 — the narrative home for the ─────
// engine's ghosting detection + follow-up drafting). The scheduler's daily
// post-submission sweep already flags applications gone silent past the SLA
// and DRAFTS (never sends) a follow-up for each one still awaiting a response
// past the follow-up window — both were reachable only as generic Portal
// pending actions. This panel surfaces them per-application right on the
// Tracker, where the owner is already looking at "where does each application
// stand": each drafted follow-up shows its full subject/body for review
// (editable before approving), and approving schedules it through the SAME
// owner-approval-only proxy path (`POST /api/applicant/followups/applications/
// {id}/approve` — the ONLY route in the product that can queue a follow-up
// for sending; the engine never sends one on its own). Ghosting flags render
// as honest, informational rows — the board's "Went quiet" bucket below keeps
// the status itself. Loaded off the board's own campaign ids (a follow-up
// only ever exists for a tracked application), degrades silently (hides
// itself) on any failure — a bonus surface, never allowed to blank out the
// primary tracker.

function _attentionPanelEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-attention');
}

function _attentionCampaignIds() {
  // Fan out ONLY over the campaigns the board itself is currently showing:
  // the SAME shared campaign filter _renderFiltered renders through
  // (filterByCampaign over the shared switcher's selection), so the panel
  // can never surface follow-ups/ghosting rows from a search the board
  // below is hiding.
  const ids = new Set();
  filterByCampaign(_lastApplications || []).forEach((app) => {
    if (app && app.campaign_id) ids.add(String(app.campaign_id));
  });
  return Array.from(ids);
}

function _renderGhostRow(item) {
  const title = esc(String(item.title || 'An application looks like it went quiet'));
  const payload = (item.payload && typeof item.payload === 'object') ? item.payload : {};
  const age = Number(payload.submission_age_days);
  const meta = Number.isFinite(age) && age > 0
    ? `No response in ${age} day${age === 1 ? '' : 's'} — I’ve marked it “Went quiet” below.`
    : 'No response for a while — I’ve marked it “Went quiet” below.';
  return `
    <div class="memory-item ow-list-row" data-attention-ghost="${esc(String(item.application_id || ''))}" style="display:block;padding:6px 4px;">
      <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${title}</div>
      <div style="margin-top:2px;font-size:10.5px;opacity:0.65;">${esc(meta)}</div>
    </div>`;
}

function _renderFollowupRow(item) {
  const id = esc(String(item.application_id || ''));
  const title = esc(String(item.title || 'A follow-up is drafted for your review'));
  const payload = (item.payload && typeof item.payload === 'object') ? item.payload : {};
  const subject = esc(String(payload.subject || ''));
  const body = esc(String(payload.body || ''));
  const days = Number(payload.days_since_submission);
  const meta = Number.isFinite(days) && days > 0
    ? `Drafted after ${days} day${days === 1 ? '' : 's'} without a response. I never send one without your OK.`
    : 'Drafted for you — I never send one without your OK.';
  const busy = _busyIds.has(String(item.application_id));
  return `
    <div class="memory-item ow-list-row" data-attention-followup="${id}" style="display:block;padding:6px 4px;">
      <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${title}</div>
      <div style="margin-top:2px;font-size:10.5px;opacity:0.65;">${esc(meta)}</div>
      <details class="ow-list-row" style="margin:4px 0 0;">
        <summary style="cursor:pointer;font-size:11px;opacity:0.7;list-style:revert;">Review &amp; send</summary>
        <div style="margin:8px 0 4px;display:flex;flex-direction:column;gap:6px;">
          <input type="text" class="cal-input" data-followup-subject="${id}" value="${subject}" style="font-size:11px;padding:5px 8px;" aria-label="Follow-up subject" />
          <textarea class="cal-input" data-followup-body="${id}" rows="5" style="font-size:11px;padding:5px 8px;" aria-label="Follow-up message">${body}</textarea>
          <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;">
            <span data-followup-result="${id}" style="font-size:11px;flex:1;min-width:0;"></span>
            <button class="cal-btn" type="button" data-followup-approve="${id}" ${busy ? 'disabled' : ''} title="Approve this follow-up — I’ll send it for you after a short delay">Approve &amp; send</button>
          </div>
        </div>
      </details>
    </div>`;
}

function _renderAttentionPanel(followups, ghosted) {
  const sections = [];
  if (followups.length) {
    sections.push(`
      <div style="display:flex;align-items:center;gap:6px;padding:2px 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.6;">Follow-ups ready for your review</span>
        <span style="font-size:9.5px;opacity:0.4;">(${followups.length})</span>
      </div>
      ${followups.map(_renderFollowupRow).join('')}`);
  }
  if (ghosted.length) {
    sections.push(`
      <div style="display:flex;align-items:center;gap:6px;padding:${followups.length ? '8px' : '2px'} 0 6px;">
        <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.6;">Gone quiet</span>
        <span style="font-size:9.5px;opacity:0.4;">(${ghosted.length})</span>
      </div>
      ${ghosted.map(_renderGhostRow).join('')}`);
  }
  return `<div style="padding:8px 10px;">${sections.join('')}</div>`;
}

async function _loadAttention() {
  const panel = _attentionPanelEl();
  if (!panel) return;
  const campaignIds = _attentionCampaignIds();
  if (!campaignIds.length) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    return;
  }
  const followups = [];
  const ghosted = [];
  try {
    const results = await Promise.all(campaignIds.map(async (cid) => {
      try {
        return await _fetchJSON(`${FOLLOWUPS_API}/${encodeURIComponent(cid)}`);
      } catch {
        return null; // one unreadable campaign never blanks the whole panel
      }
    }));
    results.forEach((data) => {
      if (!data || data.engine_available === false || data.gated === true) return;
      (Array.isArray(data.followups_due) ? data.followups_due : []).forEach((it) => {
        if (it && it.application_id) followups.push(it);
      });
      (Array.isArray(data.ghosted) ? data.ghosted : []).forEach((it) => {
        if (it && typeof it === 'object') ghosted.push(it);
      });
    });
  } catch {
    // Bonus surface — never show an error banner over the primary tracker.
  }
  if (!followups.length && !ghosted.length) {
    panel.style.display = 'none';
    panel.innerHTML = '';
    return;
  }
  panel.style.display = 'block';
  panel.innerHTML = _renderAttentionPanel(followups, ghosted);
  panel.querySelectorAll('[data-followup-approve]').forEach((btn) => {
    btn.addEventListener('click', () => _approveFollowUp(btn));
  });
}

async function _approveFollowUp(btn) {
  const id = btn.getAttribute('data-followup-approve');
  if (!id || _busyIds.has(id)) return;
  const panel = _attentionPanelEl();
  const row = btn.closest('[data-attention-followup]');
  const subjectEl = row && row.querySelector(`[data-followup-subject="${CSS.escape(id)}"]`);
  const bodyEl = row && row.querySelector(`[data-followup-body="${CSS.escape(id)}"]`);
  const resultEl = row && row.querySelector(`[data-followup-result="${CSS.escape(id)}"]`);
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Scheduling…';
  try {
    const payload = {};
    if (subjectEl) payload.subject = subjectEl.value;
    if (bodyEl) payload.body = bodyEl.value;
    await _post(`${FOLLOWUPS_API}/applications/${encodeURIComponent(id)}/approve`, payload);
    _toast('Approved — I’ll send this follow-up for you after a short delay.');
    _busyIds.delete(id);
    await _loadAttention();
    return; // the row this button lives on was just re-rendered/removed
  } catch (e) {
    if (resultEl) resultEl.textContent = errText(e); else _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
    if (panel && !panel.innerHTML) panel.style.display = 'none';
  }
}

// ── Data flow ────────────────────────────────────────────────────────────────

// P1-10: the shared campaign switcher in the header — rendered only when the
// owner has 2+ searches (the slot stays empty otherwise). Fire-and-forget so
// a slow campaigns read never delays the board.
async function _mountSwitcher() {
  const slot = _modalEl && _modalEl.querySelector('#applicant-tracker-campaign');
  if (!slot) return;
  try { await mountCampaignSwitcher(slot); } catch { /* best-effort only */ }
}

// Re-filter the already-loaded board when the shared campaign selection
// changes — same rows, new lens, no second fetch.
window.addEventListener('applicant-campaign-change', () => {
  if (!_modalEl || _modalEl.classList.contains('hidden')) return;
  const host = _body();
  if (host && _lastApplications.length) _renderFiltered(host);
  // The attention panel fans out over the SAME filtered campaign ids the
  // board renders through — refresh it under the new lens too, so it never
  // contradicts the board below (fire-and-forget; hides itself on failure).
  _loadAttention();
});

// Renders the board through the shared campaign filter. When the filter
// empties a non-empty board, say so honestly (the applications exist — they
// belong to another search) instead of the brand-new-user empty state.
function _renderFiltered(host) {
  const rows = filterByCampaign(_lastApplications);
  if (!rows.length && _lastApplications.length && getActiveCampaignId()) {
    host.innerHTML = emptyHTML(
      'Nothing in this search yet',
      'This job search has no tracked applications so far — switch to “All searches” to see everything.',
    );
    return;
  }
  _renderBoard(host, rows);
}

async function _load(showSpinner) {
  if (_loading) return;
  _loading = true;
  _mountSwitcher();
  const host = _body();
  if (host && showSpinner) host.innerHTML = loadingHTML('Loading your tracker…');
  try {
    const data = await _fetchJSON(API);
    _lastApplications = Array.isArray(data && data.applications) ? data.applications : [];
    // P1-12: the follow-ups / gone-quiet panel keys off the board's own
    // campaign ids, so it (re)loads whenever the board itself does —
    // fire-and-forget, it hides itself on any failure.
    _loadAttention();
    if (!host) return;
    if (data && data.gated === true) { _renderGated(host, data); return; }
    if (data && data.engine_available === false) { _renderOffline(host); return; }
    if (!data || data.has_data === false) { _renderEmpty(host); return; }
    _renderFiltered(host);
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
  if (!outcomeType || !applicationId || _busyIds.has(applicationId)) return;
  // Dark-engine audit item 11: the optional free-text reason input sits next
  // to the select on the SAME row -- only meaningful (and only forwarded)
  // when the owner is recording a rejection, so it never sends noise for the
  // other outcome types.
  const row = select.closest('[data-tracker-row]');
  const reasonEl = row ? row.querySelector(`[data-tracker-reason="${CSS.escape(applicationId)}"]`) : null;
  const reason = (outcomeType === 'rejected' && reasonEl) ? reasonEl.value.trim() : '';
  _busyIds.add(applicationId);
  select.disabled = true;
  try {
    const body = { outcome_type: outcomeType };
    if (reason) body.reason = reason;
    await _post(`${API}/applications/${encodeURIComponent(applicationId)}/outcome`, body);
    _toast('Recorded — thanks for letting me know.');
    await _load(false);
  } catch (e) {
    _toast(errText(e));
    select.disabled = false;
  } finally {
    _busyIds.delete(applicationId);
  }
}

// Dark-engine audit item 13: close out a dead application so it stops
// showing as active in every future tracker view. The engine independently
// re-checks the §7 transition is legal (409 when the row somehow isn't
// archivable anymore, e.g. a concurrent update) -- this button is only ever
// rendered for a row _renderRow already knows is in an archivable bucket.
async function _archiveApplication(btn) {
  const id = btn.getAttribute('data-tracker-archive');
  if (!id || _busyIds.has(id)) return;
  _busyIds.add(id);
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = 'Archiving…';
  try {
    await _post(`${API}/applications/${encodeURIComponent(id)}/archive`, {});
    _toast('Archived — it will no longer show as active.');
    await _load(false);
  } catch (e) {
    _toast(errText(e));
    btn.disabled = false;
    btn.textContent = origLabel;
  } finally {
    _busyIds.delete(id);
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
        : "Didn’t recognize anything in that email.";
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = errText(e);
  } finally {
    _busyIds.delete(id);
    btn.disabled = false;
  }
}

// ── "Find responses in your inbox" — suggest, never auto-record ────────────
// (design-audit Top-25 #5, phase 3 / systemic theme #3, round 2). Phase 2
// above already made "close the loop" reachable but left it a manual
// copy-paste chore: the owner had to remember which application an email was
// about and go paste it in themselves. Automatic inbox->application matching
// was deliberately deferred (a mis-attribution risks recording a fake
// outcome against the wrong application) — this is the safe resolution:
// SUGGEST candidates, computed entirely client-side from data already on
// screen, and NEVER record anything without an explicit "Yes, check it"
// click. That click still runs through the exact same
// `${API}/applications/{id}/scan-email` proxy call as `_scanEmail` above, so
// the engine — not this matching heuristic — is what actually classifies and
// records an outcome; a wrong guess here can only ever produce a wrong
// SUGGESTION, never a wrong RECORDED outcome, because the engine's own
// detectors still have to find a confident signal in the real email body
// before `recorded` comes back true.
//
// Scoring note: the tracker board has no dedicated "company" field (the
// engine's ``Application``/tracker-row shape only carries `job_title` /
// `role_name` / `campaign_name` — see `PostSubmissionService.list_tracker_
// rows`; campaigns default to generic names like "My job search"). So the
// "company-name token overlap" this affordance is built around runs against
// the best identifying text actually reachable here — the application's own
// title/role/campaign strings — after stripping generic job-posting/email
// boilerplate words. That keeps the heuristic honest about what it can see;
// it does not change the safety property above, since even a bad guess is
// just a dismissable suggestion.

// Generic job-posting / recruiting-email vocabulary that would otherwise
// produce noisy "matches" on almost every email (e.g. every tracked role
// probably has "engineer" in it, and every recruiting email has "team" or
// "application" in it) — stripped before scoring so a surfaced match reflects
// something actually distinctive, not just shared boilerplate.
const _MATCH_STOPWORDS = new Set([
  'the', 'and', 'for', 'from', 'with', 'your', 'you', 'our', 'about', 'application', 'applications',
  'applicant', 'applying', 'apply', 'job', 'jobs', 'role', 'roles', 'position', 'positions', 'career',
  'careers', 'team', 'teams', 'company', 'companies', 'inc', 'llc', 'corp', 'corporation', 'ltd',
  'group', 'talent', 'recruiting', 'recruitment', 'recruiter', 'hiring', 'human', 'resources',
  'notification', 'notifications', 'update', 'updates', 'status', 'thanks', 'thank', 'regarding',
  'next', 'steps', 'engineer', 'engineering', 'developer', 'development', 'senior', 'junior', 'lead',
  'management', 'manager', 'director', 'associate', 'specialist', 'analyst', 'intern', 'internship',
  'contract', 'remote', 'hybrid', 'onsite', 'full', 'part', 'time', 'software', 'backend', 'frontend',
  'stack', 'product', 'staff', 'principal', 'new', 'opening', 'openings', 'opportunity',
  'opportunities', 'candidate', 'candidates', 'reply', 'noreply', 'support', 'info', 'mail', 'email',
  'search', 'searching', 'find', 'finding',
]);

// Personal-webmail domains never carry a company identity, so a hit there
// (the display name might still match, the domain never should) is excluded.
const _WEBMAIL_DOMAINS = new Set([
  'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com', 'aol.com',
  'protonmail.com', 'live.com', 'msn.com', 'me.com',
]);

function _matchTokenize(text) {
  return String(text || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 4 && !/^\d+$/.test(t) && !_MATCH_STOPWORDS.has(t));
}

function _appMatchTokens(app) {
  const text = [app && app.job_title, app && app.role_name, app && app.campaign_name]
    .filter(Boolean).join(' ');
  return new Set(_matchTokenize(text));
}

function _emailSenderMatchTokens(email) {
  const name = (email && email.from_name) || '';
  const addr = String((email && email.from_address) || '');
  const domain = addr.includes('@') ? addr.split('@')[1].toLowerCase() : '';
  const domainTokens = _WEBMAIL_DOMAINS.has(domain)
    ? []
    : _matchTokenize(domain.replace(/\.[a-z]{2,}$/i, ''));
  return new Set([..._matchTokenize(name), ...domainTokens]);
}

function _emailSubjectMatchTokens(email) {
  return new Set(_matchTokenize((email && email.subject) || ''));
}

// Score ONE (email, application) pair. A sender-name/domain hit is the
// strongest signal (an email FROM something that shares a distinctive word
// with the tracked role/campaign) and alone clears the bar; a subject-only
// hit also clears it (many ATS systems send from generic ATS domains like
// myworkday.com/greenhouse.io but put the identifying text in the subject
// line), since the stopword filtering above already keeps either signal
// "real, non-trivial" rather than a boilerplate coincidence.
function _scoreEmailAgainstApplication(email, app) {
  const appToks = _appMatchTokens(app);
  if (!appToks.size) return { score: 0, senderHit: null, subjectHit: null };
  const senderToks = _emailSenderMatchTokens(email);
  const subjectToks = _emailSubjectMatchTokens(email);
  let senderHit = null;
  let subjectHit = null;
  for (const t of appToks) {
    if (!senderHit && senderToks.has(t)) senderHit = t;
    if (!subjectHit && subjectToks.has(t)) subjectHit = t;
    if (senderHit && subjectHit) break;
  }
  let score = 0;
  if (senderHit) score += 2;
  if (subjectHit) score += 1;
  return { score, senderHit, subjectHit };
}

// The single best-matching application for one email, or null when there is
// no real hit OR when two+ applications tie for the top score (an ambiguous
// tie is never guessed at — see the module doc-comment above).
function _bestApplicationForEmail(email, applications) {
  let best = null;
  let tie = false;
  (applications || []).forEach((app) => {
    if (!app || !app.application_id) return;
    const { score, senderHit, subjectHit } = _scoreEmailAgainstApplication(email, app);
    if (score <= 0) return;
    if (!best || score > best.score) {
      best = { app, score, senderHit, subjectHit };
      tie = false;
    } else if (score === best.score && String(app.application_id) !== String(best.app.application_id)) {
      tie = true;
    }
  });
  return tie ? null : best;
}

// Cheap, subject-only, purely-cosmetic hint (never used for scoring/matching
// or for any recording decision — only to color the suggestion card's own
// copy). The engine's real detectors run on the full email body, only after
// the owner explicitly confirms.
const _HINT_PATTERNS = [
  { type: 'interview_invited', re: /\b(interview|phone screen|schedule a call|meet the team)\b/i },
  { type: 'offer', re: /\b(offer|welcome to the team|congratulations)\b/i },
  { type: 'rejected', re: /\b(unfortunately|not moving forward|other candidates|regret to inform|not selected)\b/i },
];

function _cheapSubjectHint(subject) {
  const s = String(subject || '');
  for (const { type, re } of _HINT_PATTERNS) {
    if (re.test(s)) return type;
  }
  return null;
}

function _dismissKey(uid, applicationId) {
  return `${uid}::${applicationId}`;
}

const DISMISSED_MATCHES_KEY = 'applicant_tracker_dismissed_email_matches';

function _loadDismissedMatches() {
  try {
    const raw = localStorage.getItem(DISMISSED_MATCHES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch { return new Set(); }
}

function _rememberDismissedMatch(key) {
  try {
    const set = _loadDismissedMatches();
    set.add(key);
    // Cap so this never grows unbounded across a long-lived session.
    const arr = Array.from(set).slice(-300);
    localStorage.setItem(DISMISSED_MATCHES_KEY, JSON.stringify(arr));
  } catch { /* no-op — worst case a suggestion re-appears once more */ }
}

function _emailAcctParam() {
  try {
    return window.__applicantActiveEmailAccount
      ? `&account_id=${encodeURIComponent(window.__applicantActiveEmailAccount)}`
      : '';
  } catch { return ''; }
}

// Best-effort plain text out of the native email detail response — prefers
// the plain-text body; falls back to stripping tags out of the HTML body
// (the engine's keyword detectors want text, not markup).
function _plainTextFromEmailDetail(data) {
  if (data && typeof data.body === 'string' && data.body.trim()) return data.body;
  if (data && typeof data.body_html === 'string' && data.body_html.trim()) {
    try {
      const tmp = document.createElement('div');
      tmp.innerHTML = data.body_html;
      return tmp.textContent || '';
    } catch { /* fall through */ }
  }
  return '';
}

function _suggestionsPanelEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-suggestions');
}

function _suggestionsListEl() {
  return _modalEl && _modalEl.querySelector('#applicant-tracker-suggestions-list');
}

function _renderSuggestionCard(candidate) {
  const { key, email, app } = candidate;
  const sender = esc(email.from_name || email.from_address || 'someone');
  const subject = esc(email.subject || '(no subject)');
  const company = esc(app.campaign_name || _roleLabel(app));
  const hint = _cheapSubjectHint(email.subject);
  const hintText = hint ? ` It might be ${esc(SCAN_OUTCOME_LABEL[hint] || 'a response')}.` : '';
  return `
    <div class="memory-item ow-list-row" data-suggestion-key="${esc(key)}" style="padding:8px 10px;">
      <div style="font-size:12px;">This email from <strong>${sender}</strong> — "${subject}" — looks like it might be
        about your application to <strong>${company}</strong>. Is it?${hintText}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:6px;justify-content:flex-end;">
        <span data-suggestion-result="${esc(key)}" style="font-size:11px;flex:1;min-width:0;"></span>
        <button class="cal-btn" type="button" data-suggestion-dismiss="${esc(key)}">No / dismiss</button>
        <button class="cal-btn" type="button" data-suggestion-confirm="${esc(key)}">Yes, check it</button>
      </div>
    </div>`;
}

function _renderSuggestionsList(candidates) {
  const list = _suggestionsListEl();
  if (!list) return;
  if (!candidates.length) {
    list.innerHTML = `<div style="padding:8px 10px;font-size:11px;opacity:0.65;">`
      + `No likely responses found in your inbox right now.</div>`;
    return;
  }
  list.innerHTML = candidates.map(_renderSuggestionCard).join('');
  list.querySelectorAll('[data-suggestion-confirm]').forEach((btn) => {
    btn.addEventListener('click', () => _onSuggestionConfirm(btn));
  });
  list.querySelectorAll('[data-suggestion-dismiss]').forEach((btn) => {
    btn.addEventListener('click', () => _onSuggestionDismiss(btn));
  });
}

function _openSuggestionsPanel() {
  const panel = _suggestionsPanelEl();
  if (!panel) return null;
  panel.style.display = 'block';
  panel.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;">
      <span style="font-size:9.5px;letter-spacing:0.04em;text-transform:uppercase;opacity:0.55;">Possible responses in your inbox</span>
      <button class="cal-btn" type="button" id="applicant-tracker-suggestions-hide" style="font-size:10.5px;">Hide</button>
    </div>
    <div id="applicant-tracker-suggestions-list"></div>`;
  const hideBtn = panel.querySelector('#applicant-tracker-suggestions-hide');
  if (hideBtn) hideBtn.addEventListener('click', () => { panel.style.display = 'none'; });
  return panel;
}

// The "Find responses in your inbox" click handler: reads the native email
// inbox (read-only — never marks anything read/unread, never opens an
// email) plus the board already on screen, scores candidates client-side,
// and renders them as dismissable suggestion cards. Degrades to the SAME
// graceful empty state whether the inbox has no likely matches or the email
// feature isn't reachable at all — this affordance never surfaces an error.
async function _onFindResponses(btn) {
  if (_emailMatchLoading) return;
  _emailMatchLoading = true;
  const origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Searching…';
  const panel = _openSuggestionsPanel();
  if (panel) {
    const list = _suggestionsListEl();
    if (list) list.innerHTML = loadingHTML('Checking your inbox…');
  }
  let candidates = [];
  try {
    const data = await _fetchJSON(`/api/email/list?folder=INBOX&limit=50${_emailAcctParam()}`);
    if (data && !data.error) {
      const emails = Array.isArray(data.emails) ? data.emails : [];
      const dismissed = _loadDismissedMatches();
      const applications = _lastApplications || [];
      emails.forEach((email) => {
        if (!email || email.uid == null) return;
        const best = _bestApplicationForEmail(email, applications);
        if (!best) return;
        const key = _dismissKey(email.uid, best.app.application_id);
        if (dismissed.has(key)) return;
        candidates.push({ key, email, app: best.app, score: best.score });
      });
      candidates.sort((a, b) => b.score - a.score);
    }
  } catch {
    // No inbox access / email feature not configured / network hiccup — the
    // affordance degrades silently to the same empty state as "no matches".
    candidates = [];
  }
  _currentCandidates = candidates;
  _renderSuggestionsList(candidates);
  _emailMatchLoading = false;
  btn.disabled = false;
  btn.textContent = origLabel;
}

function _removeSuggestionCard(key) {
  _currentCandidates = (_currentCandidates || []).filter((c) => c.key !== key);
  const list = _suggestionsListEl();
  const card = list && list.querySelector(`[data-suggestion-key="${CSS.escape(key)}"]`);
  if (card) card.remove();
  if (list && !(_currentCandidates || []).length) {
    list.innerHTML = `<div style="padding:8px 10px;font-size:11px;opacity:0.65;">`
      + `No likely responses found in your inbox right now.</div>`;
  }
}

function _onSuggestionDismiss(btn) {
  const key = btn.getAttribute('data-suggestion-dismiss');
  if (!key) return;
  _rememberDismissedMatch(key);
  _removeSuggestionCard(key);
}

// The ONLY path in this whole affordance that can lead to a recorded
// outcome: the owner explicitly clicked "Yes, check it" on a specific
// suggestion card. Fetches that ONE email's full body (the list endpoint
// above never returns bodies), then posts through the EXACT SAME
// `${API}/applications/{id}/scan-email` proxy call `_scanEmail` above uses —
// the engine's own detectors still decide whether anything gets recorded.
async function _onSuggestionConfirm(btn) {
  const key = btn.getAttribute('data-suggestion-confirm');
  const candidate = (_currentCandidates || []).find((c) => c.key === key);
  const card = btn.closest('[data-suggestion-key]');
  if (!key || !candidate || !card) return;
  const confirmBtn = card.querySelector('[data-suggestion-confirm]');
  const dismissBtn = card.querySelector('[data-suggestion-dismiss]');
  const resultEl = card.querySelector('[data-suggestion-result]');
  if (confirmBtn) confirmBtn.disabled = true;
  if (dismissBtn) dismissBtn.disabled = true;
  if (resultEl) resultEl.textContent = 'Checking…';
  const applicationId = String(candidate.app.application_id);
  const uid = candidate.email.uid;
  try {
    const emailData = await _fetchJSON(`/api/email/read/${encodeURIComponent(uid)}?folder=INBOX${_emailAcctParam()}`);
    const subject = (emailData && emailData.subject) || candidate.email.subject || '';
    const body = _plainTextFromEmailDetail(emailData);
    const scanData = await _post(`${API}/applications/${encodeURIComponent(applicationId)}/scan-email`, { subject, body });
    _rememberDismissedMatch(key);
    if (scanData && scanData.detected && scanData.recorded) {
      const label = SCAN_OUTCOME_LABEL[scanData.outcome_type] || 'an outcome';
      _toast(`Found ${label} in that email — recorded.`);
      _removeSuggestionCard(key);
      await _load(false);
      return;
    }
    if (resultEl) {
      resultEl.textContent = (scanData && scanData.detected)
        ? 'Found some signal, but not confident enough to record automatically.'
        : "Didn’t recognize anything in that email.";
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = errText(e);
    if (confirmBtn) confirmBtn.disabled = false;
    if (dismissBtn) dismissBtn.disabled = false;
  }
}

// ── Screening-answer library (product-gaps backlog #20) ────────────────────
// Lazy per-row disclosure over the reusable, campaign-scoped answer bank a
// generation in Documents quietly builds over time (MaterialService's
// generate_screening_answer -> _save_to_screening_library). Loaded ONLY the
// first time a row's "Screening answers" section is opened, never eagerly for
// every row (same lazy-on-demand shape as the "Check an email" disclosure and
// the digest's Research brief).

async function _onScreeningToggle(details) {
  if (!details.open) return; // 'toggle' also fires on close; only load on open
  const id = details.getAttribute('data-tracker-screening');
  const campaignId = details.getAttribute('data-screening-campaign');
  const body = details.querySelector(`[data-screening-body="${id}"]`);
  if (!body) return;
  if (!campaignId) {
    body.textContent = 'No search linked to this application yet.';
    return;
  }
  try {
    const data = await _fetchJSON(`${LIBRARY_API}/${encodeURIComponent(campaignId)}`);
    _renderScreeningBody(body, id, data && data.items);
  } catch (e) {
    body.textContent = errText(e);
  }
}

function _renderScreeningBody(body, id, items) {
  if (!items || !items.length) {
    body.textContent = 'No saved answers yet — answers you generate in Documents are saved here automatically.';
    return;
  }
  body.innerHTML = items.map((it, i) => `
    <div style="display:flex;align-items:center;gap:8px;padding:4px 0;border-top:1px solid var(--border,rgba(255,255,255,0.08));">
      <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(it.question)}</span>
      <button class="cal-btn" type="button" data-screening-reuse="${id}" data-screening-idx="${i}" style="font-size:10.5px;">Reuse</button>
    </div>
    <div data-screening-result="${id}-${i}" style="font-size:10.5px;opacity:0.7;"></div>`).join('');
  body.querySelectorAll('[data-screening-reuse]').forEach((btn, i) => {
    btn.addEventListener('click', () => _reuseScreeningAnswer(btn, items[i].question));
  });
}

async function _reuseScreeningAnswer(btn, question) {
  const id = btn.getAttribute('data-screening-reuse');
  const idx = btn.getAttribute('data-screening-idx');
  const details = btn.closest('[data-tracker-screening]');
  const campaignId = details ? details.getAttribute('data-screening-campaign') : '';
  const resultEl = details ? details.querySelector(`[data-screening-result="${id}-${idx}"]`) : null;
  if (!id || !question || !campaignId) return;
  btn.disabled = true;
  if (resultEl) resultEl.textContent = 'Reusing…';
  try {
    const data = await _post(`${LIBRARY_API}/reuse`, {
      campaign_id: campaignId, application_id: id, question,
    });
    if (data && data.found) {
      _toast('Reused — ready for review in Documents.');
      if (resultEl) resultEl.textContent = 'Added to Documents for your review.';
    } else if (resultEl) {
      resultEl.textContent = 'Could not reuse that answer.';
    }
  } catch (e) {
    if (resultEl) resultEl.textContent = errText(e);
  } finally {
    btn.disabled = false;
  }
}

// ── Interview prep (product-gaps backlog #30) ───────────────────────────────
// Only rendered on a row that has already recorded an interview_invited
// signal (see _renderRow); the engine independently re-enforces that gate, so
// this is purely the reachable UI for a brief that already exists to generate.

async function _onPrepToggle(details) {
  if (!details.open) return;
  const id = details.getAttribute('data-tracker-prep');
  const body = details.querySelector(`[data-prep-body="${id}"]`);
  if (!body) return;
  try {
    const data = await _fetchJSON(`${API}/applications/${encodeURIComponent(id)}/interview-prep`);
    _renderPrepBody(body, data);
  } catch (e) {
    body.textContent = errText(e);
  }
}

function _renderPrepBody(body, data) {
  if (!data || data.generated !== true) {
    body.textContent = "Prep notes aren’t ready yet.";
    return;
  }
  const notes = Array.isArray(data.notes) ? data.notes : [];
  const reqs = Array.isArray(data.key_requirements) ? data.key_requirements : [];
  const parts = notes.map((n) => `<div style="margin:2px 0;">${esc(n)}</div>`);
  if (reqs.length) {
    parts.push(`<ul style="margin:4px 0 4px 16px;padding:0;">${reqs.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`);
  }
  if (data.company_research) {
    parts.push(`<div style="margin-top:6px;opacity:0.85;white-space:pre-wrap;">${esc(data.company_research)}</div>`);
  }
  body.innerHTML = parts.join('') || 'Nothing more to add yet.';
}

// ── View details (dark-engine audit #25) ────────────────────────────────────
// The Tracker's own drill-down onto the SAME per-application history the
// admin-only Debug modal already renders (status, work mode, screenshot
// count, outcome timeline) -- reached here through the owner-scoped proxy
// instead of an admin gate. Loaded ONLY the first time a row's "View details"
// section is opened, never eagerly for every row (same lazy-on-demand shape
// as "Screening answers" / "Interview prep" above). Also renders the
// originating posting's salary/location (dark-engine audit #56) alongside the
// work mode that was already here -- all three are captured per posting
// (``JobPosting.salary``/``.location``/``.work_mode``) but, before now, only
// work mode reached this surface.

async function _onHistoryToggle(details) {
  if (!details.open) return; // 'toggle' also fires on close; only load on open
  const id = details.getAttribute('data-tracker-history');
  const body = details.querySelector(`[data-history-body="${id}"]`);
  if (!body) return;
  try {
    const data = await _fetchJSON(`${API}/applications/${encodeURIComponent(id)}/history`);
    _renderHistoryBody(body, data);
  } catch (e) {
    body.textContent = errText(e);
  }
}

// Plain-language label for one attributes_used key (dark-engine audit #54):
// the engine's own snake_case/free-form field names ("first_name", "race",
// "First Name") are turned into a consistent Title Case reading -- never the
// raw storage key -- so this stays plain language even though the key set
// itself is caller-defined (whatever the engine recorded as "consumed" for
// this application), not a fixed enum this module can hard-code labels for.
function _prettyAttrLabel(key) {
  const words = String(key || '').replace(/[_-]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return 'Detail';
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// Best-effort display text for one attributes_used value -- primitives print
// as-is; anything else (a nested object/array the engine happened to record)
// is JSON-stringified rather than silently dropped or shown as
// "[object Object]".
function _attrValueText(v) {
  if (v == null) return '';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  try { return JSON.stringify(v); } catch { return String(v); }
}

// The "which of your details were used" section (dark-engine audit #54):
// ``Application.attributes_used`` is the exact attribute map the engine
// consumed submitting THIS application -- a real privacy-trust artifact the
// engine already keeps (see ``AdminQueryService.application_history``) but
// never surfaced anywhere before. Real data only -- an application that never
// recorded any attributes shows the honest "none recorded" state, never a
// fabricated list.
function _attributesUsedHTML(attributesUsed) {
  const attrs = (attributesUsed && typeof attributesUsed === 'object') ? attributesUsed : {};
  const keys = Object.keys(attrs);
  if (!keys.length) {
    return '<div style="opacity:0.7;">No details recorded for this application yet.</div>';
  }
  return `<ul style="margin:4px 0 0 16px;padding:0;">${keys.map((k) => (
    `<li>${esc(_prettyAttrLabel(k))}: ${esc(_attrValueText(attrs[k]))}</li>`
  )).join('')}</ul>`;
}

// A direct link into the application's own LIVE sandbox/takeover session
// (dark-engine audit #57): ``Application.sandbox_session_url`` was recorded on
// every in-flight application but nothing read it -- the remote/takeover lane
// rebuilt its own session list from ``/sessions`` instead of this field.
// Omitted entirely (no empty/dead link) once there is no live session for
// this application (already submitted/archived, or never reached a browser
// session) -- never a fabricated link.
function _sandboxSessionHTML(url) {
  const href = (url == null) ? '' : String(url).trim();
  if (!href) return '';
  return `
    <div style="margin-top:6px;">
      <a class="cal-btn" href="${esc(href)}" target="_blank" rel="noopener noreferrer"
         style="display:inline-block;text-decoration:none;font-size:11px;"
         title="Watch the live browser view I’m using for this application">
        Watch live
      </a>
    </div>`;
}

// Plain-language verb-phrase for one Plan-as-Data op (dark-engine audit #58) --
// the typed GOTO/FIND/FILL/... vocabulary is engine-internal; the owner sees
// "Went to / Filled / Selected / ..." instead of raw op-kind strings.
const _PLAN_OP_LABEL = {
  goto: 'Went to the page',
  find: 'Located a field',
  fill: 'Filled in a field',
  select: 'Chose an option',
  click: 'Clicked a button',
  upload: 'Attached a document',
  extract: 'Read a value from the page',
  assert: 'Checked the page state',
  wait: 'Waited for the page',
  stop: 'Stopped for your review',
};

function _planOpLabel(op) {
  const kind = String((op && op.kind) || '').toLowerCase();
  const base = _PLAN_OP_LABEL[kind] || 'Took a step';
  const detail = op.attribute_id || op.ref || op.url || op.reason || op.document_id || '';
  return detail ? `${base} (${_prettyAttrLabel(String(detail))})` : base;
}

// The "what the agent did on this form" disclosure (dark-engine audit #58):
// the pre-fill planner's stored op-sequence(s) (``plan_ops``, newest last),
// read-only -- this never re-executes anything, it just narrates what
// already ran. Absent/empty (the common case -- ``PREFILL_USE_PLANNER`` is
// off by default) renders nothing, same "no dead UI" convention as the rest
// of this drill-down.
function _planOpsHTML(planOps) {
  const plans = Array.isArray(planOps) ? planOps : [];
  if (!plans.length) return '';
  const pages = plans.map((p) => {
    const ops = Array.isArray(p && p.ops) ? p.ops : [];
    if (!ops.length) return '';
    const steps = ops.map((op) => `<li>${esc(_planOpLabel(op))}</li>`).join('');
    const pageUrl = p && p.url ? esc(String(p.url)) : 'this page';
    return `<div style="margin-top:4px;"><div style="opacity:0.7;">${pageUrl}</div><ol style="margin:2px 0 0 16px;padding:0;">${steps}</ol></div>`;
  }).filter(Boolean).join('');
  if (!pages) return '';
  const totalSteps = plans.reduce((n, p) => n + (Array.isArray(p && p.ops) ? p.ops.length : 0), 0);
  return `
    <details style="margin-top:6px;">
      <summary style="cursor:pointer;opacity:0.7;list-style:revert;">What the agent did on this form (${totalSteps} step${totalSteps === 1 ? '' : 's'})</summary>
      <div style="margin:6px 0 0;max-height:220px;overflow-y:auto;">${pages}</div>
    </details>`;
}

function _renderHistoryBody(body, data) {
  if (!data || data.found === false) {
    body.textContent = 'No history recorded for this application yet.';
    return;
  }
  const status = esc(STATUS_LABEL[data.status] || String(data.status || 'Unknown').replace(/_/g, ' '));
  const workMode = esc(data.work_mode ? String(data.work_mode) : 'Not recorded');
  // dark-engine audit #56: salary/location, captured per posting alongside
  // work mode, but never carried through to this drill-down before -- same
  // "Not recorded" honest-empty convention as work mode above, never a
  // fabricated placeholder.
  const salary = esc(data.salary ? String(data.salary) : 'Not recorded');
  const location = esc(data.location ? String(data.location) : 'Not recorded');
  const shots = data.screenshot_count != null ? Number(data.screenshot_count) : 0;
  const outcomes = Array.isArray(data.outcomes) ? data.outcomes : [];
  const timeline = outcomes.length
    ? `<ul style="margin:4px 0 0 16px;padding:0;">${outcomes.map((o) => `<li>${esc(_outcomeEventLabel(o.type))}</li>`).join('')}</ul>`
    : '<div style="opacity:0.7;">No outcomes recorded yet.</div>';
  body.innerHTML = `
    <div>Status: <strong>${status}</strong></div>
    <div>Location: ${location}</div>
    <div>Work mode: ${workMode}</div>
    <div>Salary: ${salary}</div>
    <div>Screenshots captured: ${esc(String(shots))}</div>
    <div style="margin-top:4px;">Outcomes:${timeline}</div>
    <div style="margin-top:4px;">Data used on this application:${_attributesUsedHTML(data.attributes_used)}</div>
    ${_sandboxSessionHTML(data.sandbox_session_url)}
    ${_planOpsHTML(data.plan_ops)}`;
}

export async function openApplicantTracker() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  await Promise.all([_load(true), _loadPendingConfirmation(), _loadStuck(), _loadBlocked()]);
  // Keep it fresh while open (only while the tab is visible).
  if (_pollStop) _pollStop();
  _pollStop = pollVisible(() => { _load(false); _loadPendingConfirmation(); _loadStuck(); _loadBlocked(); }, 60000);
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

// Named exports below are for tests only (the pure email-match scoring
// heuristic exercised directly, without a full DOM simulation) — the module's
// real runtime surface is still just `openApplicantTracker` / the default.
export {
  _matchTokenize, _scoreEmailAgainstApplication, _bestApplicationForEmail,
  _cheapSubjectHint, _dismissKey,
};

export default applicantTrackerModule;
