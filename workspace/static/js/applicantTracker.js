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
//: Product-gaps backlog #20 — the reusable screening-answer library lives on
//: the Documents proxy (campaign-scoped), not the tracker's own API base.
const LIBRARY_API = '/api/applicant/documents/screening-answer-library';

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
          <button class="cal-btn" id="applicant-tracker-find-emails" title="Look for likely replies in your inbox">Find responses in your inbox</button>
          <button class="cal-btn" id="applicant-tracker-refresh" title="Refresh your tracker">Refresh</button>
          <button class="close-btn" id="applicant-tracker-close" title="Close">✖</button>
        </div>
      </div>
      <div id="applicant-tracker-suggestions" style="display:none;flex-shrink:0;max-height:38vh;overflow-y:auto;border-bottom:1px solid var(--border,rgba(255,255,255,0.08));"></div>
      <div class="modal-body" id="applicant-tracker-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-tracker-close').addEventListener('click', _close);
  modal.querySelector('#applicant-tracker-refresh').addEventListener('click', () => _load(true));
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
  const campaignId = esc(String(app.campaign_id || ''));
  const campaign = app.campaign_name ? `<span style="opacity:0.5;">· ${esc(app.campaign_name)}</span>` : '';
  const busy = _busyIds.has(String(app.application_id));
  const label = esc(_roleLabel(app));
  const signals = Array.isArray(app.signals) ? app.signals : [];
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
      ${_screeningAnswersHTML(id, campaignId, label)}
      ${signals.includes('interview_invited') ? _interviewPrepHTML(id, label) : ''}
    </div>`;
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
    'Once your assistant submits an application, it shows up here so you can follow where it stands.',
  );
  host.querySelectorAll('[data-tracker-record]').forEach((select) => {
    select.addEventListener('change', () => _recordOutcome(select));
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
    _lastApplications = Array.isArray(data && data.applications) ? data.applications : [];
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
        : "Didn't recognize anything in that email.";
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
    body.textContent = 'No campaign on this application yet.';
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
    body.textContent = "Prep notes aren't ready yet.";
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

// Named exports below are for tests only (the pure email-match scoring
// heuristic exercised directly, without a full DOM simulation) — the module's
// real runtime surface is still just `openApplicantTracker` / the default.
export {
  _matchTokenize, _scoreEmailAgainstApplication, _bestApplicationForEmail,
  _cheapSubjectHint, _dismissKey,
};

export default applicantTrackerModule;
