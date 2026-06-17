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

let _overlay = null;
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
const STEPS = [
  { key: 'llm',        title: 'Connect a model',  done: (s) => !!(s && s.llm_configured) },
  { key: 'channels',   title: 'Notifications',    done: (s) => !!(s && s.channels_configured) },
  { key: 'sandbox',    title: 'Automation sandbox', done: (s) => !!(s && Array.isArray(s.steps_complete) && s.steps_complete.includes('sandbox')) },
  { key: 'fonts',      title: 'Fonts',            done: (s) => !!(s && s.fonts_ready) },
  { key: 'onboarding', title: 'Your profile',     done: (s) => !!(s && s.onboarding_complete) },
];

// Intake sub-sections (the comprehensive Workday-ready interview). Each renders a
// small form; data is saved per-section so the interview is fully resumable.
const INTAKE_SECTIONS = [
  'identity', 'work_authorization', 'location', 'target_roles', 'compensation',
  'work_history', 'education', 'references', 'key_attributes', 'eeo',
  'base_resume', 'campaign_criteria',
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

function _setBody(html) {
  const body = document.getElementById('ao-body');
  if (body) body.innerHTML = html;
}

function _setFoot(html) {
  const foot = document.getElementById('ao-foot');
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
    if (step.key === 'llm') return await _renderLLM();
    if (step.key === 'channels') return await _renderChannels();
    if (step.key === 'sandbox') return await _renderSandbox();
    if (step.key === 'fonts') return await _renderFonts();
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
      const isLocal = /localhost|127\.0\.0\.1|0\.0\.0\.0|::1|11434/.test(chosen.base_url || '');
      const provider = isLocal ? 'ollama' : 'openai';
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
            `Saved your model, but the application engine could not be configured automatically: ${gateErr.message || 'unknown error'}. You can continue; if job features stay locked, re-open this step.`,
          ));
        }
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
    <div id="ao-sb-msg"></div>
  `);
  _setFoot(`<button class="cal-btn cal-btn-primary" id="ao-sb-save">Save &amp; continue</button>`);

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

// The resume upload LIFTS fileHandler.js's picker (chip preview + upload-progress
// whirlpool), pointed at the existing /base-resume engine proxy.
function _renderBaseResume(saved) {
  const total = INTAKE_SECTIONS.length;
  _setBody(`
    <div class="ao-intake-progress">Profile step ${_intakeIndex + 1} of ${total}</div>
    <h2 class="ao-step-title">Upload your resume ${_tip('Applicant reads your resume to fill in your profile and to match its style. After upload we build a high-fidelity version and show you a preview to accept or reject.')}</h2>
    <p class="ao-step-desc">Upload your current resume. We’ll read it to fill in your profile, then show you a polished version to approve.</p>
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
      st.innerHTML = `<p class="admin-success" style="font-size:0.86rem;margin:8px 0;">Read ${res.attribute_count || 0} details from your resume.</p>`;
      if (res.requires_confirmation && (res.conflicts || []).length) {
        _renderConflicts(res.conflicts);
      } else {
        document.getElementById('ao-conflicts').innerHTML = '';
      }
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
      // Persist the base_resume section so it counts as complete + reconcile is done.
      _onboarding = await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/section`, {
        section: 'base_resume', data: { uploaded: true },
      });
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
    wrap.innerHTML = `
      <div class="admin-card">
        <p style="margin:0 0 8px;">We built a high-fidelity version of your resume (${esc(String(p.page_count || '?'))} page(s)). ${esc(note)}</p>
        ${(p.notes && p.notes.length) ? `<ul>${p.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
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
  _setBody('<div style="text-align:center;padding:30px 0;"><h2 style="margin:0 0 8px;">You’re all set!</h2><p>Applicant is ready to start working for you.</p></div>');
  _setFoot('<button class="cal-btn cal-btn-primary" id="ao-finish">Get started</button>');
  document.getElementById('ao-finish').onclick = _dismiss;
  const nav = document.getElementById('ao-nav');
  if (nav) nav.innerHTML = '';
  _renderRail();
}

function _dismiss() {
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
  const complete = status.llm_configured && status.channels_configured && status.onboarding_complete;
  if (complete) return false; // nothing to do

  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
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
  try { await _refreshStatus(); } catch { /* engine down — still show the wizard */ }
  if (_status && _status.llm_configured) { try { await _ensureCampaign(); } catch { /* later */ } }
  _stepIndex = 0;
  await _renderStep();
}

// Expose a global so the Settings panel can relaunch setup without importing this module.
if (typeof window !== 'undefined') window.launchApplicantSetup = launchOnboarding;

export default { maybeLaunchOnboarding, launchOnboarding };
