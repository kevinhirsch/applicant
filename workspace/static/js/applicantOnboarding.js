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

const SETUP = '/api/applicant/setup';
const OPS = '/api/applicant/ops';  // one-click update (FR-OOBE-4 / FR-INSTALL-2)

let _overlay = null;
let _overlayA11yCleanup = null;
let _campaignId = null;
let _status = null;        // engine setup status
let _onboarding = null;    // engine onboarding state
let _stepIndex = 0;        // active step in STEPS
let _busy = false;

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
  { key: 'welcome',    title: 'Welcome',          done: (s) => !!(s && (s.llm_configured || s.onboarding_complete || (Array.isArray(s.steps_complete) && s.steps_complete.length))) },
  { key: 'llm',        title: 'Connect a model',  done: (s) => !!(s && s.llm_configured) },
  // "Your profile" is OPTIONAL — the only thing that strictly gates BEGINNING is a
  // connected model. Applicant gathers what it needs to apply over time (a résumé,
  // or just telling it in chat). The step is "done enough" once the agent has the
  // required-to-apply essentials (apply_ready), so the rail stops nagging once the
  // hard apply-gate would open; a brand-new user can also just Skip it.
  { key: 'onboarding', title: 'Your profile',     done: (s) => !!(s && (s.apply_ready || s.onboarding_complete)) },
];

// Intake sub-sections (the comprehensive Workday-ready interview). Each renders a
// small form; data is saved per-section so the interview is fully resumable.
//
// Resume-FIRST: the base-resume upload leads the profile so the engine can read
// the resume and PREFILL the editable fields below (identity, work history,
// education, skills). The user then steps through and corrects any parsing
// mistakes instead of typing everything by hand — uploading is the starting
// point of profile setup, not a post-hoc reconciliation.
const INTAKE_SECTIONS = [
  'base_resume',
  'identity', 'work_authorization', 'location', 'target_roles', 'compensation',
  'work_history', 'education', 'references', 'key_attributes', 'eeo',
  'campaign_criteria',
];

// The honest "what Applicant never does" list (B1). Exported via the module so
// other surfaces (e.g. the Portal empty state, D4) reuse the EXACT same wording.
const NEVER_DOES = [
  'Never submits an application without your approval.',
  'Pauses and asks whenever something is uncertain.',
  'Never solves CAPTCHAs — it hands those to you.',
  'Never guesses your voluntary self-identification (EEO) answers.',
];

// ── small helpers ───────────────────────────────────────────────────────────

function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _toast(msg) {
  try {
    if (window.uiModule && typeof window.uiModule.showToast === 'function') {
      window.uiModule.showToast(msg);
      return;
    }
  } catch { /* fall through */ }
  try { console.warn('[setup]', msg); } catch { /* no-op */ }
}

async function _fetchJSON(url, opts = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    err.body = data;
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
// (Multipart uploads no longer hand-roll FormData here — the fonts/resume steps
// reuse fileHandler.js's picker uploadPending(), which builds + POSTs the form.)

// ── engine status / campaign bootstrap ──────────────────────────────────────

async function _refreshStatus() {
  _status = await _fetchJSON(`${SETUP}/status`);
  return _status;
}

// The intake attaches to a campaign; ensure one exists once the LLM gate is open.
async function _ensureCampaign() {
  if (_campaignId) return _campaignId;
  let list = [];
  try { list = await _fetchJSON(`${SETUP}/campaigns`); } catch { list = []; }
  if (Array.isArray(list) && list.length) {
    _campaignId = list[0].id;
    return _campaignId;
  }
  const created = await _post(`${SETUP}/campaigns`, { name: 'My job search' });
  _campaignId = created.id;
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
  o.className = 'modal';
  // Blocking: trap focus, no dismiss-into-app. The user can't escape into the job
  // features until setup is done (the engine also blocks server-side).
  o.setAttribute('role', 'dialog');
  o.setAttribute('aria-modal', 'true');
  o.setAttribute('aria-label', 'Set up Applicant');
  o.innerHTML = `
    <div class="modal-content">
      <div class="modal-header" style="cursor:default;">
        <h4>Welcome — let's get you set up</h4>
      </div>
      <div class="admin-tabs" id="ao-rail" role="list" aria-label="Setup progress"></div>
      <div class="modal-body" id="ao-body"></div>
      <div class="ao-foot" id="ao-foot"></div>
      <div class="ao-nav" id="ao-nav"></div>
    </div>`;
  // Swallow click-throughs to the app behind the overlay (no dismiss-on-backdrop).
  o.addEventListener('click', (ev) => { if (ev.target === o) ev.stopPropagation(); });
  return o;
}

function _renderRail() {
  const rail = document.getElementById('ao-rail');
  if (!rail) return;
  // The step rail reuses `.admin-tabs`/`.admin-tab` (the same tab strip Settings
  // and the libraries use). Steps aren't clickable — they show progress — so they
  // carry `.done`/`.active` only; the CSS de-emphasises the hover affordance.
  rail.innerHTML = STEPS.map((step, i) => {
    const done = step.done(_status);
    const cur = i === _stepIndex;
    const cls = `admin-tab${done ? ' done' : ''}${cur ? ' active' : ''}`;
    const mark = done ? '✓ ' : `${i + 1}. `;
    return `<span class="${cls}" role="listitem" aria-current="${cur ? 'step' : 'false'}">${esc(mark)}${esc(step.title)}</span>`;
  }).join('');
}

// When a step renderer is reused OUTSIDE the wizard (Settings), these point at the
// settings panel's body/foot elements instead of the wizard's fixed ao-body/ao-foot.
// Null = wizard mode (the default). See mountSettingsStep() below.
let _bodyTarget = null;
let _footTarget = null;

function _setBody(html) {
  const body = _bodyTarget || document.getElementById('ao-body');
  if (body) body.innerHTML = html;
}

function _setFoot(html) {
  const foot = _footTarget || document.getElementById('ao-foot');
  if (foot) foot.innerHTML = html;
}

function _err(html) {
  return `<p class="admin-error" role="alert" style="font-size:0.86rem;margin:8px 0;">${html}</p>`;
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
  // Mark the engine step complete (best-effort) then move forward (linearly).
  try { _status = await _post(`${SETUP}/advance/${stepKey}`); }
  catch { await _refreshStatus().catch(() => {}); }
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
  await _refreshStatus().catch(() => {});
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
function _renderNav() {
  const nav = document.getElementById('ao-nav');
  if (!nav) return;
  const last = _stepIndex >= STEPS.length - 1;
  nav.innerHTML =
    (_stepIndex > 0
      ? '<button type="button" class="cal-btn" id="ao-back">← Back</button>'
      : '<span></span>') +
    `<button type="button" class="cal-btn" id="ao-skip">${last ? 'Finish' : 'Skip for now →'}</button>`;
  const back = document.getElementById('ao-back');
  if (back) back.onclick = () => { if (!_busy) _prevStep(); };
  const skip = document.getElementById('ao-skip');
  if (skip) skip.onclick = () => { if (!_busy) _nextStep(); };
}

// ── STEP 0: Welcome (B1) ─────────────────────────────────────────────────────
//
// A short, honest preview of the journey and a plain-language list of what
// Applicant never does. Reuses the shared `.admin-card` framing + `.ao-step-*`
// classes so it matches every other step. The persistent Skip/Back nav already
// lets the user move on; this step just adds an explicit "Let's go" foot button.
function _renderWelcome() {
  _setBody(`
    <h2 class="ao-step-title">Welcome to Applicant</h2>
    <p class="ao-step-desc">
      Just one thing to start: connect a model. Everything about your job search,
      Applicant can learn as you go — drop in a résumé to jump-start it, or simply
      tell it what you're looking for in chat.
    </p>
    <div class="admin-card">
      <h2 style="margin:0 0 6px;font-size:0.95em;">What you'll set up</h2>
      <ol style="margin:0 0 2px 18px;padding:0;font-size:0.88rem;line-height:1.5;">
        <li>Connect a model — a local model or a cloud provider. <em>(the only required step)</em></li>
        <li>Your profile — optional. Add a résumé to speed things up, or skip it and tell Applicant in chat.</li>
      </ol>
      <p style="margin:8px 0 0;font-size:0.82rem;opacity:0.7;">Applicant won't start applying until it knows the essentials (target roles, work mode, locations, salary floor, key skills, and a résumé) — it'll ask for whatever's still missing. Notifications, fonts and the automation sandbox are optional too — set them up any time in Settings.</p>
    </div>
    <div class="admin-card">
      <h2 style="margin:0 0 6px;font-size:0.95em;">How Applicant works — and what it never does</h2>
      <ul style="margin:0 0 2px 18px;padding:0;font-size:0.88rem;line-height:1.5;">
        ${NEVER_DOES.map((t) => `<li>${esc(t)}</li>`).join('')}
      </ul>
    </div>
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
    <h2 class="ao-step-title">Connect a model ${_tip('Applicant uses an AI model to read job posts and write your materials. Add a local model or a cloud provider below, then enable it and pick a model.')}</h2>
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
            `Could not connect this model to the application engine: ${gateErr.message || 'unknown error'}. `,
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
  _setBody(`
    <h2 class="ao-step-title">Notifications ${_tip('How Applicant reaches you — Discord and/or email — for your daily digest and approval requests. Optional: you can skip this and set it up later in Settings.')}</h2>
    <p class="ao-step-desc">Add a Discord webhook and/or an email address so Applicant can send you updates and ask for approvals. This is optional — you can <strong>Skip for now</strong> and set it up later.</p>
    <div class="admin-card">
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Discord webhook
            ${_tip('In your Discord server: Settings → Integrations → Webhooks → New Webhook → Copy URL.')}
          </label>
          <input id="ao-ch-discord" class="settings-select" type="text" placeholder="https://discord.com/api/webhooks/..." value="${esc(cur.discord_webhook_url || '')}" />
        </div>
        <div class="settings-row">
          <label class="settings-label">Email / SMTP
            ${_tip('An Apprise-style URL, e.g. mailto://user:pass@gmail.com. You can add several, comma-separated.')}
          </label>
          <input id="ao-ch-email" class="settings-select" type="text" placeholder="mailto://user:pass@smtp.example.com" value="${esc(cur.apprise_urls || '')}" />
        </div>
        <div style="font-size:11px;opacity:0.6;margin-top:4px;">Add either or both — or skip for now.</div>
      </div>
    </div>
    <div class="admin-card ao-help">
      <h2>How to set these up</h2>
      <p style="margin:4px 0 2px;"><strong>Discord webhook</strong></p>
      <ol style="margin:0 0 8px 18px;padding:0;">
        <li>In your Discord server: <strong>Server Settings → Integrations → Webhooks</strong>.</li>
        <li><strong>New Webhook</strong>, choose the channel for your updates, then <strong>Copy Webhook URL</strong>.</li>
        <li>Paste it into the Discord webhook field above.</li>
      </ol>
      <p style="margin:4px 0 2px;"><strong>Email / SMTP</strong> — an Apprise-style URL:</p>
      <ul style="margin:0 0 6px 18px;padding:0;">
        <li>Gmail: <code>mailto://you:APP_PASSWORD@gmail.com</code> — use a Google <em>App Password</em>, not your login password.</li>
        <li>Other SMTP: <code>mailtos://user:pass@smtp.yourhost.com:587</code></li>
        <li>Add several by separating them with commas.</li>
      </ul>
      <p style="margin:0;opacity:0.6;">Full URL formats: github.com/caronc/apprise/wiki</p>
    </div>
    <div class="admin-card">
      <h2><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;opacity:0.6"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>Test</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">Save your channels and send a test notification to verify they work.</div>
      <div class="settings-row">
        <span id="ao-ch-test-msg" style="font-size:11px;"></span>
        <button class="admin-btn-add" id="ao-ch-test" style="margin-left:auto;">Send a test</button>
      </div>
    </div>
    <div class="admin-card">
      <h2>Quiet hours ${_tip('When on, Applicant holds approval requests and your daily digest until quiet hours end, so it never pings you overnight. Anything urgent — like an error that needs you — always comes through right away.')}</h2>
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
            <label class="settings-label">Time zone ${_tip('Optional. An IANA name like America/Phoenix or Europe/London. Leave blank to use UTC.')}</label>
            <input id="ao-qh-tz" class="settings-select" type="text" placeholder="UTC" value="${esc(qh.tz || '')}" />
          </div>
        </div>
      </div>
      <div id="ao-qh-msg" style="margin-top:6px;"></div>
      <div class="settings-row" style="margin-top:8px;">
        <span id="ao-qh-save-msg" style="font-size:11px;"></span>
        <button class="admin-btn-add" id="ao-qh-save" style="margin-left:auto;">Save quiet hours</button>
      </div>
    </div>
    <div class="admin-card">
      <h2>Email reminder timing ${_tip('How long Applicant waits before also emailing you about an approval it has not heard back on. The in-app and Discord nudges come first; email is the slower backstop.')}</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">If an approval still needs you after this long, Applicant also emails you as a backstop. Lower = emailed sooner; higher = fewer emails.</div>
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
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-ch-save">Save &amp; continue</button>`);

  const collect = () => ({
    discord_webhook_url: (document.getElementById('ao-ch-discord').value || '').trim(),
    apprise_urls: (document.getElementById('ao-ch-email').value || '').trim(),
  });

  // Same save-then-test handler shape as settings.js's reminder Test button:
  // disable, status into a span, success → `.admin-success`, failure → `.admin-error`.
  const testBtn = document.getElementById('ao-ch-test');
  const testMsg = document.getElementById('ao-ch-test-msg');
  testBtn.onclick = async () => {
    const body = collect();
    if (!body.discord_webhook_url && !body.apprise_urls) {
      testMsg.textContent = 'Add a channel first.'; testMsg.className = 'admin-error'; return;
    }
    testBtn.disabled = true;
    testMsg.textContent = 'Saving + sending…'; testMsg.className = '';
    try {
      await _post(`${SETUP}/channels`, body);
      const res = await _post(`${SETUP}/channels/test`, {});
      const ch = (res.channels || []).join(', ') || 'your channels';
      testMsg.textContent = `Test sent to ${ch}.`; testMsg.className = 'admin-success';
    } catch (e) {
      testMsg.textContent = 'Failed: ' + (e.message || 'Test failed.'); testMsg.className = 'admin-error';
    } finally {
      testBtn.disabled = false;
    }
  };

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
    const body = {
      enabled,
      start: (document.getElementById('ao-qh-start').value || '22:00'),
      end: (document.getElementById('ao-qh-end').value || '07:00'),
      tz: (document.getElementById('ao-qh-tz').value || '').trim(),
    };
    qhSave.disabled = true;
    qhSaveMsg.textContent = 'Saving…'; qhSaveMsg.className = '';
    try {
      await _post(`${SETUP}/channels/quiet-hours`, body);
      qhSaveMsg.textContent = enabled ? 'Quiet hours saved.' : 'Notifications on 24/7.';
      qhSaveMsg.className = 'admin-success';
    } catch (e) {
      qhSaveMsg.textContent = 'Failed: ' + (e.message || 'Could not save.'); qhSaveMsg.className = 'admin-error';
    } finally {
      qhSave.disabled = false;
    }
  };

  // Email reminder timing (FR-NOTIF-2): the escalation delay before email backstops
  // an unanswered approval. Saved on its own (no URL needed) so it works the same in
  // the wizard and in Settings.
  const etSave = document.getElementById('ao-et-save');
  const etSaveMsg = document.getElementById('ao-et-save-msg');
  if (etSave) etSave.onclick = async () => {
    const raw = parseInt(document.getElementById('ao-ch-email-timeout').value, 10);
    const minutes = Number.isFinite(raw) ? Math.max(1, Math.min(1440, raw)) : 15;
    etSave.disabled = true;
    etSaveMsg.textContent = 'Saving…'; etSaveMsg.className = '';
    try {
      await _post(`${SETUP}/channels`, { email_timeout_minutes: minutes });
      etSaveMsg.textContent = `Email backstop after ${minutes} min.`;
      etSaveMsg.className = 'admin-success';
    } catch (e) {
      etSaveMsg.textContent = 'Failed: ' + (e.message || 'Could not save.'); etSaveMsg.className = 'admin-error';
    } finally {
      etSave.disabled = false;
    }
  };

  document.getElementById('ao-ch-save').onclick = async () => {
    if (_busy) return;
    const body = collect();
    if (!body.discord_webhook_url && !body.apprise_urls) {
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
    btn.textContent = 'Available';
    note.textContent = 'Ready. Turn it on for a session from the live-session window when you need it.';
  } else {
    btn.disabled = true;
    btn.textContent = 'Turn on';
    note.textContent = 'Coming in a future update — desktop help isn’t set up on this sandbox yet.';
  }
}

async function _renderSandbox() {
  let cur = {};
  try { cur = await _fetchJSON(`${SETUP}/sandbox-connection`); } catch { cur = {}; }
  const conn = cur.connection || {};
  // Default the picker to whatever the engine has selected.
  const isWindows = (cur.backend === 'proxmox-windows');

  _setBody(`
    <h2 class="ao-step-title">Automation sandbox ${_tip('Where Applicant runs the browser it drives — and that you take over when a human step is needed. The built-in sandbox works out of the box. Advanced: point it at your own Windows VM (on Proxmox) so the browser is real Chrome on real Windows.')}</h2>
    <p class="ao-step-desc">Pick where Applicant runs the browser. Most people keep the built-in sandbox.</p>
    <div class="admin-card">
      <div class="settings-col">
        <div class="settings-row">
          <label class="settings-label">Sandbox</label>
          <select id="ao-sb-backend" class="settings-select">
            <option value="local"${isWindows ? '' : ' selected'}>Built-in sandbox (recommended)</option>
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
              <input id="ao-sb-tokensecret" class="settings-select" type="password" placeholder="secret" autocomplete="new-password" style="flex:1;" />
            </div>
          </div>
          <div class="settings-row">
            <label class="settings-label">Windows VM id ${_tip('The VMID of your licensed Windows VM (Chrome + guest agent + RDP enabled).')}</label>
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
              <input id="ao-sb-rdppass" class="settings-select" type="password" placeholder="password" autocomplete="new-password" style="flex:1;" />
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
          <label class="settings-label">Desktop help ${_tip('Lets the assistant handle steps that live outside the web page — like a file-upload dialog or another desktop window — during a live session. You stay in control: it never creates accounts, clears verifications, or submits, and it asks before each step. You turn it on per live session.')}</label>
          <div style="display:flex;flex-direction:column;gap:6px;flex:1;">
            <button class="cal-btn" id="ao-desktop-toggle" type="button" disabled
                    title="Let the assistant help with desktop steps the browser can't reach">Turn on</button>
            <p id="ao-desktop-note" style="margin:0;opacity:0.65;font-size:0.8rem;">
              Coming in a future update — desktop help isn’t set up on this sandbox yet.
            </p>
            <p style="margin:0;opacity:0.55;font-size:0.78rem;">
              Best-effort and optional. The assistant only helps with desktop steps you
              approve, one at a time — the parts only you should do (accounts, verifications,
              the final submit) always stay with you.
            </p>
          </div>
        </div>
      </div>
    </div>
    <div id="ao-sb-msg"></div>
  `);
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-sb-save">Save &amp; continue</button>`);

  // Desktop help (FR-CUA) — present-but-grayed until the desktop helper is baked
  // into the sandbox image and the engine's health preflight passes. The actual
  // opt-in is per live session (in the live-session surface); here we surface the
  // capability + the honest best-effort caveat, and reflect the locked state.
  _renderDesktopAssistSetting().catch(() => {});

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
      if (msgEl) msgEl.innerHTML = _err('Add the Proxmox API URL, node, token id and the Windows VM id to continue.');
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
    <h2 class="ao-step-title">Fonts ${_tip('To make your generated resume look exactly like yours, Applicant may need the fonts your resume uses. Upload a resume to check, then add any missing fonts. This step is optional — you can skip it.')}</h2>
    <p class="ao-step-desc">Optional: check which fonts your resume needs and add any that are missing, so your generated resume keeps its look.</p>
    <div class="admin-card">
      <div class="settings-col">
        <label class="settings-label" style="min-width:0;">Check a resume for required fonts</label>
        <div class="settings-row">
          <button type="button" class="cal-btn" id="ao-font-pick">Choose a resume…</button>
          <input id="ao-font-detect" type="file" accept=".docx,.doc,.pdf,.rtf,.txt" style="display:none;" />
        </div>
        <div class="attach-strip" id="ao-font-strip"></div>
      </div>
    </div>
    <div id="ao-font-report"></div>
    <p style="font-size:0.82rem;opacity:0.7;margin:12px 0 0;">Installed fonts: <span id="ao-font-installed">${installed.length ? esc(installed.join(', ')) : 'none yet'}</span></p>
    <div id="ao-font-msg"></div>
  `);
  _setFoot(`
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
  document.getElementById('ao-font-skip').onclick = finishFonts;
  document.getElementById('ao-font-continue').onclick = finishFonts;
}

// ── STEP 4: Onboarding intake (resumable interview) ─────────────────────────

// Per-section form fields. Kept plain-language. Each field: {name, label, type}.
const SECTION_FORMS = {
  identity: {
    title: 'About you',
    fields: [
      { name: 'full_legal_name', label: 'Full legal name', type: 'text' },
      { name: 'preferred_name', label: 'Preferred name', type: 'text' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'phone', label: 'Phone', type: 'text' },
      { name: 'address', label: 'Mailing address', type: 'text' },
      { name: 'linkedin', label: 'LinkedIn URL', type: 'text' },
      { name: 'portfolio', label: 'Portfolio / GitHub URL', type: 'text' },
    ],
  },
  work_authorization: {
    title: 'Work authorization',
    fields: [
      { name: 'authorized_country', label: 'Country you are authorized to work in', type: 'text' },
      { name: 'authorized', label: 'Authorized to work there?', type: 'yesno' },
      { name: 'needs_sponsorship', label: 'Will you need visa sponsorship now or in future?', type: 'yesno' },
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
    fields: [
      { name: 'salary_floor', label: 'Salary floor (hard minimum)', type: 'text' },
      { name: 'desired_salary', label: 'Desired salary / range', type: 'text' },
      { name: 'currency', label: 'Currency', type: 'text' },
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
    repeat: true,
    fields: [
      { name: 'name', label: 'Name', type: 'text' },
      { name: 'relationship', label: 'Relationship / title', type: 'text' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'phone', label: 'Phone', type: 'text' },
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
    desc: 'Entirely optional. The default for every field is "decline to self-identify" — we never guess these.',
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

// Intake fields reuse the shared `.settings-col`/`.settings-label`/
// `.settings-select` form classes (same as Settings' field rows), so inputs,
// selects and textareas match the rest of the app and track the theme.
function _fieldHTML(f, value) {
  const v = value == null ? '' : value;
  if (f.type === 'textarea') {
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label><textarea class="settings-select" name="${esc(f.name)}" rows="3" style="resize:vertical;">${esc(v)}</textarea></div>`;
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
    const opts = ['decline to self-identify', 'prefer to answer'];
    return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label>
      <select class="settings-select" name="${esc(f.name)}">
        ${opts.map((o) => `<option value="${esc(o)}"${(v || 'decline to self-identify') === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}
      </select>
      <input class="settings-select" name="${esc(f.name)}__detail" type="text" placeholder="Your answer (optional)" value="" style="margin-top:6px;" />
      </div>`;
  }
  return `<div class="settings-col" style="margin-bottom:12px;"><label class="settings-label" style="min-width:0;">${esc(f.label)}</label><input class="settings-select" type="${esc(f.type)}" name="${esc(f.name)}" value="${esc(v)}" /></div>`;
}

function _collectForm(formEl) {
  const out = {};
  formEl.querySelectorAll('input, textarea, select').forEach((inp) => {
    if (!inp.name) return;
    out[inp.name] = inp.value;
  });
  return out;
}

async function _renderOnboarding() {
  await _ensureCampaign();
  _onboarding = await _fetchJSON(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}`);
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
      <p style="margin:0;font-size:0.86rem;">Applicant has what it needs to start applying. Anything else here just makes your applications smoother — it's all optional.</p>
    </div>`;
  }
  const missing = Array.isArray(s.apply_missing) ? s.apply_missing : [];
  if (!missing.length) return '';
  return `<div class="admin-card" style="border-left:3px solid var(--accent-warm, #d8a23a);">
    <p style="margin:0 0 4px;font-size:0.86rem;"><strong>This part is optional.</strong> Add a résumé to fill it in fast, or just tell Applicant in chat — it'll keep learning as you go.</p>
    <p style="margin:0;font-size:0.84rem;opacity:0.85;">Before it can start applying, Applicant still needs: ${esc(missing.join(', '))}.</p>
  </div>`;
}

async function _renderIntakeSection() {
  const key = INTAKE_SECTIONS[_intakeIndex];
  const total = INTAKE_SECTIONS.length;
  const saved = (_onboarding.intake && _onboarding.intake[key]) || {};

  if (key === 'base_resume') return _renderBaseResume(saved);

  const spec = SECTION_FORMS[key];
  const fieldsHTML = spec.fields.map((f) => _fieldHTML(f, saved[f.name])).join('');
  _setBody(`
    <div class="ao-intake-progress">Profile step ${_intakeIndex + 1} of ${total}</div>
    <h2 class="ao-step-title">${esc(spec.title)}</h2>
    ${spec.desc ? `<p class="ao-step-desc">${esc(spec.desc)}</p>` : ''}
    <form id="ao-intake-form">${fieldsHTML}</form>
    <div id="ao-intake-msg"></div>
  `);
  _setFoot(`
    ${_intakeIndex > 0 ? '<button class="cal-btn" id="ao-intake-back">Back</button>' : ''}
    <button class="cal-btn cal-btn-primary" id="ao-intake-next">Save &amp; continue</button>
  `);

  const back = document.getElementById('ao-intake-back');
  if (back) back.onclick = () => { _intakeIndex = Math.max(0, _intakeIndex - 1); _renderIntakeSection(); };

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
      Your resume uses fonts that aren't installed yet. Add them below so your
      generated resume keeps its look.
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
    try {
      await _buildPreview();
      document.getElementById('ao-resume-next').disabled = false;
    } catch (e) {
      st.innerHTML = _err(esc(e.message || 'Could not build preview.'));
    }
  };
}

// The resume upload LIFTS fileHandler.js's picker (chip preview + upload-progress
// whirlpool), pointed at the existing /base-resume engine proxy.
function _renderBaseResume(saved) {
  const total = INTAKE_SECTIONS.length;
  _setBody(`
    <div class="ao-intake-progress">Profile step ${_intakeIndex + 1} of ${total}</div>
    ${_applyReadinessBanner()}
    <h2 class="ao-step-title">Start with your resume ${_tip('Applicant reads your resume and fills in the rest of your profile for you — you just review and fix anything it got wrong. After upload we also build a high-fidelity version and show you a preview to accept or reject.')}</h2>
    <p class="ao-step-desc">Optional but recommended: upload your current resume and we’ll read it to fill in the profile fields that follow — so you don’t have to type everything by hand. Prefer to skip it? Use <strong>Skip for now</strong> and just tell Applicant what you want in chat. You can edit every field afterward.</p>
    <div class="admin-card">
      <div class="settings-row">
        <button type="button" class="cal-btn" id="ao-resume-pick">Choose your resume…</button>
        <input id="ao-resume-file" type="file" accept=".docx,.doc,.pdf,.rtf,.txt,.md" style="display:none;" />
      </div>
      <div class="attach-strip" id="ao-resume-strip"></div>
    </div>
    <div id="ao-resume-status">${saved && saved.document_path ? '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">A resume is already on file. Re-upload to replace it.</p>' : ''}</div>
    <div id="ao-conflicts"></div>
    <div id="ao-preview"></div>
    <div id="ao-resume-msg"></div>
  `);
  _setFoot(`
    <button class="cal-btn" id="ao-intake-back">Back</button>
    <button class="cal-btn cal-btn-primary" id="ao-resume-next" ${saved && saved.document_path ? '' : 'disabled'}>Continue</button>
  `);

  document.getElementById('ao-intake-back').onclick = () => {
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
    st.innerHTML = '<p style="font-size:0.82rem;opacity:0.75;">Reading your resume…</p>';
    try {
      await picker.uploadPending();      // chip + progress whirlpool, posts to /base-resume
      const res = picker.getLastResponse() || {};
      // Resume-first: re-fetch the intake so the upcoming steps render PREFILLED
      // with what we read (identity, work history, education, skills) — the user
      // reviews + corrects rather than typing from scratch.
      try {
        _onboarding = await _fetchJSON(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}`);
      } catch { /* keep last-known intake; prefill is best-effort */ }
      st.innerHTML = `<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Read ${res.attribute_count || 0} details from your resume — we’ve filled in the next steps for you to review.</p>`;
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

      await _buildPreview();
      document.getElementById('ao-resume-next').disabled = false;
    } catch (e) {
      st.innerHTML = _err(esc(e.message || 'Could not read the resume.'));
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
      <p style="color:var(--accent-warm, #d8a23a);font-size:0.86rem;margin:0 0 8px;">A few details from your resume differ from what you told us. Pick which to keep:</p>
      ${conflicts.map((c, i) => `
        <div data-attr="${esc(c.attribute)}" data-i="${i}" style="margin:8px 0;display:flex;flex-direction:column;gap:2px;">
          <strong>${esc(c.attribute)}</strong>
          <label style="font-weight:normal;font-size:0.86rem;"><input type="radio" name="ao-conf-${i}" value="interview" checked> Keep: ${esc(c.interview_value)}</label>
          <label style="font-weight:normal;font-size:0.86rem;"><input type="radio" name="ao-conf-${i}" value="parsed"> Use resume: ${esc(c.parsed_value)}</label>
        </div>`).join('')}
      <button class="cal-btn" id="ao-conf-apply" style="margin-top:6px;">Apply choices</button>
    </div>`;
  document.getElementById('ao-conf-apply').onclick = async () => {
    try {
      for (const c of conflicts) {
        const i = wrap.querySelector(`[data-attr="${CSS.escape(c.attribute)}"]`).getAttribute('data-i');
        const choice = wrap.querySelector(`input[name="ao-conf-${i}"]:checked`).value;
        const value = choice === 'parsed' ? c.parsed_value : c.interview_value;
        await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/confirm-conflict`, {
          attribute: c.attribute, value,
        });
      }
      wrap.innerHTML = '<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Choices applied.</p>';
    } catch (e) {
      _toast(e.message || 'Could not apply choices.');
    }
  };
}

async function _buildPreview() {
  const wrap = document.getElementById('ao-preview');
  wrap.innerHTML = '<p style="font-size:0.82rem;opacity:0.75;">Building a polished version…</p>';
  try {
    const p = await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/preview`, {});
    const note = p.fidelity_ok ? 'Looks like a faithful match.' : 'Some formatting may differ.';
    // `notes` may come back as an array, a single string, or be absent — coerce to
    // an array so a string value doesn't crash the preview on `.map` (it has a
    // truthy `.length` but no `.map`), which surfaced as "Preview unavailable".
    const notesList = Array.isArray(p.notes) ? p.notes : (p.notes ? [String(p.notes)] : []);
    wrap.innerHTML = `
      <div class="admin-card">
        <p style="margin:0 0 8px;">We built a high-fidelity version of your resume (${esc(String(p.page_count || '?'))} page(s)). ${esc(note)}</p>
        ${notesList.length ? `<ul>${notesList.map((n) => `<li>${esc(String(n))}</li>`).join('')}</ul>` : ''}
        <div class="settings-row" style="margin-top:6px;">
          <button class="cal-btn cal-btn-primary" id="ao-prev-accept">Use this version</button>
          <button class="cal-btn" id="ao-prev-reject">Keep my original</button>
          <span id="ao-prev-status" style="font-size:0.82rem;opacity:0.75;"></span>
        </div>
      </div>`;
    document.getElementById('ao-prev-accept').onclick = async () => {
      try { await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/accept`, {});
        document.getElementById('ao-prev-status').textContent = 'Using the polished version.';
      } catch (e) { _toast(e.message || 'Could not accept.'); }
    };
    document.getElementById('ao-prev-reject').onclick = async () => {
      try { await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/reject`, {});
        document.getElementById('ao-prev-status').textContent = 'Keeping your original.';
      } catch (e) { _toast(e.message || 'Could not reject.'); }
    };
  } catch (e) {
    wrap.innerHTML = `<p style="font-size:0.82rem;opacity:0.75;">Preview unavailable: ${esc(e.message || '')}</p>`;
  }
}

async function _nextIntakeOrComplete() {
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
    if (missing.length) {
      const idx = INTAKE_SECTIONS.indexOf(missing[0]);
      _intakeIndex = idx >= 0 ? idx : 0;
      await _renderIntakeSection();
      document.getElementById('ao-intake-msg')
        && (document.getElementById('ao-intake-msg').innerHTML = _err('Please finish this section to continue.'));
    } else {
      _toast(e.message || 'Could not finish onboarding.');
    }
  }
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
    const readyLine = ready
      ? 'Applicant is ready to start applying for you.'
      : `Applicant is set up. Before it starts applying it still needs: ${esc(applyMissing.join(', '))} — just tell it in chat or add a résumé any time, and it'll begin automatically.`;
    _setBody(`<div style="text-align:center;padding:30px 0;"><h2 style="margin:0 0 8px;">You’re all set!</h2><p style="max-width:460px;margin:0 auto;">${readyLine}</p></div>`);
    _setFoot('<button class="cal-btn cal-btn-primary" id="ao-finish">Get started</button>');
    document.getElementById('ao-finish').onclick = _dismiss;
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

function _dismiss() {
  // Tear down a11y bindings before removing the overlay from the DOM.
  if (_overlayA11yCleanup) { _overlayA11yCleanup(); _overlayA11yCleanup = null; }
  // Hand the shared endpoint manager back to Settings before tearing down the
  // overlay, so it isn't removed from the DOM along with the overlay.
  _restoreEndpointManager();
  if (_overlay && _overlay.parentNode) _overlay.parentNode.removeChild(_overlay);
  _overlay = null;
  // Re-run the feature-activation layer so the job sections light up now that the
  // engine gate is open. app.js exposes the refresh; fall back to a reload.
  try {
    if (typeof window.refreshApplicantFeatures === 'function') {
      window.refreshApplicantFeatures();
      return;
    }
  } catch { /* fall through */ }
  try { window.location.reload(); } catch { /* no-op */ }
}

// ── public entry: maybe launch the wizard on boot ───────────────────────────

// Returns true when the setup wizard was launched (setup incomplete), false
// otherwise (setup already complete, or the engine is unreachable). Callers use
// this to decide whether to take precedence over a post-login landing surface:
// the wizard always wins, and the home-base Portal only opens when this is false.
export async function maybeLaunchOnboarding() {
  if (_overlay) return true; // already open
  let status;
  try { status = await _refreshStatus(); }
  catch { return false; } // engine unreachable -> don't block; the user can still log in
  if (!status) return false;
  const complete = status.llm_configured && status.onboarding_complete;
  if (complete) return false; // nothing to do

  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
  if (_overlayA11yCleanup) _overlayA11yCleanup();
  _overlayA11yCleanup = window.uiModule && window.uiModule.initModalA11y
    ? window.uiModule.initModalA11y(_overlay, _dismiss)
    : null;
  _stepIndex = _firstIncompleteStep();
  // Pre-create the campaign once the LLM gate is open so onboarding resumes cleanly.
  if (status.llm_configured) { try { await _ensureCampaign(); } catch { /* later */ } }
  await _renderStep();
  return true;
}

// Force-open the wizard (e.g. the "Re-run setup" button in Settings) regardless of
// completion, starting at the first step so any prior choice can be reviewed/changed.
export async function launchOnboarding() {
  if (_overlay) return;
  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
  if (_overlayA11yCleanup) _overlayA11yCleanup();
  _overlayA11yCleanup = window.uiModule && window.uiModule.initModalA11y
    ? window.uiModule.initModalA11y(_overlay, _dismiss)
    : null;
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
    out.textContent = 'Working…';
    try {
      const res = await _post(`${OPS}/update/trigger`, {});
      out.textContent = res.message || (res.started ? 'Update started.' : 'Nothing to do.');
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
  _bodyTarget = body;
  _footTarget = foot;
  try {
    await render();
  } finally {
    // Restore so a later wizard launch keeps targeting its own DOM. Only the
    // synchronous body/foot build reads these targets; later click handlers
    // address their own elements by id.
    _bodyTarget = prevBody;
    _footTarget = prevFoot;
  }
  return true;
}

if (typeof window !== 'undefined') window.mountApplicantSettingsStep = mountSettingsStep;

export default { maybeLaunchOnboarding, launchOnboarding, neverDoesList, mountSettingsStep };
