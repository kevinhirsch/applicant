// static/js/applicantOnboarding.js
//
// First-run setup wizard — the blocking, resumable overlay that runs right after
// login when the engine reports setup/onboarding is incomplete. It walks a brand
// new user through, in order:
//
//   1. Connect a model  -> /api/applicant/setup/llm (+ model-endpoints catalog)
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

const SETUP = '/api/applicant/setup';

let _overlay = null;
let _campaignId = null;
let _status = null;        // engine setup status
let _onboarding = null;    // engine onboarding state
let _stepIndex = 0;        // active step in STEPS
let _busy = false;

// Ordered wizard steps. `done(status)` reads the engine status to decide if the
// step is already satisfied (drives resume + the progress rail).
const STEPS = [
  { key: 'llm',        title: 'Connect a model',  done: (s) => !!(s && s.llm_configured) },
  { key: 'channels',   title: 'Notifications',    done: (s) => !!(s && s.channels_configured) },
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

function _postForm(url, formData) {
  return _fetchJSON(url, { method: 'POST', body: formData });
}

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
  const o = document.createElement('div');
  o.id = 'applicant-onboarding-overlay';
  o.className = 'ao-overlay';
  // Blocking: trap focus, no dismiss-into-app. The user can't escape into the job
  // features until setup is done (the engine also blocks server-side).
  o.setAttribute('role', 'dialog');
  o.setAttribute('aria-modal', 'true');
  o.setAttribute('aria-label', 'Set up Applicant');
  o.innerHTML = `
    <div class="ao-card">
      <header class="ao-head">
        <h1 class="ao-title">Welcome — let's get you set up</h1>
        <p class="ao-sub">A few quick steps so Applicant can start working for you.</p>
        <ol class="ao-rail" id="ao-rail"></ol>
      </header>
      <div class="ao-body" id="ao-body"></div>
      <footer class="ao-foot" id="ao-foot"></footer>
    </div>`;
  // Swallow click-throughs to the app behind the overlay.
  o.addEventListener('click', (ev) => { if (ev.target === o) ev.stopPropagation(); });
  return o;
}

function _renderRail() {
  const rail = document.getElementById('ao-rail');
  if (!rail) return;
  rail.innerHTML = STEPS.map((step, i) => {
    const done = step.done(_status);
    const cur = i === _stepIndex;
    const cls = `ao-rail-step${done ? ' done' : ''}${cur ? ' current' : ''}`;
    const mark = done ? '✓' : (i + 1);
    return `<li class="${cls}"><span class="ao-rail-num">${mark}</span>${esc(step.title)}</li>`;
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
  return `<p class="ao-error" role="alert">${html}</p>`;
}

function _tip(text) {
  return `<span class="ao-tip" title="${esc(text)}" aria-label="${esc(text)}">?</span>`;
}

// ── render the active step ──────────────────────────────────────────────────

async function _renderStep() {
  _renderRail();
  const step = STEPS[_stepIndex];
  try {
    if (step.key === 'llm') return await _renderLLM();
    if (step.key === 'channels') return await _renderChannels();
    if (step.key === 'fonts') return await _renderFonts();
    if (step.key === 'onboarding') return await _renderOnboarding();
  } catch (e) {
    _setBody(_err(esc(e.message || 'Something went wrong.')));
    _setFoot('');
  }
  return undefined;
}

async function _advanceAndContinue(stepKey) {
  // Mark the engine step complete (best-effort) then move to the next incomplete.
  try { _status = await _post(`${SETUP}/advance/${stepKey}`); }
  catch { await _refreshStatus().catch(() => {}); }
  await _goToFirstIncompleteOrFinish();
}

async function _goToFirstIncompleteOrFinish() {
  await _refreshStatus().catch(() => {});
  if (STEPS.every((s) => s.done(_status))) { await _finish(); return; }
  _stepIndex = _firstIncompleteStep();
  await _renderStep();
}

// ── STEP 1: LLM ─────────────────────────────────────────────────────────────

async function _renderLLM() {
  _setBody(`
    <h2 class="ao-step-title">Connect a model ${_tip('Applicant uses an AI model to read job posts and write your materials. Pick a provider, paste a key, and choose a model.')}</h2>
    <p class="ao-step-desc">Add a provider below, then pick the model you want to use.</p>
    <div class="ao-field">
      <label>Provider address
        ${_tip('For a cloud provider paste its API base URL (e.g. OpenRouter). For a local model, paste your Ollama address. The model list is fetched for you.')}
      </label>
      <input id="ao-llm-url" type="text" placeholder="https://openrouter.ai/api/v1  or  http://localhost:11434" />
    </div>
    <div class="ao-field">
      <label>API key <span class="ao-opt">(leave blank for a local model)</span></label>
      <input id="ao-llm-key" type="password" autocomplete="off" placeholder="sk-..." />
    </div>
    <div class="ao-row">
      <button class="ao-btn ao-btn-ghost" id="ao-llm-load">Load models</button>
      <span id="ao-llm-load-status" class="ao-inline-status"></span>
    </div>
    <div class="ao-field" id="ao-llm-model-wrap" style="display:none">
      <label>Model</label>
      <select id="ao-llm-model"></select>
    </div>
    <div id="ao-llm-msg"></div>
  `);
  _setFoot(`<button class="ao-btn ao-btn-primary" id="ao-llm-save" disabled>Save &amp; continue</button>`);

  let endpointId = null;

  document.getElementById('ao-llm-load').onclick = async () => {
    const url = (document.getElementById('ao-llm-url').value || '').trim();
    const key = document.getElementById('ao-llm-key').value || '';
    const statusEl = document.getElementById('ao-llm-load-status');
    if (!url) { statusEl.textContent = 'Enter a provider address first.'; return; }
    statusEl.textContent = 'Loading models…';
    try {
      const fd = new FormData();
      fd.append('base_url', url);
      fd.append('api_key', key);
      fd.append('name', url);
      fd.append('model_type', 'llm');
      const res = await _postForm(`${SETUP}/model-endpoints`, fd);
      endpointId = res.id || (res.endpoint && res.endpoint.id) || null;
      const models = res.models || (res.endpoint && res.endpoint.models) || [];
      const sel = document.getElementById('ao-llm-model');
      const names = models.map((m) => (typeof m === 'string' ? m : (m.id || m.name))).filter(Boolean);
      if (!names.length) { statusEl.textContent = 'No models found at that address.'; return; }
      sel.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
      document.getElementById('ao-llm-model-wrap').style.display = '';
      document.getElementById('ao-llm-save').disabled = false;
      statusEl.textContent = `Found ${names.length} model${names.length === 1 ? '' : 's'}.`;
    } catch (e) {
      statusEl.textContent = '';
      document.getElementById('ao-llm-msg').innerHTML = _err(esc(e.message || 'Could not load models.'));
    }
  };

  document.getElementById('ao-llm-save').onclick = async () => {
    if (_busy) return;
    const model = document.getElementById('ao-llm-model').value;
    if (!model) return;
    _busy = true;
    document.getElementById('ao-llm-save').disabled = true;
    try {
      if (endpointId) {
        await _post(`${SETUP}/llm/from-endpoint`, { endpoint_id: endpointId, model });
      } else {
        const url = (document.getElementById('ao-llm-url').value || '').trim();
        const key = document.getElementById('ao-llm-key').value || '';
        const provider = /localhost|127\.0\.0\.1|11434/.test(url) ? 'ollama' : 'openai';
        await _post(`${SETUP}/llm`, { provider, base_url: url, api_key: key, model });
      }
      await _advanceAndContinue('llm');
    } catch (e) {
      document.getElementById('ao-llm-msg').innerHTML = _err(esc(e.message || 'Could not save the model.'));
      document.getElementById('ao-llm-save').disabled = false;
    } finally {
      _busy = false;
    }
  };
}

// ── STEP 2: Notification channels (gating) ──────────────────────────────────

async function _renderChannels() {
  let cur = {};
  try { cur = await _fetchJSON(`${SETUP}/channels`); } catch { cur = {}; }
  _setBody(`
    <h2 class="ao-step-title">Notifications ${_tip('Applicant needs at least one way to reach you — Discord and/or email — so it can send your daily digest and ask for approvals. This step is required.')}</h2>
    <p class="ao-step-desc">Add at least one channel so Applicant can send you updates and approval requests.</p>
    <div class="ao-field">
      <label>Discord webhook URL <span class="ao-opt">(optional)</span>
        ${_tip('In your Discord server: Settings → Integrations → Webhooks → New Webhook → Copy URL.')}
      </label>
      <input id="ao-ch-discord" type="text" placeholder="https://discord.com/api/webhooks/..." value="${esc(cur.discord_webhook_url || '')}" />
    </div>
    <div class="ao-field">
      <label>Email / SMTP address <span class="ao-opt">(optional)</span>
        ${_tip('An Apprise-style URL, e.g. mailto://user:pass@gmail.com. You can add several, comma-separated.')}
      </label>
      <input id="ao-ch-email" type="text" placeholder="mailto://user:pass@smtp.example.com" value="${esc(cur.apprise_urls || '')}" />
    </div>
    <div class="ao-row">
      <button class="ao-btn ao-btn-ghost" id="ao-ch-test">Send a test</button>
      <span id="ao-ch-test-status" class="ao-inline-status"></span>
    </div>
    <div id="ao-ch-msg"></div>
  `);
  _setFoot(`<button class="ao-btn ao-btn-primary" id="ao-ch-save">Save &amp; continue</button>`);

  const collect = () => ({
    discord_webhook_url: (document.getElementById('ao-ch-discord').value || '').trim(),
    apprise_urls: (document.getElementById('ao-ch-email').value || '').trim(),
  });

  document.getElementById('ao-ch-test').onclick = async () => {
    const statusEl = document.getElementById('ao-ch-test-status');
    const body = collect();
    if (!body.discord_webhook_url && !body.apprise_urls) {
      statusEl.textContent = 'Add a channel first.'; return;
    }
    statusEl.textContent = 'Saving + sending…';
    try {
      await _post(`${SETUP}/channels`, body);
      const res = await _post(`${SETUP}/channels/test`, {});
      const ch = (res.channels || []).join(', ') || 'your channels';
      statusEl.textContent = `Test sent to ${ch}.`;
    } catch (e) {
      statusEl.textContent = '';
      document.getElementById('ao-ch-msg').innerHTML = _err(esc(e.message || 'Test failed.'));
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

// ── STEP 3: Fonts ───────────────────────────────────────────────────────────

async function _renderFonts() {
  let installed = [];
  try { const f = await _fetchJSON(`${SETUP}/fonts`); installed = f.installed || []; } catch { installed = []; }
  _setBody(`
    <h2 class="ao-step-title">Fonts ${_tip('To make your generated resume look exactly like yours, Applicant may need the fonts your resume uses. Upload a resume to check, then add any missing fonts. This step is optional — you can skip it.')}</h2>
    <p class="ao-step-desc">Optional: check which fonts your resume needs and add any that are missing, so your generated resume keeps its look.</p>
    <div class="ao-field">
      <label>Check a resume for required fonts</label>
      <input id="ao-font-detect" type="file" accept=".docx,.doc,.pdf,.rtf,.txt" />
    </div>
    <div id="ao-font-report"></div>
    <p class="ao-installed">Installed fonts: <span id="ao-font-installed">${installed.length ? esc(installed.join(', ')) : 'none yet'}</span></p>
    <div id="ao-font-msg"></div>
  `);
  _setFoot(`
    <button class="ao-btn ao-btn-ghost" id="ao-font-skip">Skip for now</button>
    <button class="ao-btn ao-btn-primary" id="ao-font-continue">Continue</button>
  `);

  document.getElementById('ao-font-detect').onchange = async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const report = document.getElementById('ao-font-report');
    report.innerHTML = '<p class="ao-inline-status">Checking…</p>';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await _postForm(`${SETUP}/fonts/detect`, fd);
      const missing = res.missing || [];
      if (!missing.length) {
        report.innerHTML = '<p class="ao-ok">All required fonts are already installed.</p>';
        return;
      }
      report.innerHTML = `
        <p class="ao-warn">Missing fonts: ${esc(missing.join(', '))}</p>
        ${missing.map((m) => `
          <div class="ao-field ao-font-install" data-font="${esc(m)}">
            <label>Upload font file for <strong>${esc(m)}</strong></label>
            <input type="file" accept=".ttf,.otf" class="ao-font-file" />
          </div>`).join('')}
      `;
      report.querySelectorAll('.ao-font-install').forEach((wrap) => {
        const name = wrap.getAttribute('data-font');
        wrap.querySelector('.ao-font-file').onchange = async (e2) => {
          const ff = e2.target.files && e2.target.files[0];
          if (!ff) return;
          try {
            const fd2 = new FormData();
            fd2.append('name', name);
            fd2.append('file', ff);
            const ir = await _postForm(`${SETUP}/fonts/install`, fd2);
            document.getElementById('ao-font-installed').textContent = (ir.installed || []).join(', ') || 'none yet';
            wrap.innerHTML = `<p class="ao-ok">Installed ${esc(name)}.</p>`;
          } catch (e3) {
            document.getElementById('ao-font-msg').innerHTML = _err(esc(e3.message || 'Could not install font.'));
          }
        };
      });
    } catch (e) {
      report.innerHTML = _err(esc(e.message || 'Could not check fonts.'));
    }
  };

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

function _fieldHTML(f, value) {
  const v = value == null ? '' : value;
  if (f.type === 'textarea') {
    return `<div class="ao-field"><label>${esc(f.label)}</label><textarea name="${esc(f.name)}" rows="3">${esc(v)}</textarea></div>`;
  }
  if (f.type === 'yesno') {
    return `<div class="ao-field"><label>${esc(f.label)}</label>
      <select name="${esc(f.name)}">
        <option value=""${v === '' ? ' selected' : ''}>—</option>
        <option value="yes"${v === 'yes' ? ' selected' : ''}>Yes</option>
        <option value="no"${v === 'no' ? ' selected' : ''}>No</option>
      </select></div>`;
  }
  if (f.type === 'eeo') {
    const opts = ['decline to self-identify', 'prefer to answer'];
    return `<div class="ao-field"><label>${esc(f.label)}</label>
      <select name="${esc(f.name)}">
        ${opts.map((o) => `<option value="${esc(o)}"${(v || 'decline to self-identify') === o ? ' selected' : ''}>${esc(o)}</option>`).join('')}
      </select>
      <input class="ao-eeo-detail" name="${esc(f.name)}__detail" type="text" placeholder="Your answer (optional)" value="" />
      </div>`;
  }
  return `<div class="ao-field"><label>${esc(f.label)}</label><input type="${esc(f.type)}" name="${esc(f.name)}" value="${esc(v)}" /></div>`;
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
    ${_intakeIndex > 0 ? '<button class="ao-btn ao-btn-ghost" id="ao-intake-back">Back</button>' : ''}
    <button class="ao-btn ao-btn-primary" id="ao-intake-next">Save &amp; continue</button>
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

function _renderBaseResume(saved) {
  const total = INTAKE_SECTIONS.length;
  _setBody(`
    <div class="ao-intake-progress">Profile step ${_intakeIndex + 1} of ${total}</div>
    <h2 class="ao-step-title">Upload your resume ${_tip('Applicant reads your resume to fill in your profile and to match its style. After upload we build a high-fidelity version and show you a preview to accept or reject.')}</h2>
    <p class="ao-step-desc">Upload your current resume. We’ll read it to fill in your profile, then show you a polished version to approve.</p>
    <div class="ao-field">
      <input id="ao-resume-file" type="file" accept=".docx,.doc,.pdf,.rtf,.txt,.md" />
    </div>
    <div id="ao-resume-status">${saved && saved.document_path ? '<p class="ao-ok">A resume is already on file. Re-upload to replace it.</p>' : ''}</div>
    <div id="ao-conflicts"></div>
    <div id="ao-preview"></div>
    <div id="ao-resume-msg"></div>
  `);
  _setFoot(`
    <button class="ao-btn ao-btn-ghost" id="ao-intake-back">Back</button>
    <button class="ao-btn ao-btn-primary" id="ao-resume-next" ${saved && saved.document_path ? '' : 'disabled'}>Continue</button>
  `);

  document.getElementById('ao-intake-back').onclick = () => {
    _intakeIndex = Math.max(0, _intakeIndex - 1); _renderIntakeSection();
  };

  document.getElementById('ao-resume-file').onchange = async (ev) => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const st = document.getElementById('ao-resume-status');
    st.innerHTML = '<p class="ao-inline-status">Reading your resume…</p>';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await _postForm(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/base-resume`, fd);
      st.innerHTML = `<p class="ao-ok">Read ${res.attribute_count || 0} details from your resume.</p>`;
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
  };

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
    <div class="ao-conflict-box">
      <p class="ao-warn">A few details from your resume differ from what you told us. Pick which to keep:</p>
      ${conflicts.map((c, i) => `
        <div class="ao-conflict" data-attr="${esc(c.attribute)}" data-i="${i}">
          <strong>${esc(c.attribute)}</strong>
          <label><input type="radio" name="ao-conf-${i}" value="interview" checked> Keep: ${esc(c.interview_value)}</label>
          <label><input type="radio" name="ao-conf-${i}" value="parsed"> Use resume: ${esc(c.parsed_value)}</label>
        </div>`).join('')}
      <button class="ao-btn ao-btn-ghost" id="ao-conf-apply">Apply choices</button>
    </div>`;
  document.getElementById('ao-conf-apply').onclick = async () => {
    try {
      for (const c of conflicts) {
        const i = wrap.querySelector(`.ao-conflict[data-attr="${CSS.escape(c.attribute)}"]`).getAttribute('data-i');
        const choice = wrap.querySelector(`input[name="ao-conf-${i}"]:checked`).value;
        const value = choice === 'parsed' ? c.parsed_value : c.interview_value;
        await _post(`${SETUP}/onboarding/${encodeURIComponent(_campaignId)}/confirm-conflict`, {
          attribute: c.attribute, value,
        });
      }
      wrap.innerHTML = '<p class="ao-ok">Choices applied.</p>';
    } catch (e) {
      _toast(e.message || 'Could not apply choices.');
    }
  };
}

async function _buildPreview() {
  const wrap = document.getElementById('ao-preview');
  wrap.innerHTML = '<p class="ao-inline-status">Building a polished version…</p>';
  try {
    const p = await _post(`${SETUP}/conversion/${encodeURIComponent(_campaignId)}/preview`, {});
    const note = p.fidelity_ok ? 'Looks like a faithful match.' : 'Some formatting may differ.';
    wrap.innerHTML = `
      <div class="ao-preview-box">
        <p>We built a high-fidelity version of your resume (${esc(String(p.page_count || '?'))} page(s)). ${esc(note)}</p>
        ${(p.notes && p.notes.length) ? `<ul>${p.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
        <div class="ao-row">
          <button class="ao-btn ao-btn-primary" id="ao-prev-accept">Use this version</button>
          <button class="ao-btn ao-btn-ghost" id="ao-prev-reject">Keep my original</button>
          <span id="ao-prev-status" class="ao-inline-status"></span>
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
    wrap.innerHTML = `<p class="ao-inline-status">Preview unavailable: ${esc(e.message || '')}</p>`;
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
  _setBody('<div class="ao-done"><h2>You’re all set!</h2><p>Applicant is ready to start working for you.</p></div>');
  _setFoot('<button class="ao-btn ao-btn-primary" id="ao-finish">Get started</button>');
  document.getElementById('ao-finish').onclick = _dismiss;
  _renderRail();
}

function _dismiss() {
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

export async function maybeLaunchOnboarding() {
  if (_overlay) return; // already open
  let status;
  try { status = await _refreshStatus(); }
  catch { return; } // engine unreachable -> don't block; the user can still log in
  if (!status) return;
  const complete = status.llm_configured && status.channels_configured && status.onboarding_complete;
  if (complete) return; // nothing to do

  _overlay = _buildOverlay();
  document.body.appendChild(_overlay);
  _stepIndex = _firstIncompleteStep();
  // Pre-create the campaign once the LLM gate is open so onboarding resumes cleanly.
  if (status.llm_configured) { try { await _ensureCampaign(); } catch { /* later */ } }
  await _renderStep();
}

export default { maybeLaunchOnboarding };
