// static/js/applicantOnboarding.js
//
// First-run setup wizard — the blocking, resumable overlay that runs right after
// login when the engine reports setup/onboarding is incomplete. It walks a brand
// new user through, in order:
//
//   1. Connect a model  -> REUSES the Settings Local/Remote endpoint manager
//                           (admin.js mountEndpointManager + /api/model-endpoints),
//                           then opens the engine gate via /api/applicant/setup/llm
//   2. Notifications     -> /api/applicant/setup/channels (gating step)
//   3. Fonts             -> /api/applicant/setup/fonts/*
//   4. Your profile      -> /api/applicant/setup/onboarding/* + base-resume +
//                           LaTeX conversion preview accept/reject, then complete
//
// It is ADDITIVE and self-contained: it opens its own full-screen overlay, talks
// to the engine only through the workspace proxy, and does not touch any other
// module. The engine enforces the real gate (it blocks job work server-side until
// configured); this overlay's job is to DRIVE the user to completion and not let
// the UI wander into the job features early. It is resumable — on every open it
// fetches status and reopens at the first incomplete step. On completion it
// dismisses and re-runs the feature-activation layer so the job sections light up.
//
// White-labelled throughout: plain language, no internal codenames or spec jargon.
//
// RE-USE (per repo CLAUDE.md — lift and shift, don't rebuild):
//   * Overlay/buttons/fields/messages use the SHARED workspace classes
//     (`.modal`/`.modal-content`/`.modal-header`/`.modal-body`, `.admin-card`,
//     `.admin-tab`, `.cal-btn`/`.cal-btn-primary`, `.admin-error`/`.admin-success`,
//     `.settings-row`/`.settings-label`/`.settings-select`) — same as the rest of
//     the app, so the wizard inherits the active theme + future changes.
//   * Step 1 lifts Settings' Local/Remote endpoint manager (admin.js
//     mountEndpointManager + /api/model-endpoints).
//   * Step 2 lifts the channel + "send a test" pattern from Settings' reminder
//     card / admin.js's per-webhook Test (field card → Test button → status span
//     that turns .admin-success / .admin-error).
//   * Steps 3-4 file inputs lift fileHandler.js's picker (createPicker →
//     openPicker/addFiles/uploadPending/renderAttachStrip preview chips +
//     progress) instead of raw <input type=file>.

import fileHandlerModule from './fileHandler.js';
import { esc, _toast, _fetchJSON, _post, errText } from './applicantCore.js';

const SETUP = '/api/applicant/setup';
const OPS = '/api/applicant/ops';  // one-click update (FR-OOBE-4 / FR-INSTALL-2)
const PORTAL = '/api/applicant/portal';  // notification center + deliver-now (FR-NOTIF-5)

let _overlay = null;
let _overlayA11yCleanup = null;
let _campaignId = null;
let _status = null;        // engine setup status
let _onboarding = null;    // engine onboarding state
// Profile-completeness checklist (dark-engine audit item 51): which core profile
// attributes (name/email/phone/title) + search criteria the engine still reports
// missing, straight from ChatService.identify_gaps via GET .../gaps/{campaignId}.
// Best-effort — null until fetched, or on a fetch failure (older engine / offline),
// so the wizard degrades cleanly (see _profileGapsHTML).
let _profileGaps = null;
let _stepIndex = 0;        // active step in STEPS
let _busy = false;
// True once the user has typed/changed anything on the CURRENT step since it was
// last rendered (i.e. unsaved input that a stray Escape would discard). Reset
// whenever a step re-renders (_setBody) — including right after a successful
// save, since the freshly-rendered next step starts clean.
let _formDirty = false;
// Audit Top-25 #17 / §7 item 3 (Journey Beat 2 "first light"): set only when
// _finish() reaches the genuine "You're all set!" screen (llm_configured, i.e.
// the wizard has nothing left gating it), so _dismiss() can tell a real
// completion hand-off apart from an Escape/cancel out of a still-incomplete
// wizard. Consumed (and reset) the moment _dismiss() reads it.
let _justCompletedSetup = false;
// Resilience audit (exhaustive2 lens 04 #52): which draft-persistence "scope" the
// CURRENTLY rendered body belongs to — 'welcome' | 'llm' | 'onboarding:<section>' |
// a Settings step key ('channels'/'sandbox'/'fonts'/'update'). Set by whichever
// render path is about to call _setBody (see _renderStep / _renderIntakeSection /
// mountSettingsStep) so _saveDraft/_restoreDraft key sessionStorage correctly
// without depending on the transient _bodyTarget swap (which is restored to null
// again before the user ever types — see mountSettingsStep's finally).
let _draftScope = null;
// The in-flight résumé-conversion preview build request, if any (exhaustive2 lens
// 04 #59): lets a second trigger (e.g. the resume-upload flow and the
// font-install "Continue" handler can both call _buildPreview back-to-back)
// attach to the SAME build instead of firing a second, overlapping POST.
let _previewInFlight = null;

// Ordered wizard steps. `done(status)` reads the engine status to decide if the
// step is already satisfied (drives resume + the progress rail).
// The `sandbox` step is satisfied (and so skipped on the local default) unless the
// native Windows VM backend is selected and still needs its connection collected —
// the engine reports this via `steps_complete` containing 'sandbox'.
// Slimmed to only the critical-to-quality steps. Notifications, the automation
// sandbox and fonts moved into Settings (reusing the EXACT same renderers below —
// see the exported _renderChannels/_renderSandbox/_renderFonts), so nothing is
// unreachable; the engine no longer gates automated work on channels.
const STEPS = [
  // B1: a welcome / preview step. It is "done" once the user has made any setup
  // progress, so the resumable wizard skips it on re-opens but a brand-new user
  // always lands here first.
  // "Welcome" is done once the user has made any REAL setup progress, so a returning
  // user skips it but a brand-new user always lands here first. NOTE: the engine's
  // `steps_complete` always contains 'sandbox' on the default local backend (it is
  // auto-satisfied, not user-driven), so counting that as progress would skip Welcome
  // on a pristine instance — exclude it and only treat genuine user steps as progress.
  { key: 'welcome',    title: 'Welcome',          done: (s) => !!(s && (s.llm_configured || s.onboarding_complete || s.apply_ready || (Array.isArray(s.steps_complete) && s.steps_complete.some((k) => k !== 'sandbox')))) },
  // `required: true` marks the ONE step that actually gates beginning — the rail
  // (_renderRail) and the Welcome step both surface this so the three steps don't
  // read as equal weight when only one of them is load-bearing.
  { key: 'llm',        title: 'Connect a model',  required: true, done: (s) => !!(s && s.llm_configured) },
  // "Your profile" is OPTIONAL — the only thing that strictly gates BEGINNING is a
  // connected model. Applicant gathers what it needs to apply over time (a résumé,
  // or just telling it in chat). The step is "done enough" once the agent has the
  // required-to-apply essentials (apply_ready), so the rail stops nagging once the
  // hard apply-gate would open; a brand-new user can also just Skip it.
  { key: 'onboarding', title: 'Your profile',     required: false, done: (s) => !!(s && (s.apply_ready || s.onboarding_complete)) },
];

// Intake sub-sections (the comprehensive Workday-ready interview). Each renders a
// small form; data is saved per-section so the interview is fully resumable.
//
// Resume-FIRST: the base-resume upload leads the profile so the engine can read
// the resume and PREFILL the editable fields below (identity, work history,
// education, skills). The user then steps through and corrects any parsing
// mistakes instead of typing everything by hand — uploading is the starting
// point of profile setup, not a post-hoc reconciliation.
// Order (activation-funnel audit 09, items 52/56): `campaign_criteria` — the
// single highest-leverage input for discovery quality — used to sit LAST (12
// of 12), greeting the most fatigued user; moved right after `target_roles`
// so it lands while attention is still fresh. `references` — needed by only a
// minority of applications, and only at submit time — used to sit mid-list;
// moved to the very end so it's the thing skipped first when a user runs out
// of steam, not campaign criteria or EEO. Sections resume by KEY (see
// `_renderOnboarding`'s `findIndex`), so this reorder is safe for anyone
// already partway through the old order.
const INTAKE_SECTIONS = [
  'base_resume',
  'identity', 'work_authorization', 'location', 'target_roles', 'campaign_criteria',
  'compensation', 'work_history', 'education', 'key_attributes', 'eeo',
  'references',
];

// Trust-contract list reused by the Trust Center (applicantTrust.js) and
// landing.html's #trust section (verbatim substring match, see
// test_applicant_activation_funnel_09.py::
// test_trust_section_reuses_the_never_does_wording_verbatim — updated in
// lockstep with this array). Demo-tone pass: reframed from "never"/
// negative-capability phrasing to positive control statements — a list of
// "nots" reads as a disclaimer wall, not a selling point. The wizard welcome
// step and the Portal empty state no longer render this as a list at all
// (see `trustLine` below); this array now backs only the fuller Trust
// Center / landing-page treatments, where an itemized explanation is still
// the right amount of detail.
const NEVER_DOES = [
  'Submits an application only with your approval.',
  'Pauses and asks whenever something is uncertain.',
  'Hands every CAPTCHA to you to solve.',
  'Keeps your voluntary self-identification (EEO) answers in your own words.',
];

// A single, confident control statement — used wherever the product needs to
// say "you decide, always" without unspooling a list of negative disclaimers
// (the wizard welcome step below and the Portal empty state; see D39).
export const trustLine = 'You approve every application before it’s sent — you’re always in control.';
try { if (typeof window !== 'undefined') window.applicantTrustLine = trustLine; } catch { /* no-op */ }

// ── small helpers ───────────────────────────────────────────────────────────

// Busy-button pair (exhaustive2 lens 04 #29a): mirrors applicantRemote.js's
// _setButtonBusy/_clearButtonBusy (that file's local, not exported, so this is a
// same-shape copy rather than an import) — disable + relabel a button while its
// action is in flight so a fast double-click can't replay/duplicate it, then
// restore its original label and enabled state.
function _setButtonBusy(btn, busyText) {
  if (!btn) return null;
  const orig = btn.textContent;
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.style.opacity = '0.6';
  btn.style.cursor = 'wait';
  if (busyText) btn.textContent = busyText;
  return orig;
}

function _clearButtonBusy(btn, orig) {
  if (!btn) return;
  btn.disabled = false;
  btn.removeAttribute('aria-busy');
  btn.style.opacity = '';
  btn.style.cursor = '';
  if (orig != null) btn.textContent = orig;
}

// Micro-interactions lens 01 #47: the persistent Back/Skip nav already no-ops
// while a step's own save is in flight (`if (!_busy) …` in each handler), but
// gave no visual sign the click did nothing — mid-save, the nav looked live but
// silently ignored clicks, reading as broken. `_busy` is a shared module flag
// set by many different per-step handlers (not just _nextStep/_prevStep), so a
// lightweight poll — rather than threading a callback through every save path —
// keeps the persistent nav bar in sync for as long as the overlay is open.
let _navBusyTimer = null;
function _startNavBusyWatch() {
  if (_navBusyTimer) return;
  _navBusyTimer = setInterval(() => {
    const back = document.getElementById('ao-back');
    const skip = document.getElementById('ao-skip');
    [back, skip].forEach((btn) => {
      if (!btn) return;
      btn.disabled = _busy;
      btn.style.opacity = _busy ? '0.6' : '';
    });
  }, 150);
}
function _stopNavBusyWatch() {
  if (_navBusyTimer) { clearInterval(_navBusyTimer); _navBusyTimer = null; }
}

// ── draft persistence (exhaustive2 lens 04 #52) ─────────────────────────────
//
// The wizard (and the Settings panels reusing its step renderers) had zero draft
// persistence: a session-expiry or accidental reload mid-section threw away
// everything typed on the CURRENT step/section, with no recovery. This is a
// lightweight, scoped sessionStorage draft: every text-ish field inside the
// active body is captured on input/change, restored the next time that exact
// step/section renders (including after a reload — sessionStorage survives a
// same-tab reload, just not a closed tab/new session), and cleared the moment
// that step's data is actually saved to the engine (see _advanceAndContinue /
// _nextIntakeOrComplete). Never wired to a fresh scope until one is set — a
// missing/unavailable sessionStorage (private browsing) degrades to a no-op.
const _DRAFT_KEY_PREFIX = 'applicant_onboarding_draft:';

// Fields whose VALUE is itself credential-bearing (not just `type=password`,
// which is already excluded below): the Discord webhook acts as a bearer
// secret, and the Apprise/SMTP + ntfy URLs commonly embed a password or a
// secret channel token right in the string (e.g. `mailto://user:pass@host`).
// Per the hard rule for this fix, none of these are ever persisted, even to
// sessionStorage.
const _DRAFT_EXCLUDE_IDS = new Set(['ao-ch-discord', 'ao-ch-email', 'ao-ch-ntfy']);

function _draftStorageKey(scope) {
  return scope ? `${_DRAFT_KEY_PREFIX}${scope}` : null;
}

function _isDraftableField(el) {
  if (!el) return false;
  const type = (el.type || '').toLowerCase();
  // Never draft passwords/secrets, file pickers (their value can't be restored
  // anyway) or non-data controls.
  if (['password', 'file', 'hidden', 'submit', 'button'].includes(type)) return false;
  if (el.id && _DRAFT_EXCLUDE_IDS.has(el.id)) return false;
  if (!el.id && !el.name) return false; // nothing stable to key the draft on
  return true;
}

// A stable per-element key for the draft object. Most fields have a unique
// `id`; the intake sections' generated fields (see _fieldHTML/_collectForm)
// only set `name`, and repeatable sections (work history/education/references)
// reuse the SAME `name` across every entry card — scope those by their
// `.ao-repeat-entry` card index so entries don't clobber each other.
function _draftFieldKey(el) {
  if (el.id) return `id:${el.id}`;
  if (!el.name) return null;
  const entry = el.closest && el.closest('.ao-repeat-entry');
  if (entry) return `entry${entry.getAttribute('data-idx') || '0'}:${el.name}`;
  return `name:${el.name}`;
}

function _saveDraft(body) {
  const key = _draftStorageKey(_draftScope);
  if (!key || !body) return;
  const data = {};
  body.querySelectorAll('input, textarea, select').forEach((el) => {
    if (!_isDraftableField(el)) return;
    const fkey = _draftFieldKey(el);
    if (!fkey) return;
    data[fkey] = (el.type === 'checkbox' || el.type === 'radio') ? el.checked : el.value;
  });
  try {
    if (Object.keys(data).length) sessionStorage.setItem(key, JSON.stringify(data));
    else sessionStorage.removeItem(key);
  } catch { /* best-effort — a full/unavailable sessionStorage must never break the wizard */ }
}

function _restoreDraft(body) {
  const key = _draftStorageKey(_draftScope);
  if (!key || !body) return;
  let data = null;
  try { data = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { data = null; }
  if (!data) return;
  body.querySelectorAll('input, textarea, select').forEach((el) => {
    if (!_isDraftableField(el)) return;
    const fkey = _draftFieldKey(el);
    if (!fkey || !(fkey in data)) return;
    if (el.type === 'checkbox' || el.type === 'radio') el.checked = !!data[fkey];
    else el.value = data[fkey];
  });
}

function _clearDraft(scope) {
  const key = _draftStorageKey(scope || _draftScope);
  if (!key) return;
  try { sessionStorage.removeItem(key); } catch { /* best-effort */ }
}

// Best-effort cleanup of every draft once the wizard genuinely completes (see
// _dismiss) — nothing left to resume, so no reason to keep any scope around.
function _clearAllDrafts() {
  try {
    const toRemove = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(_DRAFT_KEY_PREFIX)) toRemove.push(k);
    }
    toRemove.forEach((k) => sessionStorage.removeItem(k));
  } catch { /* best-effort */ }
}

// Wire the save-on-input/change listener directly onto the body element ONCE
// (a dataset flag survives the innerHTML rewrites _setBody does on every
// render, so this never double-binds across step transitions). Takes `body`
// as a parameter — deliberately NOT re-reading the module-level _bodyTarget at
// save time, since mountSettingsStep() restores that to its previous value
// (typically null) synchronously right after the render call returns, well
// before the user has typed anything.
function _wireDraftListeners(body) {
  if (!body || body.dataset.aoDraftWired) return;
  body.dataset.aoDraftWired = '1';
  const handler = () => _saveDraft(body);
  body.addEventListener('input', handler);
  body.addEventListener('change', handler);
}

// (Multipart uploads no longer hand-roll FormData here — the fonts/resume steps
// reuse fileHandler.js's picker uploadPending(), which builds + POSTs the form.)

// ── engine status / campaign bootstrap ──────────────────────────────────────

async function _refreshStatus() {
  _status = await _fetchJSON(`${SETUP}/status`);
  return _status;
}

// #117: remember which campaign the wizard is walking through, per user, so a
// reload/relaunch always resumes the SAME one. `GET .../campaigns` carries no
// guaranteed ordering (an unordered SQL SELECT can legitimately return rows in a
// different order across requests), so blindly taking `list[0]` made the
// resumed campaign — and therefore the resumed intake SECTION — depend on
// server-side row order rather than on anything the user did. Pinning the
// resolved id here makes "first incomplete step" a pure function of THIS
// campaign's own state again.
const _CAMPAIGN_KEY_PREFIX = 'applicant_onboarding_campaign:';

function _campaignStorageKey() {
  let user = '';
  try { user = (document.body && document.body.dataset && document.body.dataset.user) || ''; } catch { /* no-op */ }
  return `${_CAMPAIGN_KEY_PREFIX}${user}`;
}

function _rememberedCampaignId() {
  try { return localStorage.getItem(_campaignStorageKey()) || null; } catch { return null; }
}

function _rememberCampaignId(id) {
  try { if (id) localStorage.setItem(_campaignStorageKey(), id); } catch { /* best-effort */ }
}

// The intake attaches to a campaign; ensure one exists once the LLM gate is open.
async function _ensureCampaign() {
  if (_campaignId) return _campaignId;
  let list = [];
  try { list = await _fetchJSON(`${SETUP}/campaigns`); } catch { list = []; }
  if (Array.isArray(list) && list.length) {
    const remembered = _rememberedCampaignId();
    const match = remembered && list.find((c) => c.id === remembered);
    _campaignId = match ? match.id : list[0].id;
    _rememberCampaignId(_campaignId);
    return _campaignId;
  }
  const created = await _post(`${SETUP}/campaigns`, { name: 'My job search' });
  _campaignId = created.id;
  _rememberCampaignId(_campaignId);
  return _campaignId;
}

// ── overlay scaffolding ─────────────────────────────────────────────────────

function _firstIncompleteStep() {
  for (let i = 0; i < STEPS.length; i += 1) {
    if (!STEPS[i].done(_status)) return i;
  }
  return STEPS.length - 1;
}

function _buildOverlay() {
  // The overlay is the SHARED `.modal` (#applicant-onboarding-overlay re-adds the
  // blocking backdrop in CSS). Inside, the SHARED `.modal-content` /
  // `.modal-header` / `.modal-body` give the wizard the exact same frame, title
  // strip and scroll behaviour as every other tool window.
  const o = document.createElement('div');
  o.id = 'applicant-onboarding-overlay';
  // FR-UIKIT-2 (#471): the real dialog root composes the vendored Window kit's
  // `ow-window` alongside the legacy `.modal` (mirrors appkitChatHint.js, which
  // composes the kit `ow-`/`on-` classes onto its real rendered element). The class
  // lands on the actual painted dialog (role=dialog, aria-modal) so the kit window
  // chrome/glass applies; all existing `.modal`/`.modal-content` rules, handlers and
  // the focus trap are preserved.
  o.className = 'modal ow-window';
  // Blocking: trap focus, no dismiss-into-app. The user can't escape into the job
  // features until setup is done (the engine also blocks server-side).
  o.setAttribute('role', 'dialog');
  o.setAttribute('aria-modal', 'true');
  o.setAttribute('aria-label', 'Set up Applicant');
  o.innerHTML = `
    <div class="modal-content" data-no-swipe-dismiss>
      <div class="modal-header" style="cursor:default;">
        <h4>Welcome — let's get you set up</h4>
      </div>
      <!-- D82: resumability is fully implemented (status-driven resume, see
           maybeLaunchOnboarding) but was never STATED, so leaving mid-setup read
           as risky ("will I lose this?"). One persistent, honest line converts
           that fear into permission to step away and come back. -->
      <p class="ao-progress-hint" style="margin:2px 22px 0;font-size:11px;opacity:0.62;">Your progress saves automatically — close this any time and pick up where you left off.</p>
      <div class="admin-tabs" id="ao-rail" role="list" aria-label="Setup progress"></div>
      <div class="modal-body" id="ao-body"></div>
      <!-- D69: Back/Skip (persistent) and the per-step primary action used to be two
           stacked rows (a full-width primary CTA row, then a second full-width nav
           row directly under it) — read as two competing calls to action. They are
           now one terminal action bar: secondary actions (Back/Skip) grouped left,
           the step's primary action right, sharing a single hairline separator. -->
      <div class="ao-actionbar" id="ao-actionbar">
        <div class="ao-nav" id="ao-nav"></div>
        <div class="ao-foot" id="ao-foot"></div>
      </div>
    </div>`;
  // Swallow click-throughs to the app behind the overlay (no dismiss-on-backdrop).
  o.addEventListener('click', (ev) => { if (ev.target === o) ev.stopPropagation(); });
  // `data-no-swipe-dismiss` on `.modal-content` above opts the WHOLE blocking
  // wizard out of ui.js's mobile swipe-down-to-dismiss (it checks
  // `e.target.closest('.cal-splitter, [data-no-swipe-dismiss]')` at touchstart) —
  // this is the one surface that must never be swipe-dismissible, even from the
  // header/grab-zone the generic handler otherwise allows.
  // Track unsaved input so Escape (see _maybeDismiss) can confirm before
  // discarding an in-progress section instead of silently wiping it.
  o.addEventListener('input', () => { _formDirty = true; });
  o.addEventListener('change', () => { _formDirty = true; });
  return o;
}

function _renderRail() {
  const rail = document.getElementById('ao-rail');
  if (!rail) return;
  // The step rail reuses `.admin-tabs`/`.admin-tab` (the same tab strip Settings
  // and the libraries use), but these steps are progress indicators, not
  // clickable tabs: `aria-disabled` says so to assistive tech (there is no click
  // handler either — nothing here is actually focusable/actionable), and the
  // onboarding-scoped CSS drops the tab hover affordance. D76: "Connect a model"
  // is the one step that actually gates beginning — the rail says so instead of
  // presenting all three steps as equal weight (that's also spelled out in the
  // Welcome copy).
  const cur = STEPS[_stepIndex];
  // D74: on a narrow phone the 3-item tab strip can truncate a title ("3. Your
  // pro…"). `.ao-rail-compact` is a single "Step N of M · Title" line that CSS
  // shows ONLY under the narrow breakpoint (swapping in for the tab strip, which
  // is hidden there) — always legible regardless of how long a step title is.
  // #22/#115: "Your profile" already renders its own finer-grained progress line
  // in the body (`_intakeProgressHTML` — "Your profile — section N of 12"), so
  // showing this coarser "Step N of M · Your profile" line at the same time reads
  // as two conflicting counters on a phone. Skip the compact line for that one
  // step; the intake's own line already names the step and shows where you are.
  const compact = cur.key === 'onboarding'
    ? ''
    : `<span class="ao-rail-compact" aria-hidden="true">Step ${_stepIndex + 1} of ${STEPS.length} · ${esc(cur.title)}</span>`;
  const steps = STEPS.map((step, i) => {
    const done = step.done(_status);
    const isCur = i === _stepIndex;
    const cls = `admin-tab ao-rail-step${done ? ' done' : ''}${isCur ? ' active' : ''}`;
    const mark = done ? '✓ ' : `${i + 1}. `;
    const badge = step.required ? ' <span class="ao-rail-req">Required</span>' : '';
    // Micro-interactions lens 01 #60: `aria-current="false"` is a literal string,
    // not a boolean — some assistive tech announces the word "false" aloud. Omit
    // the attribute entirely on non-current steps instead of setting it false.
    const ariaCurrent = isCur ? ' aria-current="step"' : '';
    return `<span class="${cls}" role="listitem" aria-disabled="true"${ariaCurrent}>${esc(mark)}${esc(step.title)}${badge}</span>`;
  }).join('');
  rail.innerHTML = compact + steps;
}

// When a step renderer is reused OUTSIDE the wizard (Settings), these point at the
// settings panel's body/foot elements instead of the wizard's fixed ao-body/ao-foot.
// Null = wizard mode (the default). See mountSettingsStep() below.
let _bodyTarget = null;
let _footTarget = null;
// #96: explicit "am I being rendered inside Settings, not the wizard?" flag,
// threaded through mountSettingsStep() below. The relocated renderers
// (_renderChannels/_renderSandbox/_renderFonts) use it to drop wizard-only
// footer chrome ("Skip for now" / "…&amp; continue") that reads as meaningless
// once there's no wizard flow to continue or skip — Settings just needs "Save".
let _inSettingsContext = false;

function _setBody(html) {
  const body = _bodyTarget || document.getElementById('ao-body');
  if (body) {
    body.innerHTML = html;
    // #52: restore any draft saved for the CURRENT scope (set by the caller
    // before this render — see _renderStep/_renderIntakeSection/mountSettingsStep)
    // then (re-)wire the save-on-input listener for whatever's on screen now.
    _restoreDraft(body);
    _wireDraftListeners(body);
  }
  // A fresh render means whatever was on screen is now either saved (we only
  // get here after a save/step-advance, or on first paint of a step) or
  // discarded intentionally — either way there's nothing unsaved left to lose.
  _formDirty = false;
}

function _setFoot(html) {
  const foot = _footTarget || document.getElementById('ao-foot');
  if (foot) foot.innerHTML = html;
}

function _err(html) {
  return `<p class="admin-error" role="alert" style="font-size:0.86rem;margin:8px 0;">${html}</p>`;
}

// Resume-health at upload: renders the `resume_health` block the engine's
// base-resume ingest now returns (the existing ats_parseability self-check —
// previously run only on the GENERATED render right before submission — reused
// here against the resume the user just uploaded). Friendlier phrasing for the
// couple of known issue strings; anything unrecognized falls back to the raw
// engine message so a wording change upstream never goes silent.
const _RESUME_HEALTH_HINTS = [
  [
    'no recoverable text layer',
    "We couldn’t pull readable text out of this file, so application systems may see a blank resume. If it’s a scanned image or uses text boxes/graphics for layout, try exporting a plain text-based PDF or Word doc instead.",
  ],
  [
    'your name is not detectable',
    "Your name isn’t detectable in the text — make sure it appears as plain text near the top, not inside a header image or graphic.",
  ],
  [
    'contact email is not recoverable',
    "Your email address isn’t detectable in the text — some systems may fail to capture it. Check that it isn’t inside a text box, header/footer image, or icon-only contact block.",
  ],
  [
    'phone number is not detectable',
    "A phone number isn’t detectable in the text — add one in plain text so application systems can capture it.",
  ],
  [
    'no recognizable section headers',
    'We didn’t find standard section headers (e.g. "Experience", "Education", "Skills") — using conventional headers helps automated systems parse your résumé correctly.',
  ],
  [
    'very little text could be read',
    'Only a small amount of text could be read from this file — it may not be a complete résumé, or most of the content may be stored as images.',
  ],
];

function _friendlyResumeHealthIssue(issue) {
  const hit = _RESUME_HEALTH_HINTS.find(([needle]) => issue.includes(needle));
  return hit ? hit[1] : issue;
}

function _resumeHealthHTML(res) {
  const health = (res && res.resume_health) || null;
  const issues = health && Array.isArray(health.issues) ? health.issues : [];
  // HONESTY: "looks good" only on an EXPLICIT positive verdict computed by the
  // engine (verdict === 'good', or an older engine's explicit parseable: true).
  // A missing/unknown resume_health must read as "not assessed" — the absence
  // of a bad verdict is never evidence of a good one.
  const explicitlyGood = !!health && !issues.length
    && (health.verdict === 'good' || (health.verdict == null && health.parseable === true));
  if (explicitlyGood) {
    return '<p class="admin-success" style="font-size:0.82rem;margin:2px 0 8px;">Resume health: looks good — this résumé should read cleanly in most application-tracking systems.</p>';
  }
  if (!issues.length) {
    return '<p style="font-size:0.82rem;margin:2px 0 8px;opacity:0.85;">Resume health: I couldn’t assess this file, so please double-check the profile fields I filled in.</p>';
  }
  const items = issues.map((i) => `<li>${esc(_friendlyResumeHealthIssue(i))}</li>`).join('');
  return `
    <p style="font-size:0.82rem;margin:2px 0 2px;opacity:0.85;">Resume health: a couple of things some application systems may struggle with —</p>
    <ul style="font-size:0.82rem;margin:0 0 8px 18px;opacity:0.85;">${items}</ul>
  `;
}

// Parse-verify ("double-check") line. HONESTY: the green confirmation shows
// only when the engine explicitly reports verified: true; anything else says
// the reading was NOT double-checked and why — the absence of a check is never
// dressed up as one. What the check changed (corrections) and what it kept
// from the first read (restorations) surface here so no change is silent.
const _VERIFY_REASON_COPY = {
  no_model: 'no model is connected yet',
  disabled: 'automatic double-checking is turned off',
  model_error: 'I couldn’t reach your model',
  malformed_output: 'your model couldn’t confirm the reading',
  low_confidence: 'your model wasn’t confident about the reading',
  empty_source: 'no text could be read from the file',
  verify_error: 'the double-check hit an unexpected error',
};

function _friendlyVerifyItem(item) {
  const s = String(item || '');
  if (s.startsWith('role:')) return `Job: ${s.slice(5)}`;
  if (s.startsWith('education:')) return `Education: ${s.slice(10)}`;
  if (s.startsWith('skill:')) return `Skill: ${s.slice(6)}`;
  if (s.startsWith('contact:')) return `Contact: ${s.slice(8)}`;
  return s;
}

// Per-area confidence, grouped by stem because live models rename the areas
// ("work_history_titles_companies" et al). Each area shows its LOWEST matching
// score — the conservative read, same semantics as the engine's floor.
const _CONF_AREAS = [
  ['work', 'work history'],
  ['educat', 'education'],
  ['skill', 'skills'],
  ['contact', 'contact'],
];

function _confidenceSummary(conf) {
  if (!conf || typeof conf !== 'object') return '';
  const parts = [];
  for (const [stem, label] of _CONF_AREAS) {
    const vals = Object.entries(conf)
      .filter(([k, val]) => k.toLowerCase().includes(stem) && Number.isFinite(Number(val)))
      .map(([, val]) => Number(val));
    if (vals.length) parts.push(`${label} ${Math.round(Math.min(...vals) * 100)}%`);
  }
  if (!parts.length) return '';
  return ` <span style="opacity:0.75;">(confidence: ${esc(parts.join(', '))})</span>`;
}

function _verifyListHTML(label, items) {
  if (!Array.isArray(items) || !items.length) return '';
  const shown = items.slice(0, 5).map((c) => `<li>${esc(_friendlyVerifyItem(c))}</li>`).join('');
  const more = items.length > 5 ? `<li>…and ${items.length - 5} more</li>` : '';
  return `
    <p style="font-size:0.82rem;margin:2px 0 2px;opacity:0.85;">${label}</p>
    <ul style="font-size:0.82rem;margin:0 0 8px 18px;opacity:0.85;">${shown}${more}</ul>`;
}

function _parseVerifyHTML(res) {
  const v = (res && res.verify) || null;
  // An older engine that reports nothing gets silence — never a guessed verdict.
  if (!v || typeof v !== 'object') return '';
  const base = 'font-size:0.82rem;margin:2px 0 8px;';
  if (v.verified === true) {
    const fixed = _verifyListHTML('The double-check also tidied up:', v.corrections);
    const kept = _verifyListHTML(
      'Kept from the first read — worth a quick look:',
      v.restored_from_draft,
    );
    return `<p class="admin-success" style="${base}">Double-checked: a model re-read the original file and confirmed how everything was filed.${_confidenceSummary(v.confidence)}</p>${fixed}${kept}`;
  }
  const why = _VERIFY_REASON_COPY[v.reason] || 'it could not be run';
  return `<p style="${base}opacity:0.85;">Not double-checked (${esc(why)}) — the details below came straight from the file, so please review them.</p>`;
}

// Post-upload "what I read" line. HONESTY: the green success styling and the
// "I read N details" claim are shown only when the engine reports a real,
// non-trivial parse (parsed_field_count is what THIS parse extracted). A
// trivially-empty parse is called out as a likely non-text résumé, and an
// engine that doesn't report the count gets no number at all — never a
// fabricated one.
function _resumeReadSummaryHTML(res) {
  const raw = res ? res.parsed_field_count : null;
  const n = raw == null || !Number.isFinite(Number(raw)) ? null : Number(raw);
  const style = 'font-size:0.86rem;margin:8px 0;';
  if (n === null) {
    return `<p style="${style}">I read your résumé — review the next steps and fix anything I got wrong.</p>`;
  }
  if (n === 0) {
    return `<p style="${style}">I couldn’t read any details from this file — it may not be a text résumé. You can still type your profile into the next steps.</p>`;
  }
  if (n < 3) {
    return `<p style="${style}">I could only read ${n} ${n === 1 ? 'detail' : 'details'} from this file — it may not be a text résumé. Please double-check the next steps.</p>`;
  }
  return `<p class="admin-success" style="${style}">I read ${n} details from your résumé and filled in the next steps for you to review.</p>`;
}

// Help marker. Uses the SAME `?` help-icon the rest of the workspace uses
// (`preset-hint-icon`, a native-`title` hover icon — see Settings → Presets) so
// the wizard's tooltips actually show on hover and look identical to the app.
// `role="img"` + the `title`/`aria-label` make the help text reachable to AT too.
function _tip(text) {
  // data-tip drives the immediate CSS hover/focus bubble; aria-label keeps it
  // reachable to assistive tech. (No native `title` — it's slow + would double up.)
  return `<span class="preset-hint-icon ao-tip" role="img" data-tip="${esc(text)}" aria-label="${esc(text)}" tabindex="0">?</span>`;
}

// ── render the active step ──────────────────────────────────────────────────

async function _renderStep() {
  _renderRail();
  _renderNav();
  const step = STEPS[_stepIndex];
  // #52: default the draft scope to this step's key; _renderIntakeSection
  // narrows it further to `onboarding:<section>` before its own _setBody call.
  _draftScope = step.key;
  // Whenever we render anything other than the LLM step, return the shared
  // endpoint manager to its Settings home so it isn't left detached in the DOM.
  if (step.key !== 'llm') _restoreEndpointManager();
  try {
    if (step.key === 'welcome') return _renderWelcome();
    if (step.key === 'llm') return await _renderLLM();
    if (step.key === 'onboarding') return await _renderOnboarding();
  } catch (e) {
    _setBody(_err(esc(e.message || 'Something went wrong.')));
    _setFoot('');
  }
  return undefined;
}

async function _advanceAndContinue(stepKey) {
  // #52: callers only reach here after their own data-save POST already
  // succeeded, so the draft for this step is now redundant — clear it before
  // it can ever mask what the engine actually has on a later reopen.
  _clearDraft(stepKey);
  // Mark the engine step complete (best-effort) then move forward (linearly).
  try { _status = await _post(`${SETUP}/advance/${stepKey}`); }
  catch { await _refreshStatus().catch(e => console.error('Silent catch in applicantOnboarding:', e)); }
  // Settings reuse: a relocated step renderer is being driven from a Settings
  // panel (no wizard overlay open) — save only, never drive wizard navigation.
  if (!_overlay) return;
  await _nextStep();
}

// Linear navigation. The user can ALWAYS move forward (Skip never blocks) and
// ALWAYS go Back to correct a previous step. Completing a step is NOT required to
// advance — the engine still gates real automated work server-side until setup is
// actually done, so letting the user roam the wizard is safe.
async function _nextStep() {
  await _refreshStatus().catch(e => console.error('Silent catch in applicantOnboarding:', e));
  if (_stepIndex >= STEPS.length - 1) { await _finish(); return; }
  _stepIndex += 1;
  await _renderStep();
}

async function _prevStep() {
  if (_stepIndex <= 0) return;
  _stepIndex -= 1;
  await _renderStep();
}

// Persistent Back / Skip bar shown on every step so no step can trap the user.
//
// #18: "Your profile" (the `onboarding` step) manages its OWN Back/Skip/Save &
// continue per intake section (see _renderIntakeSection / _renderRepeatSection /
// _renderBaseResume's own `_setFoot` calls) — layering this persistent bar on
// top of it produced FOUR footer buttons with TWO differently-behaved "Back"s
// (this one jumped to the previous TOP-LEVEL wizard step; the section's own Back
// moves between intake sections) plus a "Finish" that actually skipped the
// entire remaining profile, contradicting its label. Leave all navigation to
// the section footer while inside that step; _finish() already clears this bar
// itself once the wizard actually reaches the completion screen.
function _renderNav() {
  const nav = document.getElementById('ao-nav');
  if (!nav) return;
  const cur0 = STEPS[_stepIndex];
  if (cur0 && cur0.key === 'onboarding') { nav.innerHTML = ''; return; }
  const last = _stepIndex >= STEPS.length - 1;
  // D16 (activation-funnel audit 09): "Skip for now" and "Finish" used to be the
  // exact same button with no hint of what skipping actually costs. On the one
  // step that truly gates beginning ("Connect a model"), spell out the
  // consequence right next to the button instead of leaving it silent.
  const cur = STEPS[_stepIndex];
  const skipHint = (!last && cur && cur.required && !cur.done(_status))
    ? '<span class="ao-skip-hint" style="font-size:11px;opacity:0.65;margin-left:10px;">Connect a model to get started.</span>'
    : '';
  // D69: nav is now a left-aligned button cluster inside the shared `.ao-actionbar`
  // row (see _buildOverlay) rather than a full-width row of its own — no need for
  // an empty spacer span to hold Back's place when it's absent.
  nav.innerHTML =
    (_stepIndex > 0 ? '<button type="button" class="cal-btn" id="ao-back">← Back</button>' : '') +
    `<button type="button" class="cal-btn" id="ao-skip">${last ? 'Finish' : 'Skip for now →'}</button>` +
    skipHint;
  const back = document.getElementById('ao-back');
  if (back) back.onclick = () => { if (!_busy) _prevStep(); };
  const skip = document.getElementById('ao-skip');
  if (skip) skip.onclick = () => { if (!_busy) _nextStep(); };
}

// ── STEP 0: Welcome (B1) ─────────────────────────────────────────────────────
//
// A short, honest preview of the journey and a confident, one-line control
// statement. Reuses the shared `.admin-card` framing + `.ao-step-*` classes
// so it matches every other step. The persistent Skip/Back nav already lets
// the user move on; this step just adds an explicit "Let's go" foot button.
//
// D68/D81: this used to stack TWO bordered `.admin-card` boxes (an ordered list
// + a dense paragraph, then a second card with a 4-item list) before the user
// could do anything — a lot to read on the very first screen. Trimmed to the
// one-line promise + a flattened hairline group that calls out the one actually
// required step (D76). Demo-tone pass: the old "What I never do" disclosure
// (a collapsed list of negative "never" statements) read as a wall of
// disclaimers, not a selling point — replaced with ONE confident control
// statement (`trustLine`, also reused by the Portal empty state — see D39).
//
// NOTE (copy/voice lens 02, #51): the audit flags this step-desc as
// third-person and suggests a first-person rewrite. Left as-is because
// static/js/models.js's welcome card (outside this pass's allowlist) asserts
// this EXACT string verbatim (test_applicant_round1_remainder_welcomecard.py
// ::test_welcome_setup_card_copy_matches_established_wizard_voice) to prove
// it reuses the wizard's voice rather than inventing new copy. Fix both
// files together in a follow-up pass.
function _renderWelcome() {
  _setBody(`
    <h2 class="ao-step-title">Welcome to Applicant</h2>
    <p class="ao-step-desc">Connect a model to get started — everything else, Applicant learns as you go.</p>
    <div class="ao-hairline-group">
      <div class="ao-hairline-row">
        <span class="ao-step-badge ao-step-badge-required">Required</span>
        <span class="ao-hairline-text">Connect a model — a local model or a cloud provider.</span>
      </div>
      <div class="ao-hairline-row">
        <span class="ao-step-badge ao-step-badge-optional">Optional</span>
        <span class="ao-hairline-text">Your profile — add a résumé to speed things up, or skip it and tell me in chat. Notifications, fonts and where I browse live in Settings any time.</span>
      </div>
    </div>
    <p class="ao-welcome-trust" style="font-size:11px;opacity:0.7;margin:14px 0 0;">${esc(trustLine)}</p>
  `);
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-welcome-next">Let's get started</button>`);
  const btn = document.getElementById('ao-welcome-next');
  if (btn) btn.onclick = () => { if (!_busy) _nextStep(); };
}

// ── STEP 1: LLM ─────────────────────────────────────────────────────────────
//
// This step REUSES the existing, working Local/Remote endpoint manager from
// Settings → Services rather than its own bespoke provider form. admin.js owns
// the manager (add local / add remote provider, test, enable/disable, per-model
// toggles) and the proven `/api/model-endpoints` backend; here we just relocate
// that exact node into the wizard (mountEndpointManager) and, once the user has
// an enabled endpoint with a selected model, open the engine gate from the chosen
// values via the engine setup proxy `/api/applicant/setup/llm`.

// True once the manager node has been moved into the wizard, so we can move it
// back to Settings on advance/dismiss.
let _llmManagerMounted = false;

function _adminModule() {
  return (typeof window !== 'undefined' && window.adminModule) ? window.adminModule : null;
}

// Move the shared endpoint manager back to its Settings home (best-effort).
function _restoreEndpointManager() {
  if (!_llmManagerMounted) return;
  const adm = _adminModule();
  try { adm && adm.unmountEndpointManager && adm.unmountEndpointManager(); } catch { /* no-op */ }
  _llmManagerMounted = false;
}

async function _renderLLM() {
  _setBody(`
    <h2 class="ao-step-title">Connect a model ${_tip('I use an AI model to read job posts and write your materials. Add a local model or a cloud provider below, then enable it and pick a model.')}</h2>
    <p class="ao-step-desc">Add a model source below — a local model (e.g. Ollama) or a cloud API. Once it is enabled and shows a model, continue.</p>
    <div id="ao-llm-manager"></div>
    <div id="ao-llm-msg"></div>
  `);
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-llm-save">Save &amp; continue</button>`);

  // Mount the SAME endpoint manager Settings uses. No bespoke add/test/list logic
  // lives here — admin.js drives the form, the live list, and /api/model-endpoints.
  const adm = _adminModule();
  const host = document.getElementById('ao-llm-manager');
  if (adm && typeof adm.mountEndpointManager === 'function' && host && adm.mountEndpointManager(host)) {
    _llmManagerMounted = true;
    // ON-S2-1 (button salad): mountEndpointManager() force-expands BOTH the
    // Local and API add sections (admin.js's _expandAddSections) so the
    // manager is instantly usable — reasonable in Settings (opened by
    // choice, one section at a time) but here it roughly doubles the
    // buttons/toggles on screen the instant this step renders, stacked on
    // top of the Added-Models list. Cap it back to ONE open provider section
    // — Local, the simpler no-signup path — by driving admin.js's OWN
    // already-wired toggle (a synthetic click on its header) rather than
    // hand-editing the collapsed/aria state, so admin.js's localStorage-
    // backed remembered open/closed state for next time stays correct.
    const apiSection = host.querySelector('#adm-add-api');
    if (apiSection && !apiSection.classList.contains('collapsed')) {
      const apiToggle = apiSection.querySelector('.adm-section-toggle');
      if (apiToggle) apiToggle.click();
    }
    // This is the SAME DOM node Settings uses (relocated, not recreated), so
    // a per-endpoint model checklist a previous Settings visit left expanded
    // would otherwise still be open here too. loadEndpoints() always
    // *renders* that checklist collapsed from scratch, but defensively
    // re-collapse any that are somehow already open before the user ever
    // sees this step, so it never "appears at once" with everything else.
    host.querySelectorAll('[data-adm-ep-models-panel]:not(.hidden)').forEach((panelEl) => {
      panelEl.classList.add('hidden');
      const row = panelEl.closest('[data-adm-ep-id]');
      const chevron = row && row.querySelector('.admin-user-chevron');
      if (chevron) { chevron.style.transform = ''; chevron.style.opacity = '0.3'; }
    });
    // #14: the manager's real inputs (e.g. #adm-epLocalUrl / #adm-epUrl) don't
    // exist yet at the _setBody() call above — that call's own _restoreDraft
    // only found the empty `#ao-llm-manager` placeholder, so a draft saved from
    // a previous visit to this step never made it back onto screen. Re-run the
    // restore now that mountEndpointManager() has actually populated the DOM.
    // (The API-key field stays excluded from drafting by design — see
    // _isDraftableField's `type === 'password'` check — so no secret is ever
    // persisted to sessionStorage here.)
    _restoreDraft(document.getElementById('ao-body'));
  } else if (host) {
    host.innerHTML = _err('The model manager is unavailable. Please reload and try again.');
  }

  document.getElementById('ao-llm-save').onclick = async () => {
    if (_busy) return;
    const msgEl = document.getElementById('ao-llm-msg');
    if (msgEl) msgEl.innerHTML = '';
    // Read the chosen endpoint + model straight from the shared manager's live
    // list (the same /api/model-endpoints the manager renders from).
    let chosen = null;
    try { chosen = adm && adm.getSelectedLlmEndpoint ? await adm.getSelectedLlmEndpoint() : null; }
    catch { chosen = null; }
    if (!chosen || !chosen.model) {
      if (msgEl) msgEl.innerHTML = _err('Add a model source above, enable it, and make sure it lists at least one model — then continue.');
      return;
    }
    _busy = true;
    const saveBtn = document.getElementById('ao-llm-save');
    if (saveBtn) saveBtn.disabled = true;
    try {
      // Open the ENGINE gate from the chosen values. /api/applicant/setup/llm is a
      // direct provider/model/key save on the engine (NOT the model-endpoints proxy
      // that 500s). Best-effort: a local model needs no key; a cloud provider's key
      // already lives with the saved endpoint, so we send what we have and surface a
      // clear message if the engine rejects it.
      //
      // B4: infer the provider from the SELECTED ENDPOINT OBJECT (the server's
      // detected `provider` / local-vs-api `category`), not a regex on the URL.
      const provider = _inferProvider(chosen);
      // D27/D33: the manager can silently pick the FIRST enabled endpoint's FIRST
      // model with no confirmation UI, and an unrecognized cloud provider quietly
      // becomes "openai" — say out loud what is actually about to be connected so
      // a wrong pick (a toy/embedding model, a mis-detected provider) is visible
      // before it becomes the engine's brain, not discovered later as a mystery
      // failure.
      if (msgEl) msgEl.innerHTML = `<p style="font-size:0.8rem;opacity:0.75;margin:4px 0;">Connecting as <strong>${esc(provider)}</strong> · model: <strong>${esc(chosen.model)}</strong>…</p>`;
      // B3: only advance when the engine gate actually opens. If the save fails,
      // keep the user on this step with a clear retry and leave it marked
      // not-done so the resumable wizard reopens here.
      try {
        await _post(`${SETUP}/llm`, {
          provider,
          base_url: chosen.base_url || '',
          api_key: '',
          model: chosen.model,
        });
      } catch (gateErr) {
        if (msgEl) {
          msgEl.innerHTML = _err(esc(
            `I couldn’t connect to this model: ${gateErr.message || 'unknown error'}. `,
          ) + 'Check the model is enabled and reachable, then try again.');
        }
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Try again'; }
        _busy = false;
        return; // stay on the LLM step; it remains not-done
      }
      _restoreEndpointManager();
      await _advanceAndContinue('llm');
    } catch (e) {
      if (msgEl) msgEl.innerHTML = _err(esc(e.message || 'Could not save the model.'));
      if (saveBtn) saveBtn.disabled = false;
    } finally {
      _busy = false;
    }
  };
}

// B4: infer the engine provider/type from the selected endpoint object returned
// by getSelectedLlmEndpoint() (server-detected `provider` + local/api
// `category`), with a conservative fallback only if those are absent.
function _inferProvider(chosen) {
  const prov = (chosen && chosen.provider ? String(chosen.provider) : '').toLowerCase();
  if (prov) {
    // Local runtimes the engine treats as Ollama-compatible.
    if (prov === 'ollama' || prov === 'llamacpp' || prov === 'lmstudio' || prov === 'local') return 'ollama';
    if (prov === 'openai') return 'openai';
    if (prov === 'anthropic') return 'anthropic';
    // Most cloud providers are OpenAI-compatible from the engine's perspective.
    return 'openai';
  }
  // No detected provider — fall back to the local/api category from the object.
  if (chosen && chosen.category === 'local') return 'ollama';
  return 'openai';
}

// ── STEP 2: Notification channels (gating) ──────────────────────────────────

// This step LIFTS the channel + "send a test" UI/flow from Settings' reminder
// card (settings.js `initReminderSettings`) and admin.js's per-webhook Test:
// a channel field card (`.admin-card` + `.settings-col`/`.settings-row`/
// `.settings-label`/`.settings-select`) followed by a Test card whose
// `.admin-btn-add` button writes a status span that turns `.admin-success` /
// `.admin-error` — the same save-then-test pattern, pointed at the wizard's
// existing `/channels` + `/channels/test` proxies.
async function _renderChannels() {
  let cur = {};
  try { cur = await _fetchJSON(`${SETUP}/channels`); } catch { cur = {}; }
  const qh = (cur && cur.quiet_hours) || { enabled: false, start: '22:00', end: '07:00', tz: '' };
  // A free-text zone silently degrades to UTC on the engine side if it's ever left blank
  // or unrecognized, so default a first-time (unsaved) field to the browser's own zone
  // rather than blank/UTC — a new user then starts from a correct zone.
  let _browserTz = 'UTC';
  try { _browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { /* keep UTC fallback */ }
  const qhTz = qh.tz || _browserTz;
  _setBody(`
    <h2 class="ao-step-title">Notifications ${_tip('How I reach you — Discord and/or email — with your daily digest and approval requests. Optional: you can skip this and set it up later in Settings.')}</h2>
    <p class="ao-step-desc">Add a Discord webhook and/or an email address so I can send you updates and ask for approvals. This is optional — you can <strong>Skip for now</strong> and set it up later. Discord and phone push (ntfy) are <strong>recommended</strong>: they need no DNS setup and can't land in a spam folder. Email works too, but it's only as reliable as your own mail server's setup — see the deliverability tips below before you lean on it.</p>
    <div class="admin-card">
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Discord webhook <span class="ao-ch-recommended" style="font-size:10px;font-weight:600;color:#2f6fed;background:rgba(47,111,237,0.12);border-radius:3px;padding:1px 5px;margin-left:4px;">Recommended</span>
            ${_tip('In your Discord server: Settings → Integrations → Webhooks → New Webhook → Copy URL.')}
          </label>
          <input id="ao-ch-discord" class="settings-select" type="text" placeholder="https://discord.com/api/webhooks/…" value="${esc(cur.discord_webhook_url || '')}" />
          <button type="button" class="cal-btn" id="ao-ch-test-discord" title="Save your channels, then send a test message to Discord only">Send test</button>
        </div>
        <div class="settings-row"><span id="ao-ch-test-discord-msg" style="font-size:11px;margin-left:auto;"></span></div>
        <div class="settings-row">
          <label class="settings-label">Phone push (ntfy) <span class="ao-ch-recommended" style="font-size:10px;font-weight:600;color:#2f6fed;background:rgba(47,111,237,0.12);border-radius:3px;padding:1px 5px;margin-left:4px;">Recommended</span>
            ${_tip('A free ntfy topic URL for instant push to your phone, e.g. ntfy://ntfy.sh/your-secret-topic. Install the ntfy app, subscribe to the same topic, and urgent action alerts arrive as push notifications. Add several, comma-separated.')}
          </label>
          <input id="ao-ch-ntfy" class="settings-select" type="text" placeholder="${cur.ntfy_configured ? '•••• already saved — leave blank to keep' : 'ntfy://ntfy.sh/your-secret-topic'}" value="" />
          <button type="button" class="cal-btn" id="ao-ch-test-ntfy" title="Save your channels, then send a test push to your phone only">Send test</button>
        </div>
        <div class="settings-row"><span id="ao-ch-test-ntfy-msg" style="font-size:11px;margin-left:auto;"></span></div>
        <div class="settings-row">
          <label class="settings-label">Email / SMTP <span style="font-size:10px;font-weight:600;color:#8a6d3b;background:rgba(138,109,59,0.12);border-radius:3px;padding:1px 5px;margin-left:4px;">Needs setup for reliable delivery</span>
            ${_tip('An Apprise-style URL, e.g. mailto://user:pass@gmail.com. You can add several, comma-separated. Sending through your own SMTP host? Add SPF/DKIM/DMARC records for that domain or digests can land in spam — see the deliverability tips below.')}
          </label>
          <input id="ao-ch-email" class="settings-select" type="text" placeholder="mailto://user:pass@smtp.example.com" value="${esc(cur.apprise_urls || '')}" />
          <button type="button" class="cal-btn" id="ao-ch-test-email" title="Save your channels, then send a test email only">Send test</button>
        </div>
        <div class="settings-row"><span id="ao-ch-test-email-msg" style="font-size:11px;margin-left:auto;"></span></div>
        <div style="font-size:11px;opacity:0.6;margin-top:4px;">Add any of these — or skip for now. In-app updates are always on with zero setup: everything I send shows up in your Pending portal either way.</div>
      </div>
    </div>
    <div class="admin-card ao-help">
      <h2>How to set these up</h2>
      <p style="margin:4px 0 2px;"><strong>Discord webhook</strong> (recommended)</p>
      <ol style="margin:0 0 8px 18px;padding:0;">
        <li>In your Discord server: <strong>Server Settings → Integrations → Webhooks</strong>.</li>
        <li><strong>New Webhook</strong>, choose the channel for your updates, then <strong>Copy Webhook URL</strong>.</li>
        <li>Paste it into the Discord webhook field above.</li>
      </ol>
      <p style="margin:4px 0 2px;"><strong>Phone push (ntfy)</strong> (recommended) — free instant push to your phone:</p>
      <ol style="margin:0 0 8px 18px;padding:0;">
        <li>Install the <strong>ntfy</strong> app (iOS / Android) or open <code>ntfy.sh</code>.</li>
        <li>Pick a hard-to-guess topic name and subscribe to it in the app.</li>
        <li>Paste <code>ntfy://ntfy.sh/your-topic</code> above (self-hosted: <code>ntfy://your-host/your-topic</code>).</li>
      </ol>
      <p style="margin:4px 0 2px;"><strong>Email / SMTP</strong> — an Apprise-style URL:</p>
      <ul style="margin:0 0 6px 18px;padding:0;">
        <li>Gmail: <code>mailto://you:APP_PASSWORD@gmail.com</code> — use a Google <em>App Password</em>, not your login password.</li>
        <li>Other SMTP: <code>mailtos://user:pass@smtp.yourhost.com:587</code></li>
        <li>Add several by separating them with commas.</li>
        <li>Sending through your own domain? Publish SPF, DKIM, and DMARC DNS records for
          that domain, or mail providers may quietly file your digest as spam — full
          record examples and a pre-launch checklist are in
          <code>docs/email-deliverability.md</code>.</li>
        <li>Want a nicer From name or a Reply-To? Add <code>?from=Applicant&amp;reply=you@yourdomain.com</code>
          to the URL above — Apprise supports both, no code change needed.</li>
      </ul>
      <p style="margin:0;opacity:0.6;">Full URL formats: github.com/caronc/apprise/wiki</p>
    </div>
    <div class="admin-card">
      <h2><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;opacity:0.6"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>Send yourself a test</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">Save your channels and send a test notification to verify they work.</div>
      <div class="settings-row">
        <span id="ao-ch-test-msg" style="font-size:11px;"></span>
        <button class="admin-btn-add" id="ao-ch-test" style="margin-left:auto;">Send a test</button>
      </div>
    </div>
    <div class="admin-card">
      <h2>Quiet hours ${_tip('When on, I hold approval requests and your daily digest until quiet hours end, so I never ping you overnight. Anything urgent — like an error that needs you — always comes through right away.')}</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">Pause non-urgent pushes (Discord and email) during a nightly window. In-app updates still appear in your portal, and errors always reach you immediately.</div>
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Notify me</label>
          <select id="ao-qh-mode" class="settings-select">
            <option value="always"${qh.enabled ? '' : ' selected'}>Any time (24/7)</option>
            <option value="quiet"${qh.enabled ? ' selected' : ''}>Except during quiet hours</option>
          </select>
        </div>
        <div id="ao-qh-window" style="display:${qh.enabled ? 'block' : 'none'}">
          <div class="settings-row">
            <label class="settings-label">Quiet from ${_tip('Start of the quiet window, 24-hour HH:MM. Wraps past midnight — e.g. 22:00 to 07:00.')}</label>
            <input id="ao-qh-start" class="settings-select" type="time" value="${esc(qh.start || '22:00')}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">Quiet until</label>
            <input id="ao-qh-end" class="settings-select" type="time" value="${esc(qh.end || '07:00')}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">Time zone ${_tip('An IANA name like America/Phoenix or Europe/London. Defaults to your browser’s own time zone; leave blank to use UTC.')}</label>
            <input id="ao-qh-tz" class="settings-select" type="text" placeholder="UTC" value="${esc(qhTz)}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">During quiet hours ${_tip('Choose per channel. Set one to "anytime" to keep it delivering overnight — e.g. hold Discord but still let email through.')}</label>
            <select id="ao-qh-discord" class="settings-select">
              <option value="hold"${(qh.channels && qh.channels.discord === false) ? '' : ' selected'}>Hold Discord overnight</option>
              <option value="send"${(qh.channels && qh.channels.discord === false) ? ' selected' : ''}>Send Discord anytime</option>
            </select>
          </div>
          <div class="settings-row">
            <label class="settings-label" for="ao-qh-email" style="visibility:hidden;">During quiet hours (email)</label>
            <select id="ao-qh-email" class="settings-select" aria-label="Email during quiet hours">
              <option value="hold"${(qh.channels && qh.channels.email === false) ? '' : ' selected'}>Hold email overnight</option>
              <option value="send"${(qh.channels && qh.channels.email === false) ? ' selected' : ''}>Send email anytime</option>
            </select>
          </div>
        </div>
      </div>
      <div id="ao-qh-msg" style="margin-top:6px;"></div>
      <div class="settings-row" style="margin-top:8px;">
        <span id="ao-qh-save-msg" style="font-size:11px;"></span>
        <button class="admin-btn-add" id="ao-qh-save" style="margin-left:auto;">Save quiet hours</button>
      </div>
      <div class="admin-toggle-sub" style="margin-top:10px;margin-bottom:6px;">Need something that’s being held right now? I’ll release everything quiet hours is holding, immediately.</div>
      <div class="settings-row">
        <span id="ao-qh-deliver-msg" style="font-size:11px;"></span>
        <button class="cal-btn" id="ao-qh-deliver" style="margin-left:auto;">Deliver now</button>
      </div>
    </div>
    <div class="admin-card">
      <h2>Email reminder timing ${_tip('How long I wait before also emailing you about an approval I haven’t heard back on. The in-app and Discord nudges come first; email is the slower backstop.')}</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">If an approval still needs you after this long, I also email you as a backstop. Lower means I email sooner; higher means fewer emails.</div>
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Email me after</label>
          <input id="ao-ch-email-timeout" class="settings-select" type="number" min="1" max="1440" step="1" style="max-width:120px;" value="${esc(cur.email_timeout_minutes || 15)}" />
          <span style="font-size:11px;opacity:0.7;margin-left:6px;">minutes</span>
        </div>
      </div>
      <div class="settings-row" style="margin-top:8px;">
        <span id="ao-et-save-msg" style="font-size:11px;"></span>
        <button class="admin-btn-add" id="ao-et-save" style="margin-left:auto;">Save reminder timing</button>
      </div>
    </div>
    <div id="ao-ch-msg"></div>
  `);
  // #96: "…&amp; continue" reads as meaningless once this renderer is mounted
  // inside Settings (there is no wizard flow to continue) — plain "Save" there.
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-ch-save">${_inSettingsContext ? 'Save' : 'Save &amp; continue'}</button>`);

  const collect = () => {
    const body = {
      discord_webhook_url: (document.getElementById('ao-ch-discord').value || '').trim(),
      apprise_urls: (document.getElementById('ao-ch-email').value || '').trim(),
    };
    // ntfy field shows a masked placeholder when already saved; only send a new value
    // (empty leaves the persisted topic untouched on the engine side).
    const ntfy = (document.getElementById('ao-ch-ntfy').value || '').trim();
    if (ntfy) body.ntfy_url = ntfy;
    return body;
  };
  // True when a channel is configured EITHER in the form now or already saved (so the
  // Test button works for an already-saved ntfy topic the masked field left blank).
  const anyChannel = (body) =>
    !!(body.discord_webhook_url || body.apprise_urls || body.ntfy_url || cur.ntfy_configured
       || cur.discord_configured || cur.email_configured);

  // Same save-then-test handler shape as settings.js's reminder Test button:
  // disable, status into a span, success → `.admin-success`, failure → `.admin-error`.
  const testBtn = document.getElementById('ao-ch-test');
  const testMsg = document.getElementById('ao-ch-test-msg');
  testBtn.onclick = async () => {
    const body = collect();
    if (!anyChannel(body)) {
      testMsg.textContent = 'Add a channel first.'; testMsg.className = 'admin-error'; return;
    }
    testBtn.disabled = true;
    testMsg.textContent = 'Saving and sending…'; testMsg.className = '';
    try {
      await _post(`${SETUP}/channels`, body);
      const res = await _post(`${SETUP}/channels/test`, {});
      const ch = (res.channels || []).join(', ') || 'your channels';
      // UX honesty: when notifications aren't live, the engine captured the test but
      // sent nothing — say so instead of claiming delivery (matches the engine note).
      if (res.live === false) {
        testMsg.textContent = res.note
          ? `Configured ${ch}. ${res.note}.`
          : `Configured ${ch} (dry run — nothing sent yet).`;
        testMsg.className = 'admin-warn';
      } else {
        testMsg.textContent = `Test sent to ${ch}.`; testMsg.className = 'admin-success';
      }
    } catch (e) {
      testMsg.textContent = "That didn’t send: " + (e.message || "I couldn’t send that test."); testMsg.className = 'admin-error';
    } finally {
      testBtn.disabled = false;
    }
  };

  // P1-4: per-channel Send test — same save-then-test shape as the all-channels
  // button above, but scoped to ONE channel (`POST /channels/test {channel}`), so
  // a failing webhook/SMTP/topic reports failure on ITS row instead of hiding
  // behind the channels that worked.
  const _wireChannelTest = (btnId, channel, msgId, hasValue) => {
    const btn = document.getElementById(btnId);
    const msg = document.getElementById(msgId);
    if (!btn || !msg) return;
    btn.onclick = async () => {
      const body = collect();
      if (!hasValue(body)) {
        msg.textContent = 'Add this channel first.'; msg.className = 'admin-error'; return;
      }
      btn.disabled = true;
      msg.textContent = 'Saving and sending…'; msg.className = '';
      try {
        // Save first so the test uses what's typed in the form — but only when
        // something is typed (an all-empty save is rejected by the engine, and
        // testing an already-saved channel needs no re-save).
        if (body.discord_webhook_url || body.apprise_urls || body.ntfy_url) {
          await _post(`${SETUP}/channels`, body);
        }
        const res = await _post(`${SETUP}/channels/test`, { channel });
        // UX honesty: a dry-run deployment captured the test but sent nothing.
        if (res.live === false) {
          msg.textContent = res.note ? `Saved. ${res.note}.` : 'Saved (dry run — nothing sent yet).';
          msg.className = 'admin-warn';
        } else {
          msg.textContent = 'Test sent — check it arrived.'; msg.className = 'admin-success';
        }
      } catch (e) {
        msg.textContent = "That didn’t send: " + (e.message || 'delivery failed.'); msg.className = 'admin-error';
      } finally {
        btn.disabled = false;
      }
    };
  };
  _wireChannelTest('ao-ch-test-discord', 'discord', 'ao-ch-test-discord-msg',
    (b) => !!(b.discord_webhook_url || cur.discord_configured));
  _wireChannelTest('ao-ch-test-email', 'email', 'ao-ch-test-email-msg',
    (b) => !!(b.apprise_urls || cur.email_configured));
  _wireChannelTest('ao-ch-test-ntfy', 'ntfy', 'ao-ch-test-ntfy-msg',
    (b) => !!(b.ntfy_url || cur.ntfy_configured));

  // Quiet hours (FR-NOTIF-5). The mode select reveals the window, mirroring the
  // sandbox-backend reveal above. Saving is independent of the channel save so it
  // works the same in the wizard and in Settings (where there's no "continue").
  const qhMode = document.getElementById('ao-qh-mode');
  const qhWindow = document.getElementById('ao-qh-window');
  if (qhMode) qhMode.onchange = () => {
    qhWindow.style.display = (qhMode.value === 'quiet') ? 'block' : 'none';
  };
  const qhSave = document.getElementById('ao-qh-save');
  const qhSaveMsg = document.getElementById('ao-qh-save-msg');
  if (qhSave) qhSave.onclick = async () => {
    const enabled = qhMode.value === 'quiet';
    const discordSel = document.getElementById('ao-qh-discord');
    const emailSel = document.getElementById('ao-qh-email');
    const body = {
      enabled,
      start: (document.getElementById('ao-qh-start').value || '22:00'),
      end: (document.getElementById('ao-qh-end').value || '07:00'),
      tz: (document.getElementById('ao-qh-tz').value || '').trim(),
      // #302 per-channel quiet: "hold" = respects quiet hours, "send" = anytime.
      discord_respects_quiet: discordSel ? discordSel.value === 'hold' : true,
      email_respects_quiet: emailSel ? emailSel.value === 'hold' : true,
    };
    qhSave.disabled = true;
    qhSaveMsg.textContent = 'Saving…'; qhSaveMsg.className = '';
    try {
      await _post(`${SETUP}/channels/quiet-hours`, body);
      qhSaveMsg.textContent = enabled ? 'Quiet hours saved.' : 'Notifications on 24/7.';
      qhSaveMsg.className = 'admin-success';
    } catch (e) {
      qhSaveMsg.textContent = "I couldn’t save that: " + (e.message || 'Try again shortly.'); qhSaveMsg.className = 'admin-error';
    } finally {
      qhSave.disabled = false;
    }
  };

  // Deliver now (FR-NOTIF-5): force-release every notification quiet hours is
  // currently holding back. Same save-then-status button shape as the Test card.
  const qhDeliver = document.getElementById('ao-qh-deliver');
  const qhDeliverMsg = document.getElementById('ao-qh-deliver-msg');
  if (qhDeliver) qhDeliver.onclick = async () => {
    qhDeliver.disabled = true;
    qhDeliverMsg.textContent = 'Releasing…'; qhDeliverMsg.className = '';
    try {
      const res = await _post(`${PORTAL}/notifications/deliver-now`, {});
      const n = (res && typeof res.count === 'number') ? res.count : 0;
      qhDeliverMsg.textContent = n > 0
        ? `Released ${n} held notification${n === 1 ? '' : 's'}.`
        : 'Nothing was being held back by quiet hours.';
      qhDeliverMsg.className = 'admin-success';
      _toast(qhDeliverMsg.textContent);
    } catch (e) {
      qhDeliverMsg.textContent = "I couldn’t deliver those: " + (e.message || 'Try again shortly.'); qhDeliverMsg.className = 'admin-error';
    } finally {
      qhDeliver.disabled = false;
    }
  };

  // Email reminder timing (FR-NOTIF-2): the escalation delay before email backstops
  // an unanswered approval. Saved on its own (no URL needed) so it works the same in
  // the wizard and in Settings.
  const etSave = document.getElementById('ao-et-save');
  const etSaveMsg = document.getElementById('ao-et-save-msg');
  if (etSave) etSave.onclick = async () => {
    const timeoutInput = document.getElementById('ao-ch-email-timeout');
    const raw = parseInt(timeoutInput.value, 10);
    const minutes = Number.isFinite(raw) ? Math.max(1, Math.min(1440, raw)) : 15;
    // Micro-interactions lens 01 #26: the clamp used to happen silently — typing
    // 5000 saved as 1440 with no sign anything changed. Reflect the clamped
    // value back into the field and say so, instead of a value that quietly
    // disagrees with what's on screen.
    const wasClamped = Number.isFinite(raw) && raw !== minutes;
    timeoutInput.value = minutes;
    etSave.disabled = true;
    etSaveMsg.textContent = 'Saving…'; etSaveMsg.className = '';
    try {
      await _post(`${SETUP}/channels`, { email_timeout_minutes: minutes });
      etSaveMsg.textContent = wasClamped
        ? `Capped at ${minutes} minutes — saved. I’ll email you after ${minutes} minutes.`
        : `Saved — I’ll email you after ${minutes} minutes.`;
      etSaveMsg.className = 'admin-success';
    } catch (e) {
      etSaveMsg.textContent = "I couldn’t save that: " + (e.message || 'Try again shortly.'); etSaveMsg.className = 'admin-error';
    } finally {
      etSave.disabled = false;
    }
  };

  document.getElementById('ao-ch-save').onclick = async () => {
    if (_busy) return;
    const body = collect();
    if (!anyChannel(body)) {
      document.getElementById('ao-ch-msg').innerHTML = _err('Add at least one notification channel to continue.');
      return;
    }
    _busy = true;
    document.getElementById('ao-ch-save').disabled = true;
    try {
      await _post(`${SETUP}/channels`, body);
      await _advanceAndContinue('channels');
    } catch (e) {
      document.getElementById('ao-ch-msg').innerHTML = _err(esc(e.message || 'Could not save channels.'));
      document.getElementById('ao-ch-save').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

// ── STEP 2.5: Automation sandbox (FR-SANDBOX-1) ─────────────────────────────
//
// This step LIFTS the same `.admin-card`/`.settings-col`/`.settings-row`/
// `.settings-label`/`.settings-select` field-card pattern as the Notifications
// step above, plus the same collect → save → advance handler shape, pointed at
// the wizard's `/sandbox-connection` proxy. The default is the built-in (local)
// sandbox — choosing the native Windows VM reveals the Proxmox connection form so
// the agent (and your one-click takeover) drive real Chrome inside a real Windows
// VM. The connection's secrets are sealed in the engine vault, never returned.
// Desktop help (FR-CUA) honest-state renderer for the Automation settings card.
// Reads the engine's desktop-assist preflight through the live-session proxy and
// renders the toggle locked-with-caveat while the capability is dormant. The
// toggle is informational here (the real per-session opt-in lives in the live
// session); it stays disabled until the helper is actually available.
async function _renderDesktopAssistSetting() {
  const btn = document.getElementById('ao-desktop-toggle');
  const note = document.getElementById('ao-desktop-note');
  if (!btn || !note) return;
  let health = { available: false, dormant: true };
  try {
    const data = await _fetchJSON('/api/applicant/remote/desktop/health');
    if (data) health = data;
  } catch { /* best-effort; stays locked */ }
  if (health.available) {
    btn.disabled = false;
    btn.textContent = 'Turn on';
    note.textContent = 'Ready. Turn it on from the live browser window whenever you need it.';
  } else {
    btn.disabled = true;
    btn.textContent = 'Turn on';
    note.textContent = 'Coming in a future update — desktop help isn’t set up on this browser yet.';
  }
}

async function _renderSandbox() {
  let cur = {};
  try { cur = await _fetchJSON(`${SETUP}/sandbox-connection`); } catch { cur = {}; }
  const conn = cur.connection || {};
  // Default the picker to whatever the engine has selected.
  const isWindows = (cur.backend === 'proxmox-windows');

  _setBody(`
    <h2 class="ao-step-title">Where I browse ${_tip('Where I run the browser I drive — and that you take over when a human step is needed. The built-in browser works out of the box. Advanced: point me at your own Windows VM (on Proxmox) so I browse using real Chrome on real Windows.')}</h2>
    <p class="ao-step-desc">Pick where I run the browser. Most people keep the built-in browser.</p>
    <div class="admin-card">
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Runs in</label>
          <select id="ao-sb-backend" class="settings-select">
            <option value="local"${isWindows ? '' : ' selected'}>Built-in browser (recommended)</option>
            <option value="proxmox-windows"${isWindows ? ' selected' : ''}>My own Windows VM (Proxmox)</option>
          </select>
        </div>
      </div>
    </div>
    <div id="ao-sb-win" style="display:${isWindows ? 'block' : 'none'}">
      <div class="admin-card">
        <div class="settings-col">
          <div class="settings-row">
            <label class="settings-label">Proxmox API URL ${_tip('Your Proxmox API base, e.g. https://pve.example.com:8006/api2/json')}</label>
            <input id="ao-sb-apiurl" class="settings-select" type="text" placeholder="https://pve.example.com:8006/api2/json" value="${esc(conn.proxmox_api_url || '')}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">Node ${_tip('The Proxmox node hosting the VM, e.g. pve.')}</label>
            <input id="ao-sb-node" class="settings-select" type="text" placeholder="pve" value="${esc(conn.proxmox_node || '')}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">API token ${_tip('A Proxmox API token id + its secret. The secret is sealed in the encrypted vault — leave blank to keep the saved one.')}</label>
            <div style="display:flex;gap:6px;">
              <input id="ao-sb-tokenid" class="settings-select" type="text" placeholder="root@pam!applicant" value="${esc(conn.proxmox_token_id || '')}" style="flex:2;" />
              <input id="ao-sb-tokensecret" class="settings-select" type="password" placeholder="${cur.configured ? '•••• already saved — leave blank to keep' : 'secret'}" autocomplete="new-password" style="flex:1;" />
            </div>
          </div>
          <div class="settings-row">
            <label class="settings-label">VM ID ${_tip('The VM ID of your licensed Windows VM (Chrome + guest agent + RDP enabled).')}</label>
            <input id="ao-sb-vmid" class="settings-select" type="number" placeholder="100" value="${esc(conn.template_vmid || '')}" />
          </div>
          <div class="settings-row">
            <label class="settings-label">Take over with</label>
            <select id="ao-sb-tomethod" class="settings-select">
              <option value="rdp"${(conn.takeover_method || 'rdp') === 'rdp' ? ' selected' : ''}>RDP (one-click rdp:// link)</option>
              <option value="web-console"${conn.takeover_method === 'web-console' ? ' selected' : ''}>Web console (Guacamole)</option>
            </select>
          </div>
          <div class="settings-row" id="ao-sb-rdp" style="display:${conn.takeover_method === 'web-console' ? 'none' : 'flex'}">
            <label class="settings-label">RDP sign-in ${_tip('The Windows account you take over with. Password is sealed in the vault — leave blank to keep the saved one.')}</label>
            <div style="display:flex;gap:6px;">
              <input id="ao-sb-rdpuser" class="settings-select" type="text" placeholder="Administrator" value="${esc(conn.rdp_username || '')}" style="flex:1;" />
              <input id="ao-sb-rdppass" class="settings-select" type="password" placeholder="${cur.configured ? '•••• already saved — leave blank to keep' : 'password'}" autocomplete="new-password" style="flex:1;" />
            </div>
          </div>
          <div class="settings-row" id="ao-sb-web" style="display:${conn.takeover_method === 'web-console' ? 'flex' : 'none'}">
            <label class="settings-label">Web console URL ${_tip('Your web-RDP URL with {host}/{token}/{vmid}/{node} placeholders.')}</label>
            <input id="ao-sb-tourl" class="settings-select" type="text" placeholder="https://guac.example.com/#/?host={host}&token={token}" value="${esc(conn.takeover_url_template || '')}" />
          </div>
        </div>
      </div>
      <details class="ao-adv">
        <summary>Advanced</summary>
        <div class="admin-card" style="margin-top:8px;">
          <div class="settings-col">
            <div class="settings-row">
              <label class="settings-label">Per-session mode</label>
              <select id="ao-sb-clone" class="settings-select">
                <option value="snapshot-revert"${(conn.clone_mode || 'snapshot-revert') === 'snapshot-revert' ? ' selected' : ''}>Reuse one VM, roll back each session</option>
                <option value="linked-clone"${conn.clone_mode === 'linked-clone' ? ' selected' : ''}>Fresh clone each session</option>
              </select>
            </div>
          </div>
        </div>
      </details>
    </div>
    <div class="admin-card" id="ao-desktop-card">
      <div class="settings-col">
        <div class="settings-row" style="align-items:flex-start;">
          <label class="settings-label">Desktop help ${_tip('Lets me handle steps outside the web page — like a file-upload dialog — while you watch. You stay in control: I never create accounts, clear verifications, or submit, and I ask before each step. You turn it on per live session.')}</label>
          <div style="display:flex;flex-direction:column;gap:6px;flex:1;">
            <button class="cal-btn" id="ao-desktop-toggle" type="button" disabled
                    title="Let me help with desktop steps the browser can't reach">Turn on</button>
            <p id="ao-desktop-note" style="margin:0;opacity:0.65;font-size:0.8rem;">
              Coming in a future update — desktop help isn’t set up on this browser yet.
            </p>
            <p style="margin:0;opacity:0.55;font-size:0.78rem;">
              Best-effort and optional. I only help with desktop steps you
              approve, one at a time — accounts, verifications, and the final
              submit always stay with you.
            </p>
          </div>
        </div>
      </div>
    </div>
    <div id="ao-sb-msg"></div>
  `);
  // #96: same Settings-vs-wizard footer wording fix as _renderChannels above.
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-sb-save">${_inSettingsContext ? 'Save' : 'Save &amp; continue'}</button>`);

  // Desktop help (FR-CUA) — present-but-grayed until the desktop helper is baked
  // into the sandbox image and the engine's health preflight passes. The actual
  // opt-in is per live session (in the live-session surface); here we surface the
  // capability + the honest best-effort caveat, and reflect the locked state.
  _renderDesktopAssistSetting().catch(e => console.error('Silent catch in applicantOnboarding:', e));

  const backendSel = document.getElementById('ao-sb-backend');
  const winBox = document.getElementById('ao-sb-win');
  backendSel.onchange = () => {
    winBox.style.display = (backendSel.value === 'proxmox-windows') ? 'block' : 'none';
  };

  // Take-over method toggles which one field-set is relevant (never both at once).
  const methodSel = document.getElementById('ao-sb-tomethod');
  if (methodSel) methodSel.onchange = () => {
    const web = methodSel.value === 'web-console';
    const rdpBox = document.getElementById('ao-sb-rdp');
    const webBox = document.getElementById('ao-sb-web');
    if (rdpBox) rdpBox.style.display = web ? 'none' : 'flex';
    if (webBox) webBox.style.display = web ? 'flex' : 'none';
  };

  const val = (id) => (document.getElementById(id).value || '').trim();

  document.getElementById('ao-sb-save').onclick = async () => {
    if (_busy) return;
    const msgEl = document.getElementById('ao-sb-msg');
    if (msgEl) msgEl.innerHTML = '';
    // Built-in sandbox: nothing to collect — the engine treats the step as done
    // for the local backend, so just advance.
    if (backendSel.value !== 'proxmox-windows') {
      _busy = true;
      document.getElementById('ao-sb-save').disabled = true;
      try { await _advanceAndContinue('sandbox'); }
      finally { _busy = false; }
      return;
    }
    const body = {
      proxmox_api_url: val('ao-sb-apiurl'),
      proxmox_node: val('ao-sb-node'),
      proxmox_token_id: val('ao-sb-tokenid'),
      proxmox_token_secret: val('ao-sb-tokensecret'),
      template_vmid: parseInt(val('ao-sb-vmid'), 10) || 0,
      clone_mode: val('ao-sb-clone') || 'snapshot-revert',
      rdp_username: val('ao-sb-rdpuser'),
      rdp_password: val('ao-sb-rdppass'),
      takeover_method: val('ao-sb-tomethod') || 'rdp',
      takeover_url_template: val('ao-sb-tourl'),
    };
    if (!body.proxmox_api_url || !body.proxmox_node || !body.template_vmid || !body.proxmox_token_id) {
      if (msgEl) msgEl.innerHTML = _err('Add the Proxmox API URL, node, token id and the VM ID to continue.');
      return;
    }
    _busy = true;
    document.getElementById('ao-sb-save').disabled = true;
    try {
      await _post(`${SETUP}/sandbox-connection`, body);
      await _advanceAndContinue('sandbox');
    } catch (e) {
      if (msgEl) msgEl.innerHTML = _err(esc(e.message || 'Could not save the sandbox connection.'));
      document.getElementById('ao-sb-save').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

// ── STEP 3: Fonts ───────────────────────────────────────────────────────────

// File inputs here LIFT fileHandler.js's picker (createPicker → openPicker /
// addFiles / renderAttachStrip preview chips + upload progress) instead of raw
// <input type=file>. The detect picker posts straight to /fonts/detect; each
// per-font install picker shows a chip then installs via /fonts/install.
async function _renderFonts() {
  let installed = [];
  try { const f = await _fetchJSON(`${SETUP}/fonts`); installed = f.installed || []; } catch { installed = []; }
  _setBody(`
    <h2 class="ao-step-title">Fonts ${_tip('To make your generated résumé look exactly like yours, Applicant may need the fonts your résumé uses. Upload a résumé to check, then add any missing fonts. This step is optional — you can skip it.')}</h2>
    <p class="ao-step-desc">Optional: check which fonts your résumé needs and add any that are missing, so your generated résumé keeps its look.</p>
    <div class="admin-card">
      <div class="settings-col">
        <label class="settings-label" style="min-width:0;">Check a résumé for required fonts</label>
        <div class="settings-row">
          <button type="button" class="cal-btn" id="ao-font-pick">Choose a résumé…</button>
          <input id="ao-font-detect" type="file" accept=".docx,.doc,.pdf,.rtf,.txt" style="display:none;" />
        </div>
        <div class="attach-strip" id="ao-font-strip"></div>
      </div>
    </div>
    <div id="ao-font-report"></div>
    <p style="font-size:0.82rem;opacity:0.7;margin:12px 0 0;">Installed fonts: <span id="ao-font-installed">${installed.length ? esc(installed.join(', ')) : 'none yet'}</span></p>
    <div id="ao-font-msg"></div>
  `);
  // #96: "Skip for now" / "Continue" are wizard-navigation labels — both used to
  // fire the exact same handler in EVERY context, so inside Settings they read as
  // two buttons doing an identical, meaningless thing (there's no wizard step to
  // skip or continue to). Collapse to one plain "Save" there.
  _setFoot(_inSettingsContext
    ? '<button class="cal-btn cal-btn-primary" id="ao-font-continue">Save</button>'
    : `
    <button class="cal-btn" id="ao-font-skip">Skip for now</button>
    <button class="cal-btn cal-btn-primary" id="ao-font-continue">Continue</button>
  `);

  // Detect picker — lifts fileHandler: a chip preview + upload-progress whirlpool,
  // pointed at /fonts/detect (single `file` field).
  const detectPicker = fileHandlerModule.createPicker({
    inputEl: 'ao-font-detect',
    stripEl: 'ao-font-strip',
    uploadUrl: `${SETUP}/fonts/detect`,
    fieldName: 'file',
    maxFiles: 1,
    onChange: (p) => { if (p.getPendingCount()) runDetect(p); },
  });
  document.getElementById('ao-font-pick').onclick = () => detectPicker.openPicker();
  document.getElementById('ao-font-detect').onchange = (ev) => {
    if (ev.target.files && ev.target.files.length) detectPicker.addFiles(ev.target.files);
    ev.target.value = '';
  };

  async function runDetect(picker) {
    const report = document.getElementById('ao-font-report');
    report.innerHTML = '<p style="font-size:0.82rem;opacity:0.75;">Checking…</p>';
    try {
      await picker.uploadPending();      // shows the chip + progress, posts to /fonts/detect
      const res = picker.getLastResponse() || {};
      const missing = res.missing || [];
      if (!missing.length) {
        report.innerHTML = '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">All required fonts are already installed.</p>';
        return;
      }
      report.innerHTML = `
        <p style="color:var(--accent-warm, #d8a23a);font-size:0.86rem;margin:8px 0;">Missing fonts: ${esc(missing.join(', '))}</p>
        ${missing.map((m, i) => `
          <div class="admin-card ao-font-install" data-font="${esc(m)}" data-i="${i}">
            <label class="settings-label" style="min-width:0;">Upload font file for <strong>${esc(m)}</strong></label>
            <div class="settings-row" style="margin-top:6px;">
              <button type="button" class="cal-btn ao-font-pick" data-i="${i}">Choose font file…</button>
              <input type="file" accept=".ttf,.otf" class="ao-font-file" data-i="${i}" style="display:none;" />
            </div>
            <div class="attach-strip ao-font-install-strip" id="ao-font-install-strip-${i}"></div>
          </div>`).join('')}
      `;
      report.querySelectorAll('.ao-font-install').forEach((wrap) => {
        const name = wrap.getAttribute('data-font');
        const input = wrap.querySelector('.ao-font-file');
        // Per-font install picker — same fileHandler chip + progress UX, posting
        // through uploadPending() to /fonts/install with the extra `name` field.
        const fontPicker = fileHandlerModule.createPicker({
          inputEl: input,
          stripEl: wrap.querySelector('.ao-font-install-strip'),
          uploadUrl: `${SETUP}/fonts/install`,
          fieldName: 'file',
          extraFields: { name },
          maxFiles: 1,
          onChange: (p) => { if (p.getPendingCount()) installFont(wrap, name, p); },
        });
        wrap.querySelector('.ao-font-pick').onclick = () => fontPicker.openPicker();
        input.onchange = (e2) => {
          if (e2.target.files && e2.target.files.length) fontPicker.addFiles(e2.target.files);
          e2.target.value = '';
        };
      });
    } catch (e) {
      report.innerHTML = _err(esc(e.message || 'Could not check fonts.'));
    }
  }

  async function installFont(wrap, name, picker) {
    if (!picker.getPendingCount()) return;
    try {
      await picker.uploadPending();      // chip + progress whirlpool, posts to /fonts/install
      const ir = picker.getLastResponse() || {};
      document.getElementById('ao-font-installed').textContent = (ir.installed || []).join(', ') || 'none yet';
      wrap.innerHTML = `<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Installed ${esc(name)}.</p>`;
    } catch (e3) {
      document.getElementById('ao-font-msg').innerHTML = _err(esc(e3.message || 'Could not install font.'));
    }
  }

  const finishFonts = async () => {
    if (_busy) return;
    _busy = true;
    try { await _advanceAndContinue('fonts'); }
    finally { _busy = false; }
  };
  // #96: the skip button doesn't exist in Settings context (see the _setFoot
  // call above) — guard rather than assume it's present.
  const fontSkipBtn = document.getElementById('ao-font-skip');
  if (fontSkipBtn) fontSkipBtn.onclick = finishFonts;
  document.getElementById('ao-font-continue').onclick = finishFonts;
}

// ── STEP 4: Onboarding intake (resumable interview) ─────────────────────────

// Per-section form fields. Kept plain-language. Each field: {name, label, type}.
// D47: a compact common-country list for the work-authorization datalist — a
// plain suggestion list (the input stays free text so nothing is blocked),
// just enough to steer "USA"/"United States"/"US" toward one spelling.
const _COMMON_COUNTRIES = [
  'United States', 'Canada', 'United Kingdom', 'Ireland', 'Germany', 'France',
  'Spain', 'Italy', 'Netherlands', 'Portugal', 'Poland', 'Sweden', 'Norway',
  'Denmark', 'Switzerland', 'Australia', 'New Zealand', 'India', 'Singapore',
  'Japan', 'South Korea', 'Philippines', 'Mexico', 'Brazil', 'South Africa',
];

const SECTION_FORMS = {
  identity: {
    title: 'About you',
    fields: [
      { name: 'full_legal_name', label: 'Full legal name', type: 'text' },
      { name: 'preferred_name', label: 'Preferred name', type: 'text' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'phone', label: 'Phone', type: 'tel', placeholder: '+1 555-555-5555' },
      { name: 'address', label: 'Mailing address', type: 'text' },
      { name: 'linkedin', label: 'LinkedIn URL', type: 'text', placeholder: 'linkedin.com/in/you' },
      { name: 'portfolio', label: 'Portfolio / GitHub URL', type: 'text', placeholder: 'github.com/you' },
    ],
  },
  work_authorization: {
    title: 'Work authorization',
    fields: [
      { name: 'authorized_country', label: 'Country you are authorized to work in', type: 'text', list: 'ao-countries', listOptions: _COMMON_COUNTRIES },
      { name: 'authorized', label: 'Authorized to work there?', type: 'yesno' },
      { name: 'needs_sponsorship', label: 'Will you need visa sponsorship now or in the future?', type: 'yesno' },
      { name: 'visa_status', label: 'Visa / status type (if any)', type: 'text' },
    ],
  },
  location: {
    title: 'Location & work mode',
    fields: [
      { name: 'current_location', label: 'Current location', type: 'text' },
      { name: 'willing_to_relocate', label: 'Willing to relocate?', type: 'yesno' },
      { name: 'work_mode', label: 'Preferred work mode (remote / hybrid / onsite)', type: 'text' },
      { name: 'timezone', label: 'Time zone / hours constraints', type: 'text' },
    ],
  },
  target_roles: {
    title: 'Target roles',
    fields: [
      { name: 'titles', label: 'Target job titles (comma-separated)', type: 'text' },
      { name: 'seniority', label: 'Seniority level(s)', type: 'text' },
      { name: 'adjacent_titles', label: 'Other acceptable titles', type: 'text' },
    ],
  },
  compensation: {
    title: 'Compensation',
    // D50: numbers only + a real currency picker (was three unlinked free-text
    // fields, e.g. "$120k" / "120,000" / "120000 usd" all landing differently in
    // the comparator that filters postings), plus a one-line privacy note so the
    // ask doesn't read as a black box.
    desc: 'Numbers only, no symbols. Postings below your floor are filtered out of discovery — this is never shared with an employer unless their own application form asks for it.',
    fields: [
      { name: 'salary_floor', label: 'Salary floor (hard minimum)', type: 'number', placeholder: 'e.g. 120000' },
      { name: 'desired_salary', label: 'Desired salary / range', type: 'text', placeholder: 'e.g. 140000-160000' },
      { name: 'currency', label: 'Currency', type: 'select', options: ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'Other'] },
    ],
  },
  work_history: {
    title: 'Work history',
    desc: 'Add your roles, most recent first. Dates matter for applications.',
    repeat: true,
    fields: [
      { name: 'title', label: 'Job title', type: 'text' },
      { name: 'company', label: 'Company', type: 'text' },
      { name: 'location', label: 'Location', type: 'text' },
      { name: 'start_date', label: 'Start (MM/YYYY)', type: 'text' },
      { name: 'end_date', label: 'End (MM/YYYY or present)', type: 'text' },
      { name: 'employment_type', label: 'Type (full-time/contract/…)', type: 'text' },
      { name: 'highlights', label: 'Key responsibilities & achievements', type: 'textarea' },
    ],
  },
  education: {
    title: 'Education',
    repeat: true,
    fields: [
      { name: 'degree', label: 'Degree & field', type: 'text' },
      { name: 'institution', label: 'Institution', type: 'text' },
      { name: 'start_year', label: 'Start year', type: 'text' },
      { name: 'end_year', label: 'End year (or expected)', type: 'text' },
    ],
  },
  references: {
    title: 'References',
    // #25: the "+ Add another …" button lowercases `title` for its label, which
    // reads fine for the mass nouns "work history"/"education" but produced the
    // grammatically-off "+ Add another references" for this plural section title
    // — `addLabel` gives the singular form the button actually needs.
    addLabel: 'reference',
    // D52: references are needed by only a minority of applications, and only at
    // submit time — not before first value — so this section now sits LAST in
    // INTAKE_SECTIONS (see the reorder note there) and says so plainly.
    desc: 'Most applications don’t ask for these up front. Add them now, or skip — Applicant will ask only when a specific application actually needs one.',
    // ON-S2-5: this section's own copy above says it's OK to leave blank, so
    // an empty References must not hard-block "Save & continue" the way a
    // required section does — see the `optional` check in
    // _nextIntakeOrComplete()'s missing_sections handling.
    optional: true,
    repeat: true,
    fields: [
      { name: 'name', label: 'Name', type: 'text' },
      { name: 'relationship', label: 'Relationship / title', type: 'text' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'phone', label: 'Phone', type: 'tel', placeholder: '+1 555-555-5555' },
    ],
  },
  key_attributes: {
    title: 'Skills & strengths',
    fields: [
      { name: 'technical_skills', label: 'Technical skills', type: 'textarea' },
      { name: 'strengths', label: 'Strengths / behavioral profile', type: 'textarea' },
      { name: 'motivations', label: 'What excites you / motivations', type: 'textarea' },
    ],
  },
  eeo: {
    title: 'Voluntary self-identification',
    desc: 'Entirely optional. The default for every field is "decline to self-identify" — I never guess these.',
    fields: [
      { name: 'race_ethnicity', label: 'Race / ethnicity', type: 'eeo' },
      { name: 'gender', label: 'Gender', type: 'eeo' },
      { name: 'veteran_status', label: 'Veteran status', type: 'eeo' },
      { name: 'disability_status', label: 'Disability status', type: 'eeo' },
    ],
  },
  campaign_criteria: {
    title: 'What you’re looking for',
    fields: [
      { name: 'criteria', label: 'Describe your ideal next role (free text)', type: 'textarea' },
      { name: 'target_sectors', label: 'Target sectors / example companies', type: 'text' },
      { name: 'deal_breakers', label: 'Deal-breakers / hard constraints', type: 'text' },
    ],
  },
};

let _intakeIndex = 0; // index into INTAKE_SECTIONS currently shown

// D83: the resumable intake's own sub-progress line. Worded as "section" (not
// "step") so it reads as a finer-grained count WITHIN the rail's "Your profile"
// step rather than a second, conflicting "step N of M" counter next to the
// rail's own "Step N of 3" (see _renderRail).
function _intakeProgressHTML(total) {
  return `<div class="ao-intake-progress">Your profile — section ${_intakeIndex + 1} of ${total}</div>`;
}

// Intake fields reuse the shared `.settings-col`/`.settings-label`/
// `.settings-select` form classes (same as Settings' field rows), so inputs,
// selects and textareas match the rest of the app and track the theme.
function _fieldHTML(f, value, detailValue) {
  const v = value == null ? '' : value;
  if (f.type === 'textarea') {
    // ON-S3-5: 3 rows clipped a realistic answer (e.g. a real "Technical
    // skills" list) on first view, hiding content the user had to scroll a
    // tiny box to discover was even there. 6 rows shows a full skills/
    // highlights list up front; `resize:vertical` still lets it grow further.
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label><textarea class="settings-select" name="${esc(f.name)}" rows="6" style="resize:vertical;">${esc(v)}</textarea></div>`;
  }
  if (f.type === 'yesno') {
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label>
      <select class="settings-select" name="${esc(f.name)}">
        <option value=""${v === '' ? ' selected' : ''}>—</option>
        <option value="yes"${v === 'yes' ? ' selected' : ''}>Yes</option>
        <option value="no"${v === 'no' ? ' selected' : ''}>No</option>
      </select></div>`;
  }
  if (f.type === 'eeo') {
    // Sentence-case labels for display (D-lens02 #81); the underlying value
    // sent to/read from the engine stays the original lowercase string so
    // previously-saved answers still match on re-render.
    const opts = [
      { value: 'decline to self-identify', label: 'Decline to self-identify' },
      { value: 'prefer to answer', label: 'Prefer to answer' },
    ];
    // Micro-interactions lens 01 #22: the free-text detail used to render blank
    // every time (a saved answer vanished on Back/resume) and stayed visible even
    // while "Decline to self-identify" was selected, inviting text the selection
    // says will be ignored. Rehydrate it from the saved `${name}__detail` value
    // and only show it when the answer is actually "Prefer to answer".
    const dv = detailValue == null ? '' : detailValue;
    const showDetail = (v || 'decline to self-identify') === 'prefer to answer';
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label>
      <select class="settings-select" name="${esc(f.name)}" data-eeo-select="${esc(f.name)}">
        ${opts.map((o) => `<option value="${esc(o.value)}"${(v || 'decline to self-identify') === o.value ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}
      </select>
      <input class="settings-select" name="${esc(f.name)}__detail" type="text" placeholder="Your answer (optional)" value="${esc(dv)}" style="margin-top:6px;${showDetail ? '' : 'display:none;'}" data-eeo-detail="${esc(f.name)}" />
      </div>`;
  }
  // D50 (compensation, currency): a small closed-option dropdown, same card/label
  // shell as every other field — used instead of free text so "USD"/"US dollars"/
  // "120000 usd" never fragments the comparator that filters postings on it.
  if (f.type === 'select' && Array.isArray(f.options)) {
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label>
      <select class="settings-select" name="${esc(f.name)}">
        ${f.options.map((o) => `<option value="${esc(o)}"${v === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}
      </select></div>`;
  }
  // D45/D47: optional `placeholder` (e.g. phone) and `list` (a datalist id, e.g.
  // the work-authorization country field) on an otherwise plain input — additive,
  // every existing field spec that doesn't set them renders exactly as before.
  const placeholderAttr = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : '';
  const listAttr = f.list ? ` list="${esc(f.list)}"` : '';
  const datalistHTML = (f.list && Array.isArray(f.listOptions))
    ? `<datalist id="${esc(f.list)}">${f.listOptions.map((o) => `<option value="${esc(o)}"></option>`).join('')}</datalist>`
    : '';
  // Micro-interactions lens 01 #21: give mobile keyboards a hint from the
  // field's own `type` (email/tel already set the right virtual keyboard in
  // most browsers; `autocomplete` is the extra nudge some browsers key off
  // instead) — additive, every other field type is unaffected.
  const autocompleteAttr = f.type === 'email' ? ' autocomplete="email"'
    : f.type === 'tel' ? ' autocomplete="tel"'
    : f.type === 'number' ? ' inputmode="numeric"'
    : '';
  return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label><input class="settings-select" type="${esc(f.type)}" name="${esc(f.name)}" value="${esc(v)}"${placeholderAttr}${listAttr}${autocompleteAttr} />${datalistHTML}</div>`;
}

// D46: LinkedIn/portfolio URLs typed without a scheme ("linkedin.com/in/me")
// save as unusable strings for anything that later treats them as a link
// (e.g. a pre-fill form field). Normalize just these two well-known field
// names on the way into the saved payload — a no-op for every other field.
function _maybeNormalizeUrl(name, value) {
  if ((name === 'linkedin' || name === 'portfolio') && value && !/^https?:\/\//i.test(value)) {
    return 'https://' + value.replace(/^\/+/, '');
  }
  return value;
}

function _collectForm(formEl) {
  const out = {};
  formEl.querySelectorAll('input, textarea, select').forEach((inp) => {
    if (!inp.name) return;
    out[inp.name] = _maybeNormalizeUrl(inp.name, inp.value);
  });
  return out;
}

// ── repeatable sections (work history / education / references) ────────────
//
// A `repeat: true` section spec (SECTION_FORMS.work_history/education/references)
// can hold MULTIPLE entries (e.g. several jobs). Each entry renders as its own
// `.admin-card` fieldset — the same card pattern the per-font install prompt
// above already uses for a dynamic list (_renderInlineFontPrompt) — with a
// "Remove" affordance (`.admin-btn-delete`, matching admin.js's list-item
// remove buttons) so a mistakenly-added entry can be deleted again. Saved data
// is sent as `{ entries: [...] }` rather than a single flat object.

// Normalizes whatever is currently saved for a repeat section into an array of
// entries to render. Handles three shapes: the `{entries: [...]}` shape this file
// saves back (and the engine's resume-parse prefill now also writes, carrying
// EVERY parsed role/degree — not just the most recent), an older flat
// single-object shape (a pre-fix prefill record, or any other single-object
// write), and nothing saved yet.
function _repeatEntries(saved) {
  if (saved && Array.isArray(saved.entries) && saved.entries.length) return saved.entries;
  if (saved && Object.keys(saved).length && !Array.isArray(saved.entries)) return [saved];
  return [{}];
}

function _repeatEntryCard(spec, entry, idx) {
  return `
    <div class="admin-card ao-repeat-entry" data-idx="${idx}">
      <div class="settings-row" style="justify-content:space-between;align-items:center;margin-bottom:6px;">
        <strong class="ao-repeat-label" style="font-size:0.86rem;opacity:0.75;">${esc(spec.title)} ${idx + 1}</strong>
        <button type="button" class="admin-btn-delete ao-repeat-remove" style="font-size:11px;">Remove</button>
      </div>
      ${spec.fields.map((f) => _fieldHTML(f, entry[f.name])).join('')}
    </div>`;
}

// Renumber the "<Section> N" labels and hide the last remaining Remove button
// (always keep at least one fieldset on screen) after any add/remove.
function _refreshRepeatUI(listEl, spec) {
  const cards = listEl.querySelectorAll('.ao-repeat-entry');
  cards.forEach((card, i) => {
    const label = card.querySelector('.ao-repeat-label');
    if (label) label.textContent = `${spec.title} ${i + 1}`;
    const rm = card.querySelector('.ao-repeat-remove');
    if (rm) rm.style.display = cards.length > 1 ? '' : 'none';
  });
}

function _wireRepeatRemove(listEl, spec) {
  listEl.querySelectorAll('.ao-repeat-remove').forEach((btn) => {
    btn.onclick = () => {
      if (listEl.querySelectorAll('.ao-repeat-entry').length <= 1) return;
      _formDirty = true;
      btn.closest('.ao-repeat-entry').remove();
      _refreshRepeatUI(listEl, spec);
    };
  });
}

// Collects every rendered entry into an ARRAY (one object per fieldset), reusing
// _collectForm per-entry since each `.ao-repeat-entry` card is itself a valid
// collection root. Entries the user left entirely blank (e.g. an "Add another"
// they didn't end up filling in) are dropped so an untouched repeat section
// still correctly reads back as not-yet-filled.
function _collectRepeatEntries(listEl) {
  const out = [];
  listEl.querySelectorAll('.ao-repeat-entry').forEach((entryEl) => {
    const entry = _collectForm(entryEl);
    if (Object.values(entry).some((v) => (v || '').toString().trim() !== '')) out.push(entry);
  });
  return out;
}

// #19: a real "Skip for now" affordance for every intake section's footer. The
// résumé step's body copy already promised one ("Use Skip for now…") but no
// footer control matched it — and now that the persistent nav bar is hidden for
// the whole "Your profile" step (#18, see _renderNav), there's no other way to
// bail out of it. "Your profile" is optional (STEPS' own `required: false`), so
// jumping straight to the finish screen is a fully supported path: whatever was
// already saved stays saved, and a later reopen resumes at the first section
// still incomplete.
function _intakeSkipButtonHTML() {
  return '<button type="button" class="cal-btn" id="ao-intake-skip">Skip for now</button>';
}

function _wireIntakeSkip() {
  const btn = document.getElementById('ao-intake-skip');
  if (btn) btn.onclick = () => { if (!_busy) _finish(); };
}

function _renderRepeatSection(key, spec, saved) {
  const total = INTAKE_SECTIONS.length;
  const entries = _repeatEntries(saved);
  _setBody(`
    ${_intakeProgressHTML(total)}
    <h2 class="ao-step-title">${esc(spec.title)}</h2>
    ${spec.desc ? `<p class="ao-step-desc">${esc(spec.desc)}</p>` : ''}
    <div id="ao-repeat-list">${entries.map((e, i) => _repeatEntryCard(spec, e, i)).join('')}</div>
    <button type="button" class="cal-btn" id="ao-repeat-add" style="margin-top:8px;">+ Add another ${esc(spec.addLabel || spec.title.toLowerCase())}</button>
    <div id="ao-intake-msg"></div>
  `);
  _setFoot(`
    ${_intakeIndex > 0 ? '<button class="cal-btn" id="ao-intake-back">Back</button>' : ''}
    ${_intakeSkipButtonHTML()}
    <button class="cal-btn cal-btn-primary" id="ao-intake-next">Save &amp; continue</button>
  `);
  _wireIntakeSkip();

  const list = document.getElementById('ao-repeat-list');
  _wireRepeatRemove(list, spec);
  _refreshRepeatUI(list, spec);

  document.getElementById('ao-repeat-add').onclick = () => {
    const idx = list.querySelectorAll('.ao-repeat-entry').length;
    list.insertAdjacentHTML('beforeend', _repeatEntryCard(spec, {}, idx));
    _wireRepeatRemove(list, spec);
    _refreshRepeatUI(list, spec);
  };

  const back = document.getElementById('ao-intake-back');
  if (back) back.onclick = () => { _intakeIndex = Math.max(0, _intakeIndex - 1); _renderIntakeSection(); };

  document.getElementById('ao-intake-next').onclick = async () => {
    if (_busy) return;
    _busy = true;
    document.getElementById('ao-intake-next').disabled = true;
    try {
      const data = { entries: _collectRepeatEntries(list) };
      _onboarding = await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/section`, {
        section: key, data,
      });
      await _nextIntakeOrComplete();
    } catch (e) {
      document.getElementById('ao-intake-msg').innerHTML = _err(esc(e.message || 'Could not save.'));
      document.getElementById('ao-intake-next').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

async function _renderOnboarding() {
  await _ensureCampaign();
  _onboarding = await _fetchJSON(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}`);
  // Best-effort refresh of the profile-completeness checklist (item 51) each time
  // this step is (re)entered, so it reflects the latest attribute/criteria state.
  // Never lets a fetch failure block the intake itself.
  try {
    _profileGaps = await _fetchJSON(`${SETUP}/gaps/${encodeURIComponent(_campaignId)}`);
  } catch {
    _profileGaps = null;
  }
  const done = new Set(_onboarding.sections_complete || []);
  // Resume at the first incomplete intake section.
  _intakeIndex = INTAKE_SECTIONS.findIndex((s) => !done.has(s));
  if (_intakeIndex < 0) _intakeIndex = INTAKE_SECTIONS.length - 1;
  await _renderIntakeSection();
}

// A plain banner showing what Applicant still needs before it can start applying,
// straight from the engine's setup status (apply_missing / apply_blocked_reason).
// It is honest progress, never fabricated. Returns '' when nothing is missing or
// the engine didn't report readiness (older engine) so the wizard degrades cleanly.
function _applyReadinessBanner() {
  const s = _status || {};
  if (s.apply_ready) {
    return `<div class="admin-card" style="border-left:3px solid var(--accent-ok, #4a9);">
      <p style="margin:0;font-size:0.86rem;">I have what I need to start applying. Anything else here just makes your applications smoother — it’s all optional.</p>
    </div>`;
  }
  const missing = Array.isArray(s.apply_missing) ? s.apply_missing : [];
  if (!missing.length) return '';
  return `<div class="admin-card" style="border-left:3px solid var(--accent-warm, #d8a23a);">
    <p style="margin:0 0 4px;font-size:0.86rem;"><strong>This part is optional.</strong> Add a résumé to fill it in fast, or just tell me in chat — I’ll keep learning as you go.</p>
    <p style="margin:0;font-size:0.84rem;opacity:0.85;">Before I can start applying, I still need: ${esc(missing.join(', '))}.</p>
  </div>`;
}

// A visible profile-completeness checklist (dark-engine audit item 51): the SAME
// gap list the assistant chat already computes internally (core attributes like
// name/email/phone/title, plus whether search criteria are set) — previously only
// used as hidden LLM context, now surfaced here so a user reviewing "Your profile"
// can see at a glance what's still missing without opening chat. Best-effort: ''
// until fetched, on a fetch failure, or once nothing is missing, so it degrades
// cleanly like _applyReadinessBanner and never blocks the wizard.
function _profileGapsHTML() {
  const g = _profileGaps;
  if (!g || g.complete || !Array.isArray(g.gaps) || !g.gaps.length) return '';
  return `<div class="admin-card" id="ao-profile-gaps" style="border-left:3px solid var(--accent-warm, #d8a23a);">
    <p style="margin:0 0 4px;font-size:0.86rem;"><strong>Still missing from your profile:</strong></p>
    <ul style="margin:0;padding-left:18px;font-size:0.84rem;opacity:0.85;">
      ${g.gaps.map((item) => `<li>${esc(item)}</li>`).join('')}
    </ul>
  </div>`;
}

async function _renderIntakeSection() {
  const key = INTAKE_SECTIONS[_intakeIndex];
  // #52: scope the draft per intake section (not just 'onboarding') so each
  // section's typed answers persist/restore independently.
  _draftScope = `onboarding:${key}`;
  const total = INTAKE_SECTIONS.length;
  const saved = (_onboarding.intake && _onboarding.intake[key]) || {};

  if (key === 'base_resume') return _renderBaseResume(saved);

  const spec = SECTION_FORMS[key];
  if (spec.repeat) return _renderRepeatSection(key, spec, saved);

  const fieldsHTML = spec.fields.map((f) => _fieldHTML(f, saved[f.name], saved[`${f.name}__detail`])).join('');
  _setBody(`
    ${_intakeProgressHTML(total)}
    <h2 class="ao-step-title">${esc(spec.title)}</h2>
    ${spec.desc ? `<p class="ao-step-desc">${esc(spec.desc)}</p>` : ''}
    <form id="ao-intake-form">${fieldsHTML}</form>
    <div id="ao-intake-msg"></div>
  `);
  _setFoot(`
    ${_intakeIndex > 0 ? '<button class="cal-btn" id="ao-intake-back">Back</button>' : ''}
    ${_intakeSkipButtonHTML()}
    <button class="cal-btn cal-btn-primary" id="ao-intake-next">Save &amp; continue</button>
  `);
  _wireIntakeSkip();

  // Micro-interactions lens 01 #22: toggle each EEO detail input's visibility
  // with its own select (rehydration itself happens in _fieldHTML above).
  document.querySelectorAll('[data-eeo-select]').forEach((sel) => {
    sel.onchange = () => {
      const input = document.querySelector(`[data-eeo-detail="${sel.getAttribute('data-eeo-select')}"]`);
      if (input) input.style.display = sel.value === 'prefer to answer' ? '' : 'none';
    };
  });

  const back = document.getElementById('ao-intake-back');
  if (back) back.onclick = () => { _intakeIndex = Math.max(0, _intakeIndex - 1); _renderIntakeSection(); };

  // Micro-interactions lens 01 #23: the intake `<form>` had no submit handler,
  // so plain Enter in a single-input section fell through to the browser's
  // implicit-submission default (a page-navigating GET) instead of advancing
  // the wizard like the persistent Save & continue button does.
  const intakeForm = document.getElementById('ao-intake-form');
  if (intakeForm) intakeForm.onsubmit = (e) => {
    e.preventDefault();
    const next = document.getElementById('ao-intake-next');
    if (next && !next.disabled) next.click();
  };
  // Focus the first field so a keyboard/resumed user can start typing right away.
  const firstField = intakeForm && intakeForm.querySelector('input, textarea, select');
  if (firstField) firstField.focus();

  document.getElementById('ao-intake-next').onclick = async () => {
    if (_busy) return;
    _busy = true;
    document.getElementById('ao-intake-next').disabled = true;
    try {
      const data = _collectForm(document.getElementById('ao-intake-form'));
      _onboarding = await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/section`, {
        section: key, data,
      });
      await _nextIntakeOrComplete();
    } catch (e) {
      document.getElementById('ao-intake-msg').innerHTML = _err(esc(e.message || 'Could not save.'));
      document.getElementById('ao-intake-next').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

// Inline font-install prompt surfaced in the resume upload step when the engine
// reports missing fonts (FR-FONT-1).  Reuses the per-font picker + install
// pattern from _renderFonts, but rendered inside the upload step rather than
// as a separate wizard step.
function _renderInlineFontPrompt(missing) {
  const st = document.getElementById('ao-resume-status');
  const prev = document.getElementById('ao-preview');
  if (prev) prev.innerHTML = '';
  st.innerHTML = `
    <p style="color:var(--accent-warm, #d8a23a);font-size:0.86rem;margin:8px 0;">
      Your résumé uses fonts that aren’t installed yet. Add them below so your
      generated résumé keeps its look.
    </p>
    <p style="font-size:0.82rem;opacity:0.7;">Missing: ${esc(missing.join(', '))}</p>
    ${missing.map((m, i) => `
      <div class="admin-card ao-font-install" data-font="${esc(m)}" data-i="${i}">
        <label class="settings-label" style="min-width:0;">Upload font file for <strong>${esc(m)}</strong></label>
        <div class="settings-row" style="margin-top:6px;">
          <button type="button" class="cal-btn ao-font-pick" data-i="${i}">Choose font file…</button>
          <input type="file" accept=".ttf,.otf" class="ao-font-file" data-i="${i}" style="display:none;" />
        </div>
        <div class="attach-strip ao-font-install-strip" id="ao-font-install-strip-${i}"></div>
      </div>`).join('')}
    <button class="cal-btn cal-btn-primary" id="ao-font-done" style="margin-top:10px;" disabled>Continue</button>
  `;

  let installedCount = 0;
  st.querySelectorAll('.ao-font-install').forEach((wrap) => {
    const name = wrap.getAttribute('data-font');
    const input = wrap.querySelector('.ao-font-file');
    const fontPicker = fileHandlerModule.createPicker({
      inputEl: input,
      stripEl: wrap.querySelector('.ao-font-install-strip'),
      uploadUrl: `${SETUP}/fonts/install?name=${encodeURIComponent(name)}`,
      fieldName: 'file',
      maxFiles: 1,
      onChange: async (p) => {
        if (!p.getPendingCount()) return;
        try {
          await p.uploadPending();
          installedCount++;
          if (installedCount >= missing.length) {
            document.getElementById('ao-font-done').disabled = false;
          }
        } catch (e) {
          _toast(e.message || 'Could not install font.');
        }
      },
    });
    wrap.querySelector('.ao-font-pick').onclick = () => fontPicker.openPicker();
    input.onchange = (ev) => {
      if (ev.target.files && ev.target.files.length) fontPicker.addFiles(ev.target.files);
      ev.target.value = '';
    };
  });

  document.getElementById('ao-font-done').onclick = async () => {
    st.innerHTML = '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Fonts installed — continuing to preview.</p>';
    // Refresh the font list so the engine cache is current.
    try { await _fetchJSON(`${SETUP}/fonts`); } catch { /* best-effort */ }
    // The preview is a nice-to-have fidelity check, not a hard gate — a missing
    // xelatex/LibreOffice on the deployed image (or any other preview failure)
    // must never wedge the wizard. _buildPreview() already renders its own
    // "Preview unavailable: …" message internally on failure; Continue is
    // enabled in `finally` unconditionally so it's never left permanently
    // disabled by a broken preview.
    try {
      await _buildPreview();
    } finally {
      document.getElementById('ao-resume-next').disabled = false;
    }
  };
}

// The resume upload LIFTS fileHandler.js's picker (chip preview + upload-progress
// whirlpool), pointed at the existing /base-resume engine proxy.
function _renderBaseResume(saved) {
  const total = INTAKE_SECTIONS.length;
  _setBody(`
    ${_intakeProgressHTML(total)}
    ${_applyReadinessBanner()}
    ${_profileGapsHTML()}
    <h2 class="ao-step-title">Start with your résumé ${_tip('I read your résumé and fill in the rest of your profile — you just review and fix anything I got wrong. Then, if this install can render documents, I build a polished version and show you a preview to accept or reject — and if it can’t, I say so and keep using your original file.')}</h2>
    <p class="ao-step-desc">Optional but recommended: upload your current résumé and I’ll read it to fill in the profile fields that follow — so you don’t have to type everything by hand. Prefer to skip it? Use <strong>Skip for now</strong> and just tell me what you want in chat. You can edit every field afterward.</p>
    <div class="admin-card">
      <div class="settings-row">
        <button type="button" class="cal-btn" id="ao-resume-pick">Choose your résumé…</button>
        <input id="ao-resume-file" type="file" accept=".docx,.doc,.pdf,.rtf,.txt,.md" style="display:none;" />
      </div>
      <div class="attach-strip" id="ao-resume-strip"></div>
    </div>
    <div id="ao-resume-status">${saved && saved.document_path ? '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">A résumé is already on file. Re-upload to replace it.</p>' : ''}</div>
    <div id="ao-conflicts"></div>
    <div id="ao-preview"></div>
    <div id="ao-resume-msg"></div>
  `);
  _setFoot(`
    ${_intakeIndex > 0 ? '<button class="cal-btn" id="ao-intake-back">Back</button>' : ''}
    ${_intakeSkipButtonHTML()}
    <button class="cal-btn cal-btn-primary" id="ao-resume-next" ${saved && saved.document_path ? '' : 'disabled'}>Continue</button>
  `);
  _wireIntakeSkip();

  // ON-S3-1: this is INTAKE_SECTIONS[0] ("section 1 of N") — same
  // _intakeIndex > 0 guard every other intake section already applies to
  // its own Back button (see _renderRepeatSection/_renderIntakeSection),
  // so section 1 no longer shows an always-enabled Back that's a silent
  // no-op (_intakeIndex can't go below 0).
  const back = document.getElementById('ao-intake-back');
  if (back) back.onclick = () => {
    _intakeIndex = Math.max(0, _intakeIndex - 1); _renderIntakeSection();
  };

  // Resume picker — same fileHandler chip/preview/progress UX, posting to the
  // existing /base-resume proxy (single `file` field).
  const resumePicker = fileHandlerModule.createPicker({
    inputEl: 'ao-resume-file',
    stripEl: 'ao-resume-strip',
    uploadUrl: `${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/base-resume`,
    fieldName: 'file',
    maxFiles: 1,
    onChange: (p) => { if (p.getPendingCount()) readResume(p); },
  });
  document.getElementById('ao-resume-pick').onclick = () => resumePicker.openPicker();
  document.getElementById('ao-resume-file').onchange = (ev) => {
    if (ev.target.files && ev.target.files.length) resumePicker.addFiles(ev.target.files);
    ev.target.value = '';
  };

  async function readResume(picker) {
    const st = document.getElementById('ao-resume-status');
    st.innerHTML = '<p style="font-size:0.82rem;opacity:0.75;">Reading your résumé…</p>';
    try {
      await picker.uploadPending();      // chip + progress whirlpool, posts to /base-resume
      const res = picker.getLastResponse() || {};
      // Resume-first: re-fetch the intake so the upcoming steps render PREFILLED
      // with what we read (identity, work history, education, skills) — the user
      // reviews + corrects rather than typing from scratch.
      try {
        _onboarding = await _fetchJSON(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}`);
      } catch { /* keep last-known intake; prefill is best-effort */ }
      // HONESTY: the count is what THIS parse actually extracted
      // (parsed_field_count, engine-derived) — not the whole profile's attribute
      // count — and a near-empty parse must read as a warning, not a success.
      st.innerHTML = `${_resumeReadSummaryHTML(res)}${_parseVerifyHTML(res)}${_resumeHealthHTML(res)}`;
      if (res.requires_confirmation && (res.conflicts || []).length) {
        _renderConflicts(res.conflicts);
      } else {
        document.getElementById('ao-conflicts').innerHTML = '';
      }

      // FR-FONT-1: detect required fonts and, if any are missing, surface an
      // inline install prompt in the upload step (reusing the per-font picker
      // pattern from _renderFonts).
      try {
        const fontRes = await _fetchJSON(`${SETUP}/fonts/detect`, {
          method: 'POST',
          body: (() => { const fd = new FormData(); fd.append('file', picker.getFiles()[0]); return fd; })(),
        });
        const missing = (fontRes && fontRes.missing) || [];
        if (missing.length) {
          _renderInlineFontPrompt(missing);
          // Font prompt renders its own "Continue when fonts are installed" flow;
          // skip the preview until fonts are resolved.
          return;
        }
      } catch { /* font detection is best-effort; continue to preview */ }

      // The preview is a nice-to-have fidelity check, not a hard gate — a missing
      // xelatex/LibreOffice on the deployed image (or any other preview failure)
      // must never wedge the wizard. _buildPreview() already renders its own
      // "Preview unavailable: …" message internally on failure; Continue is
      // enabled in `finally` unconditionally so it's never left permanently
      // disabled by a broken preview (the resume itself still uploaded fine).
      try {
        await _buildPreview();
      } finally {
        document.getElementById('ao-resume-next').disabled = false;
      }
    } catch (e) {
      st.innerHTML = _err(esc(e.message || 'Could not read the résumé.'));
    }
  }

  document.getElementById('ao-resume-next').onclick = async () => {
    if (_busy) return;
    _busy = true;
    document.getElementById('ao-resume-next').disabled = true;
    try {
      // The upload already parsed + reconciled the resume and marked this section
      // complete (with the stored document + raw text the rest of the engine reads).
      // Just refresh state and move on — DON'T re-save a stub that would clobber the
      // parsed base_resume record. Refresh is best-effort: keep last-known on failure.
      try {
        _onboarding = await _fetchJSON(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}`);
      } catch { /* keep last-known intake */ }
      await _nextIntakeOrComplete();
    } catch (e) {
      document.getElementById('ao-resume-msg').innerHTML = _err(esc(e.message || 'Could not continue.'));
      document.getElementById('ao-resume-next').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

function _renderConflicts(conflicts) {
  const wrap = document.getElementById('ao-conflicts');
  wrap.innerHTML = `
    <div class="admin-card">
      <p style="color:var(--accent-warm, #d8a23a);font-size:0.86rem;margin:0 0 8px;">A few details in your résumé differ from what you told me. Pick which to keep:</p>
      ${conflicts.map((c, i) => `
        <div data-attr="${esc(c.attribute)}" data-i="${i}" style="margin:8px 0;display:flex;flex-direction:column;gap:2px;">
          <strong>${esc(c.attribute)}</strong>
          <label style="font-weight:normal;font-size:0.86rem;"><input type="radio" name="ao-conf-${i}" value="interview" checked> Keep your answer: ${esc(c.interview_value)}</label>
          <label style="font-weight:normal;font-size:0.86rem;"><input type="radio" name="ao-conf-${i}" value="parsed"> Use the résumé's: ${esc(c.parsed_value)}</label>
        </div>`).join('')}
      <button class="cal-btn" id="ao-conf-apply" style="margin-top:6px;">Apply choices</button>
    </div>`;
  const applyBtn = document.getElementById('ao-conf-apply');
  // #29a: an in-flight guard — the loop below fires one confirm-conflict POST
  // per conflict with no guard, so a double-click on Apply replayed the whole
  // batch. Mirrors the _setButtonBusy/_clearButtonBusy busy-button pattern.
  applyBtn.onclick = async () => {
    if (applyBtn.disabled) return;
    const orig = _setButtonBusy(applyBtn, 'Applying…');
    try {
      for (const c of conflicts) {
        const i = wrap.querySelector(`[data-attr="${CSS.escape(c.attribute)}"]`).getAttribute('data-i');
        // #68: `.value` on a possibly-null `:checked` match null-derefed when a
        // conflict was left unanswered, surfacing as the generic "Could not
        // apply choices" toast instead of a real validation message. Every
        // choice defaults `checked` on render, but guard the read anyway so a
        // stray DOM state never throws.
        const checkedEl = wrap.querySelector(`input[name="ao-conf-${i}"]:checked`);
        if (!checkedEl) {
          _toast(`Please choose an option for ${c.attribute}.`);
          _clearButtonBusy(applyBtn, orig);
          return;
        }
        const choice = checkedEl.value;
        const value = choice === 'parsed' ? c.parsed_value : c.interview_value;
        await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/confirm-conflict`, {
          attribute: c.attribute, value,
        });
      }
      wrap.innerHTML = '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Choices applied.</p>';
    } catch (e) {
      _toast(e.message || 'Could not apply choices.');
      _clearButtonBusy(applyBtn, orig);
    }
  };
}

async function _buildPreview() {
  const wrap = document.getElementById('ao-preview');
  // #59: attach to an already-running build rather than firing a second,
  // overlapping POST — the caller that started it already renders the result
  // (or the "unavailable" message) into the same #ao-preview.
  if (_previewInFlight) {
    try { await _previewInFlight; } catch { /* handled by the original caller */ }
    return;
  }
  wrap.innerHTML = '<p style="font-size:0.82rem;opacity:0.75;">Building a polished version…</p>';
  // #59: give this specific LaTeX/LibreOffice render an explicit, generous
  // client deadline (rather than relying on _fetchJSON's generic 15s default,
  // which a real compile can plausibly exceed) so a stalled build fails loud
  // instead of leaving "Building a polished version…" up forever.
  const req = _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/preview`, {}, { timeoutMs: 45000 });
  _previewInFlight = req;
  let p;
  try {
    p = await req;
  } catch (e) {
    wrap.innerHTML = `<p style="font-size:0.82rem;opacity:0.75;">Preview unavailable: ${esc(e.message || '')}</p>`;
    return;
  } finally {
    if (_previewInFlight === req) _previewInFlight = null;
  }
  // HONESTY: "I built a polished version" may only describe a PDF the engine
  // REALLY rendered. `artifact_available` is the engine's server-derived ground
  // truth (real PDF bytes produced by an available toolchain); anything else —
  // including an older engine that doesn't report the field — must NOT claim a
  // polished version exists, offer "Use this version", or invent a page count.
  if (!p || p.artifact_available !== true) {
    const notesList = (Array.isArray(p && p.notes) ? p.notes : (p && p.notes ? [String(p.notes)] : []));
    wrap.innerHTML = `
      <div class="admin-card">
        <p style="margin:0 0 8px;">I couldn’t build a polished preview of your résumé in this deployment, so I’ll keep using your original file.</p>
        ${notesList.length ? `<ul style="font-size:0.82rem;opacity:0.85;">${notesList.map((n) => `<li>${esc(String(n))}</li>`).join('')}</ul>` : ''}
      </div>`;
    return;
  }
  {
    const note = p.fidelity_ok ? 'Looks like a faithful match.' : 'Some formatting may differ.';
    // `notes` may come back as an array, a single string, or be absent — coerce to
    // an array so a string value doesn't crash the preview on `.map` (it has a
    // truthy `.length` but no `.map`), which surfaced as "Preview unavailable".
    // The engine echoes the fidelity line into `p.notes` too, so it would render
    // twice (once in the summary `<p>` above, once as a bullet). De-dup: drop any
    // notes entry equal to the summary `note`.
    const notesList = (Array.isArray(p.notes) ? p.notes : (p.notes ? [String(p.notes)] : []))
      .filter((n) => String(n).trim() !== note.trim());
    wrap.innerHTML = `
      <div class="admin-card">
        <p style="margin:0 0 8px;">I built a polished version of your résumé (${esc(String(p.page_count || '?'))} ${p.page_count === 1 ? 'page' : 'pages'}). ${esc(note)}</p>
        ${notesList.length ? `<ul>${notesList.map((n) => `<li>${esc(String(n))}</li>`).join('')}</ul>` : ''}
        <div class="settings-row" style="margin-top:6px;">
          <button class="cal-btn cal-btn-primary" id="ao-prev-accept">Use this version</button>
          <button class="cal-btn" id="ao-prev-reject">Keep my original</button>
          <button class="cal-btn" id="ao-prev-download">Open preview PDF</button>
          <span id="ao-prev-status" style="font-size:0.82rem;opacity:0.75;"></span>
        </div>
      </div>`;
    // #29a: an in-flight guard on accept/reject — neither was disabled while
    // its POST was outstanding, so a fast double-click double-posted the
    // accept/reject choice to the engine.
    const acceptBtn = document.getElementById('ao-prev-accept');
    const rejectBtn = document.getElementById('ao-prev-reject');
    acceptBtn.onclick = async () => {
      if (acceptBtn.disabled) return;
      const orig = _setButtonBusy(acceptBtn, 'Applying…');
      if (rejectBtn) rejectBtn.disabled = true;
      try {
        await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/accept`, {});
        document.getElementById('ao-prev-status').textContent = 'Using the polished version.';
      } catch (e) { _toast(e.message || 'Could not accept.'); }
      finally {
        _clearButtonBusy(acceptBtn, orig);
        if (rejectBtn) rejectBtn.disabled = false;
      }
    };
    rejectBtn.onclick = async () => {
      if (rejectBtn.disabled) return;
      const orig = _setButtonBusy(rejectBtn, 'Applying…');
      if (acceptBtn) acceptBtn.disabled = true;
      try {
        await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/reject`, {});
        document.getElementById('ao-prev-status').textContent = 'Keeping your original.';
      } catch (e) { _toast(e.message || 'Could not reject.'); }
      finally {
        _clearButtonBusy(rejectBtn, orig);
        if (acceptBtn) acceptBtn.disabled = false;
      }
    };
    // Download the actual compiled PDF (dark-engine audit item 19) so the
    // accept/reject choice can be made from the real document, not just the
    // page-count/fidelity summary above.
    document.getElementById('ao-prev-download').onclick = async (e) => {
      const btn = e.currentTarget;
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Opening…';
      try {
        const res = await fetch(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/preview/download`, { credentials: 'same-origin' });
        if (!res.ok) throw new Error(await res.text().catch(() => 'Preview not available yet.'));
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `resume-preview-${_campaignId}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        _toast((err && err.message) || 'Could not open the preview PDF.');
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    };
  }
}

async function _nextIntakeOrComplete() {
  // #52: the section just rendered has already been POSTed successfully by the
  // time every caller reaches this function — clear its draft (still the
  // current _draftScope, `onboarding:<that section>`) before moving on.
  _clearDraft();
  if (_intakeIndex < INTAKE_SECTIONS.length - 1) {
    _intakeIndex += 1;
    await _renderIntakeSection();
    return;
  }
  // Last section saved — try to complete.
  try {
    await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/complete`, {});
    await _advanceAndContinue('onboarding');
  } catch (e) {
    // 409 with missing_sections -> jump back to the first missing one.
    const missing = (e.body && e.body.detail && e.body.detail.missing_sections)
      || (e.body && e.body.missing_sections) || [];
    // #26: a 409 that names nothing actually missing means the intake is
    // already complete on the engine's side (e.g. a duplicate/late completion
    // request racing a previous one) — treat that as success instead of
    // stranding the user on the last section with an unexplained failure.
    if (!missing.length && e.status === 409) {
      await _advanceAndContinue('onboarding');
      return;
    }
    if (missing.length) {
      // ON-S2-5: a section marked `optional` in SECTION_FORMS (currently just
      // References — its own on-screen copy says "add them now, or skip")
      // must not hard-block completion just because it's still empty; that's
      // exactly what the "Skip for now" button right next to "Save &
      // continue" already lets you do. If every reported-missing section is
      // one of these, finish the same way Skip does instead of bouncing the
      // user back to a section its own copy told them they could skip.
      const blocking = missing.filter((k) => !(SECTION_FORMS[k] && SECTION_FORMS[k].optional));
      if (!blocking.length) {
        await _finish();
        return;
      }
      const idx = INTAKE_SECTIONS.indexOf(blocking[0]);
      _intakeIndex = idx >= 0 ? idx : 0;
      await _renderIntakeSection();
      // #26: the section we just jumped back to may not even render an
      // `#ao-intake-msg` container (e.g. base_resume uses its own status area),
      // which previously swallowed this message entirely — a toast is always
      // visible regardless of which section's markup is on screen, and the
      // per-section message is kept as a bonus where that container exists.
      const msg = `Please finish "${_sectionLabel(blocking[0])}" to continue.`;
      const inline = document.getElementById('ao-intake-msg');
      if (inline) inline.innerHTML = _err(esc(msg));
      _toast(msg);
    } else {
      _toast(errText(e) || 'Could not finish onboarding.');
    }
  }
}

// Human-readable label for an intake section key, reusing SECTION_FORMS' own
// titles (#26) rather than echoing the raw engine key (e.g. "campaign_criteria").
function _sectionLabel(key) {
  if (key === 'base_resume') return 'Start with your résumé';
  const spec = SECTION_FORMS[key];
  return (spec && spec.title) || key;
}

// ── finish ──────────────────────────────────────────────────────────────────

async function _finish() {
  _restoreEndpointManager();
  // B2: be honest. Refresh status and only say "You're all set" when the gating
  // steps are actually complete; otherwise tell the truth and offer jump-backs.
  try { await _refreshStatus(); } catch { /* use last-known status */ }
  const s = _status || {};
  // Only "connect a model" strictly gates BEGINNING. Applying is hard-gated on the
  // required-to-apply essentials (apply_ready); when those aren't in yet we tell the
  // truth and point back to the profile step, but the user can still get started —
  // Applicant will gather the rest in chat.
  const missing = [];
  if (!s.llm_configured) missing.push({ key: 'llm', label: 'connect a model' });

  if (!missing.length) {
    const applyMissing = Array.isArray(s.apply_missing) ? s.apply_missing : [];
    const ready = !!s.apply_ready || applyMissing.length === 0;
    // B2 / gate-fix: be honest. Only the fully-ready state says "all set"; when the
    // apply-readiness gate is still closed the heading + copy say the search is NOT
    // running yet and name exactly what's left (the ONE server-truth apply_missing).
    const heading = ready ? 'You’re all set.' : 'Almost ready.';
    const readyLine = ready
      ? "I’m ready to start applying for you."
      : `I’m set up, but I’m not searching yet. Before I can start I still need: ${esc(applyMissing.join(', '))} — tell me in chat or add a résumé any time, and I’ll begin on my own.`;
    // D71: the default throughput (15/day, capped at 30) otherwise takes effect
    // silently — nobody consented to it and nobody was told. State it plainly as
    // a completion RECEIPT, with a pointer to where it's adjustable, right where
    // the user is already reading "what happens next".
    // #102: "Campaigns" isn't a destination anywhere in the nav — the Settings
    // tab this points to is named "Job Search" (applicantCampaignSettings.js),
    // matching the "search" wording the rest of the product uses.
    const receiptLine = 'By default, Applicant targets up to 15 new applications a day (never more than 30) — every one reviewed by you before it ships. Adjust the pace any time in Settings → Job Search.';
    // D73: when the model is connected but profile essentials are still missing,
    // the old copy buried the fix in a sentence with no way to act on it. Give it
    // a real jump button back into "Your profile", matching the jump-button
    // mechanic the still-blocked branch below already uses.
    const profileJumpBtn = (!ready && applyMissing.length)
      ? '<button class="cal-btn" id="ao-finish-profile" style="margin-top:14px;">Complete your profile</button>'
      : '';
    // P1-1: a "what happens next" card — the first digest + approval flow in
    // three plain steps, so the user leaves setup knowing what to expect and
    // when, instead of staring at a quiet app wondering if it's working.
    const whatNextCard = `
      <div class="admin-card" style="max-width:460px;margin:16px auto 0;text-align:left;">
        <p style="margin:0 0 6px;font-weight:600;font-size:0.9rem;">What happens next</p>
        <ol style="margin:0;padding-left:18px;font-size:0.84rem;opacity:0.85;line-height:1.6;">
          <li>I search for matching roles around the clock${ready ? '' : ' — starting the moment the last essentials above are in'}.</li>
          <li>Your first digest of matched roles lands in Pending, your home base — and on any notification channels you set up in Settings.</li>
          <li>You approve the roles you like; I prepare each application for your review, and nothing is ever sent without your final OK.</li>
        </ol>
      </div>`;
    _setBody(`<div style="text-align:center;padding:30px 0;"><h2 style="margin:0 0 8px;">${esc(heading)}</h2><p style="max-width:460px;margin:0 auto;">${readyLine}</p><p style="max-width:460px;margin:10px auto 0;font-size:0.82rem;opacity:0.75;">${receiptLine}</p>${whatNextCard}${profileJumpBtn}</div>`);
    _setFoot('<button class="cal-btn cal-btn-primary" id="ao-finish">Get started</button>');
    // First-light payoff: this is the ONE screen that means setup is genuinely
    // done (llm_configured, nothing left gating it) — mark it so _dismiss() knows
    // to hand off to the Portal home base rather than just closing quietly.
    _justCompletedSetup = true;
    document.getElementById('ao-finish').onclick = _dismiss;
    const profileBtn = document.getElementById('ao-finish-profile');
    if (profileBtn) profileBtn.onclick = () => {
      if (_busy) return;
      const idx = STEPS.findIndex((st) => st.key === 'onboarding');
      if (idx >= 0) { _stepIndex = idx; _renderStep(); }
    };
    const nav = document.getElementById('ao-nav');
    if (nav) nav.innerHTML = '';
    _renderRail();
    return;
  }

  const list = missing.map((m) => m.label).join(', ').replace(/, ([^,]*)$/, ' and $1');
  const jumpBtns = missing.map((m) =>
    `<button class="cal-btn ao-finish-jump" data-step="${esc(m.key)}">${esc(m.label.replace(/^./, (c) => c.toUpperCase()))}</button>`
  ).join('');
  _setBody(`
    <div style="padding:24px 0;text-align:center;">
      <h2 style="margin:0 0 8px;">Almost there</h2>
      <p style="max-width:440px;margin:0 auto 12px;">
        To let Applicant start, ${esc(list)}.
      </p>
      <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:4px;">${jumpBtns}</div>
    </div>`);
  _setFoot('');
  const nav = document.getElementById('ao-nav');
  if (nav) nav.innerHTML = '';
  _renderRail();
  // Jump straight back to an unfinished step.
  document.querySelectorAll('.ao-finish-jump').forEach((btn) => {
    btn.onclick = async () => {
      if (_busy) return;
      const key = btn.dataset.step;
      const idx = STEPS.findIndex((st) => st.key === key);
      if (idx >= 0) { _stepIndex = idx; await _renderStep(); }
    };
  });
}

// Escape-key handler wired into initModalA11y below. The wizard is "always wins,
// blocking" by design (see the CLAUDE.md working principles + the gate logic
// above) — a bare Escape must never silently discard an in-progress, unsaved
// section. When nothing has been typed since the step last rendered, Escape can
// still close directly (there's nothing to lose). Reuses the SAME styled-confirm
// pattern the Settings "Update Applicant" button above already uses
// (window.uiModule.styledConfirm, falling back to window.confirm).
async function _maybeDismiss() {
  if (!_formDirty) { _dismiss(); return; }
  let ok = false;
  try {
    ok = window.uiModule && typeof window.uiModule.styledConfirm === 'function'
      ? await window.uiModule.styledConfirm(
          'Discard your in-progress setup answers? Anything you typed on this step that hasn’t been saved will be lost.',
          { confirmText: 'Discard', cancelText: 'Keep editing', danger: true })
      : window.confirm('Discard your in-progress setup answers? Anything you typed on this step that hasn’t been saved will be lost.');
  } catch { ok = false; }
  if (ok) _dismiss();
}

// Audit Top-25 #17 / §7 item 3 (Journey Beat 2 "first light"): kill the dead air
// right after setup completes. The engine's always-on 24/7 scheduler (agent_loop.py
// _run_discovery, driven by app/lifespan.py's _scheduler_loop) already ticks on its
// own cadence — no separate client-side kickoff is needed to START discovery, it
// picks campaigns up the moment criteria are ready. What's missing is the user
// SEEING that: left on the bare chat shell, first light reads as dead. Hand off
// straight to the Portal — the established post-login home base and notification
// center (Journey Map Beat 2/4, `applicantPortal.js` openApplicantPortal) — with a
// short "you're set, here's what's next" toast, matching the honest, low-key voice
// of the models.js welcome-card work rather than a hard silent auto-navigation.
function _openHomeBaseAfterSetup() {
  // Help/self-explain audit item 23: the send-off should teach the daily
  // rhythm, not just unlock nav — so the user leaves setup already knowing
  // Applicant searches continuously, digests arrive on their own, and
  // anything needing a decision waits in Pending rather than vanishing.
  // Gate-fix honesty: only promise "I'll keep searching around the clock" when the
  // apply-readiness gate is actually open. If essentials are still missing, say so
  // — the Portal home base we're handing off to now tells the same truth.
  const applyReady = !!(_status && (_status.apply_ready
    || (Array.isArray(_status.apply_missing) && _status.apply_missing.length === 0)));
  const readyToast = 'You’re all set — I’ll keep searching around the clock. Your digest '
    + 'will arrive on its own, and anything that needs you waits right '
    + 'here in Pending, your home base.';
  const notYetToast = 'You’re set up — but I’m not searching yet. Finish the last essentials '
    + 'in Pending (your home base) and I’ll start on my own. Anything that needs you '
    + 'waits there too.';
  try {
    if (window.uiModule && typeof window.uiModule.showToast === 'function') {
      window.uiModule.showToast(applyReady ? readyToast : notYetToast, { duration: 6000 });
    } else {
      _toast(applyReady ? 'You’re all set — Applicant is getting to work.'
        : 'You’re set up — finish the last essentials in Pending to start your search.');
    }
  } catch { /* the toast is a nice-to-have; never let it block the hand-off */ }
  try {
    if (window.applicantPortalModule && typeof window.applicantPortalModule.openApplicantPortal === 'function') {
      window.applicantPortalModule.openApplicantPortal();
    }
  } catch { /* best-effort — a missing/broken Portal module must never break finishing setup */ }
}

function _dismiss() {
  _stopNavBusyWatch();
  // Tear down a11y bindings before removing the overlay from the DOM.
  if (_overlayA11yCleanup) { _overlayA11yCleanup(); _overlayA11yCleanup = null; }
  // Hand the shared endpoint manager back to Settings before tearing down the
  // overlay, so it isn't removed from the DOM along with the overlay.
  _restoreEndpointManager();
  if (_overlay && _overlay.parentNode) _overlay.parentNode.removeChild(_overlay);
  _overlay = null;
  // Consume the "we just reached the genuine finish screen" flag once, however
  // this dismiss was triggered (Get started click or Escape) — a mid-wizard
  // Escape/cancel never sets it, so this stays scoped to real completions.
  const justCompleted = _justCompletedSetup;
  _justCompletedSetup = false;
  // #52: nothing left to resume once setup genuinely completes — drop every
  // scoped draft rather than leave stale ones around for a later re-run/Settings visit.
  // Only on a genuine completion; a mid-wizard dismiss keeps its drafts so an
  // explicit re-run resumes exactly where the user left off.
  if (justCompleted) { _clearAllDrafts(); }
  // CC-S2-6 / ON-S3-19: remember the dismissal locally on EVERY close — not only a
  // genuine completion (#27). The wizard is blocking, so once the user closes it
  // (Escape/discard OR "Get started"), it must NOT auto-re-mount behind another
  // modal or steal clicks after in-app navigation. maybeLaunchOnboarding() (boot/
  // reload) and the locked-feature nav guard both honour this flag; an explicit
  // "Re-run setup" (window.launchApplicantSetup) still reopens it and clears it.
  _markDismissedLocally();
  // Re-run the feature-activation layer so the job sections light up now that the
  // engine gate is open. app.js exposes the refresh; fall back to a reload.
  try {
    if (typeof window.refreshApplicantFeatures === 'function') {
      window.refreshApplicantFeatures();
      if (justCompleted) _openHomeBaseAfterSetup();
      return;
    }
  } catch { /* fall through */ }
  // No refresh hook (defensive path only — app.js always defines it in practice):
  // a reload would wipe any Portal we open now, so skip the hand-off here and let
  // the reloaded page's own boot sequence stand up the nav fresh.
  try { window.location.reload(); } catch { /* no-op */ }
}

// ── dismissed-wizard persistence (#27) ──────────────────────────────────────
//
// The server's `onboarding_complete` is the STRICT apply-readiness gate (target
// roles, work mode, locations, salary floor, key skills, a résumé) — but "Your
// profile" is explicitly OPTIONAL (see the STEPS comment above) and the wizard's
// own _finish() screen tells the user "You're all set" the moment a model is
// connected, regardless of that stricter gate. A user who reaches that genuine
// completion screen and moves on must not be forced to re-dismiss the wizard on
// every subsequent login just because the optional profile essentials were never
// (or not yet) fully supplied. Remember that hand-off locally, per user (mirrors
// the `document.body.dataset.user`-scoped keying appkitWindow.js/appkitNotice.js
// already use), alongside the server truth so either one suppresses re-launch.
const _DISMISSED_KEY_PREFIX = 'applicant_onboarding_dismissed:';

function _dismissedStorageKey() {
  let user = '';
  try { user = (document.body && document.body.dataset && document.body.dataset.user) || ''; } catch { /* no-op */ }
  return `${_DISMISSED_KEY_PREFIX}${user}`;
}

function _isDismissedLocally() {
  try { return localStorage.getItem(_dismissedStorageKey()) === '1'; } catch { return false; }
}

function _markDismissedLocally() {
  try { localStorage.setItem(_dismissedStorageKey(), '1'); } catch { /* best-effort */ }
}

function _clearDismissedLocally() {
  try { localStorage.removeItem(_dismissedStorageKey()); } catch { /* best-effort */ }
}

// CC-S2-6 / ON-S3-19: expose the per-user dismissed check so the shell's locked-
// feature nav guard (app.js refreshApplicantFeatures) can tell "the user closed
// setup for now" apart from "never opened", and only route a locked-feature click
// into the blocking wizard when it hasn't been dismissed. Returns false on any
// error so the guard fails OPEN (its prior behaviour) rather than trapping a click.
export function isOnboardingDismissedLocally() { return _isDismissedLocally(); }
try { if (typeof window !== 'undefined') window.isApplicantOnboardingDismissed = isOnboardingDismissedLocally; } catch { /* no-op */ }

// ── public entry: maybe launch the wizard on boot ───────────────────────────

// Returns true when the setup wizard was launched (setup incomplete), false
// otherwise (setup already complete, already dismissed, or the engine is
// unreachable). Callers use this to decide whether to take precedence over a
// post-login landing surface: the wizard always wins, and the home-base Portal
// only opens when this is false.
export async function maybeLaunchOnboarding() {
  if (_overlay) return true; // already open
  let status;
  try { status = await _refreshStatus(); }
  catch { return false; } // engine unreachable -> don't block; the user can still log in
  if (!status) return false;
  const complete = status.llm_configured && status.onboarding_complete;
  if (complete) { _clearDismissedLocally(); return false; } // nothing to do
  // #27: server truth isn't complete (the optional profile essentials may never
  // fill in), but the user already reached "You're all set" once and dismissed —
  // trust that local signal so the wizard doesn't reopen on every visit.
  if (_isDismissedLocally()) return false;

  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
  if (_overlayA11yCleanup) _overlayA11yCleanup();
  _overlayA11yCleanup = window.uiModule && window.uiModule.initModalA11y
    ? window.uiModule.initModalA11y(_overlay, _maybeDismiss)
    : null;
  _stepIndex = _firstIncompleteStep();
  _startNavBusyWatch();
  // Pre-create the campaign once the LLM gate is open so onboarding resumes cleanly.
  if (status.llm_configured) { try { await _ensureCampaign(); } catch { /* later */ } }
  await _renderStep();
  return true;
}

// Force-open the wizard (e.g. the "Re-run setup" button in Settings) regardless of
// completion, starting at the first step so any prior choice can be reviewed/changed.
export async function launchOnboarding() {
  if (_overlay) return;
  // Explicit re-run (Settings "Re-run setup", a "Finish/Connect" CTA) means the
  // user WANTS setup now — clear any prior local dismissal so it reopens, and so a
  // later close re-marks it fresh (CC-S2-6). The locked-feature guard deliberately
  // does NOT reach here once dismissed (it checks isApplicantOnboardingDismissed).
  _clearDismissedLocally();
  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
  if (_overlayA11yCleanup) _overlayA11yCleanup();
  _overlayA11yCleanup = window.uiModule && window.uiModule.initModalA11y
    ? window.uiModule.initModalA11y(_overlay, _maybeDismiss)
    : null;
  _startNavBusyWatch();
  try { await _refreshStatus(); } catch { /* engine down — still show the wizard */ }
  if (_status && _status.llm_configured) { try { await _ensureCampaign(); } catch { /* later */ } }
  _stepIndex = 0;
  await _renderStep();
}

// Expose a global so the Settings panel can relaunch setup without importing this module.
if (typeof window !== 'undefined') window.launchApplicantSetup = launchOnboarding;

// The honest "what Applicant never does" list, exported so other surfaces reuse
// the EXACT same wording (D4: the Portal empty state).
export const neverDoesList = NEVER_DOES.slice();
try { if (typeof window !== 'undefined') window.applicantNeverDoesList = neverDoesList; } catch { /* no-op */ }

// ── Settings reuse of the relocated steps ───────────────────────────────────
//
// The Notifications, Automation-sandbox and Fonts steps were lifted out of the
// OOBE wizard and into Settings. Rather than reimplement them, Settings calls the
// SAME renderers (_renderChannels / _renderSandbox / _renderFonts) used by the
// wizard — this helper mounts one of them into a Settings panel by pointing the
// shared _setBody/_setFoot at the panel's own body/foot elements and flipping on
// the absent wizard overlay so the renderer saves through the engine proxies
// without trying to drive navigation.
//
// `container` is the panel element; we create/reuse `.ao-settings-body` and
// `.ao-settings-foot` children inside it so the renderer's body+foot land there.
// (The renderers detect "Settings, not wizard" at save time via the absent
// _overlay, so they save through the engine proxies without driving navigation.)
// In-settings Update button (FR-OOBE-4 / FR-UI-6 / FR-INSTALL-2). The same
// one-click update the Debug tool exposes, lifted here so it's reachable where an
// operator looks for it — Settings — without SSH/CLI. Talks to the engine ops
// proxy (GET status + POST trigger); degrades cleanly when updates aren't enabled.
async function _renderUpdate() {
  let status = { engine_available: true };
  try { status = await _fetchJSON(`${OPS}/update`); } catch { status = { engine_available: false }; }
  if (status && status.engine_available === false) {
    _setBody('<div class="admin-card"><div class="admin-toggle-sub">The update service is offline right now. Try again shortly.</div></div>');
    _setFoot('');
    return;
  }
  _setBody(`
    <h2 class="ao-step-title">Update Applicant ${_tip('Runs the safe one-click update — it backs up your data, applies the latest version, and restarts. No command line needed.')}</h2>
    <p class="ao-step-desc">Get the latest version without the command line. Applicant backs up your data first, applies the update, then restarts. If updates aren’t enabled on this install, it will tell you what it would do.</p>
    <div class="admin-card">
      <div style="font-weight:600;">One-click update</div>
      <div class="admin-toggle-sub" style="opacity:0.8;margin-top:4px;">Back up &rarr; apply the latest version &rarr; restart. Safe to run any time.</div>
      <button class="cal-btn cal-btn-primary" id="ao-update-go" style="margin-top:12px;">Check for &amp; install update</button>
      <div id="ao-update-result" class="admin-toggle-sub" style="margin-top:10px;"></div>
    </div>
  `);
  _setFoot('');
  const btn = document.getElementById('ao-update-go');
  const out = document.getElementById('ao-update-result');
  if (btn) btn.onclick = async () => {
    let ok = false;
    try {
      if (window.uiModule && typeof window.uiModule.styledConfirm === 'function') {
        ok = await window.uiModule.styledConfirm(
          'Update now? Your data is backed up first, then the latest version is applied and the app restarts.',
          { confirmText: 'Update now', cancelText: 'Cancel' });
      } else {
        ok = window.confirm('Update now? Your data is backed up first, then the latest version is applied and the app restarts.');
      }
    } catch { ok = false; }
    if (!ok) return;
    btn.disabled = true;
    out.textContent = 'Updating…';
    try {
      const res = await _post(`${OPS}/update/trigger`, {});
      out.textContent = res.message || (res.started ? 'Update started.' : "You’re already up to date.");
    } catch (e) {
      out.textContent = e.message || 'Could not start the update right now.';
    } finally {
      btn.disabled = false;
    }
  };
}

const _SETTINGS_RENDERERS = {
  channels: _renderChannels,
  sandbox: _renderSandbox,
  fonts: _renderFonts,
  update: _renderUpdate,
};

export async function mountSettingsStep(stepKey, container) {
  const render = _SETTINGS_RENDERERS[stepKey];
  if (!render || !container) return false;
  let body = container.querySelector('.ao-settings-body');
  let foot = container.querySelector('.ao-settings-foot');
  if (!body) {
    body = document.createElement('div');
    body.className = 'ao-settings-body';
    container.appendChild(body);
  }
  if (!foot) {
    foot = document.createElement('div');
    foot.className = 'ao-settings-foot ao-foot';
    container.appendChild(foot);
  }
  const prevBody = _bodyTarget;
  const prevFoot = _footTarget;
  const prevSettingsContext = _inSettingsContext;
  _bodyTarget = body;
  _footTarget = foot;
  // #96: mark this render as Settings context so the relocated renderers can
  // drop wizard-only footer chrome (see the flag's own doc comment above).
  _inSettingsContext = true;
  // #52: scope the draft to this Settings step (e.g. 'channels'/'sandbox'/
  // 'fonts'/'update') so a reload while editing Settings also survives.
  _draftScope = stepKey;
  try {
    await render();
  } finally {
    // Restore so a later wizard launch keeps targeting its own DOM. Only the
    // synchronous body/foot build reads these targets; later click handlers
    // address their own elements by id.
    _bodyTarget = prevBody;
    _footTarget = prevFoot;
    _inSettingsContext = prevSettingsContext;
  }
  return true;
}

if (typeof window !== 'undefined') window.mountApplicantSettingsStep = mountSettingsStep;

export default { maybeLaunchOnboarding, launchOnboarding, neverDoesList, trustLine, mountSettingsStep };
