// static/js/applicantModelLadder.js
//
// The model escalation ladder editor (FR-LLM-3) — Settings → Set up Applicant.
// ADDITIVE and self-contained: it talks only to the engine setup proxy
// (/api/applicant/setup/llm/tiers) and renders into the AI settings panel's
// host (#ao-settings-model-ladder). No native surface is touched.
//
// The ladder is an ORDERED list of model tiers (Level 1 → N). Work starts at
// Level 1 and climbs when a task needs more capability (low confidence, context
// overflow, or a heavy task like resume/cover-letter writing). Each tier can use
// any provider — a local model or a cloud API. Position = level; reorder, add and
// remove are all supported (1–5 tiers).
//
// Key preservation: GET returns a non-secret `api_key_ref` marker (never the key)
// for tiers that already have one saved. We keep that marker and, on save, send it
// back with a blank api_key so the engine re-seals the existing key — so editing a
// model or reordering never wipes a saved key.

import uiModule from './ui.js';
import { esc, _toast, _fetchJSON, _put } from './applicantCore.js';

const SETUP = '/api/applicant/setup';
const MAX_TIERS = 5;

// Provider options the engine accepts. Cloud providers are OpenAI-compatible from
// the engine's perspective; "Local" is the Ollama-compatible path.
const PROVIDERS = [
  ['openrouter', 'OpenRouter (cloud)'],
  ['openai', 'OpenAI-compatible (cloud)'],
  ['anthropic', 'Anthropic (cloud)'],
  ['ollama', 'Local model (Ollama-compatible)'],
];

let _host = null;
let _tiers = [];





function _blankTier() {
  return {
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
    model: '',
    api_key: '',
    api_key_ref: '',
    context_window: 128000,
    _hasKey: false,
  };
}

async function _load() {
  let data = {};
  try { data = await _fetchJSON(`${SETUP}/llm/tiers`); } catch { data = { tiers: [], engine_available: false }; }
  const tiers = (data.tiers || []).map((t) => ({
    provider: t.provider || 'openrouter',
    base_url: t.base_url || '',
    model: t.model || '',
    api_key: '', // never populated from the server (secret omitted)
    api_key_ref: t.api_key_ref || '',
    context_window: t.context_window != null ? t.context_window : 8192,
    _hasKey: !!(t.api_key_ref || t.api_key),
  }));
  _tiers = tiers.length ? tiers : [_blankTier()];
  _render(data.engine_available === false);
}

// Read the live input values back into _tiers so reorder/add/remove never lose edits.
function _syncFromDOM() {
  if (!_host) return;
  _host.querySelectorAll('[data-tier-row]').forEach((row) => {
    const i = parseInt(row.getAttribute('data-tier-row'), 10);
    if (isNaN(i) || !_tiers[i]) return;
    const get = (sel) => { const el = row.querySelector(sel); return el ? el.value : ''; };
    _tiers[i].provider = get('.ml-provider');
    _tiers[i].base_url = get('.ml-base').trim();
    _tiers[i].model = get('.ml-model').trim();
    _tiers[i].context_window = parseInt(get('.ml-ctx'), 10) || 8192;
    const key = get('.ml-key');
    if (key) { _tiers[i].api_key = key; }
  });
}

function _tierRowHTML(t, i) {
  const last = _tiers.length - 1;
  const providerOpts = PROVIDERS.map(
    ([v, label]) => `<option value="${v}"${t.provider === v ? ' selected' : ''}>${esc(label)}</option>`,
  ).join('');
  const keyNote = t._hasKey
    ? '<span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:2px;">A key is saved — leave blank to keep it.</span>'
    : '';
  return `
    <div class="admin-card og-card" data-tier-row="${i}" style="margin-bottom:10px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">
        <div style="font-weight:600;">Level ${i + 1}${i === 0 ? ' · entry model' : ''}</div>
        <div style="display:flex;gap:4px;">
          <button class="cal-btn ml-up" title="Move up" aria-label="Move up" ${i === 0 ? 'disabled' : ''}>↑</button>
          <button class="cal-btn ml-down" title="Move down" aria-label="Move down" ${i === last ? 'disabled' : ''}>↓</button>
          <button class="cal-btn ml-del" title="Remove this tier" aria-label="Remove tier" ${_tiers.length <= 1 ? 'disabled' : ''}>✕</button>
        </div>
      </div>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Provider
        <select class="settings-select ml-provider" style="display:block;margin-top:3px;min-width:240px;">${providerOpts}</select>
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Endpoint URL
        <input type="text" class="settings-select ml-base" value="${esc(t.base_url)}" placeholder="https://openrouter.ai/api/v1 (blank for a local default)" style="display:block;margin-top:3px;width:100%;max-width:420px;" />
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Model
        <input type="text" class="settings-select ml-model" value="${esc(t.model)}" placeholder="e.g. deepseek/deepseek-v4-flash" style="display:block;margin-top:3px;width:100%;max-width:420px;" />
      </label>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">API key
          <input type="password" class="settings-select ml-key" value="" placeholder="${t._hasKey ? '•••••••• (saved)' : 'cloud key (local models need none)'}" autocomplete="off" style="display:block;margin-top:3px;width:240px;" />
          ${keyNote}
        </label>
        <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Context window
          <input type="number" class="settings-select ml-ctx" min="1024" value="${esc(t.context_window)}" style="display:block;margin-top:3px;width:140px;" />
        </label>
      </div>
    </div>`;
}

function _render(offline) {
  if (!_host) return;
  if (offline) {
    _host.innerHTML = '<p class="admin-toggle-sub" style="opacity:0.7;">The application engine is offline — open this again once it is reachable to edit the model ladder.</p>';
    return;
  }
  _host.innerHTML = `
    <div class="admin-toggle-sub" style="opacity:0.8;margin-bottom:10px;">
      Applicant starts at <strong>Level 1</strong> and climbs to a higher level only when a task needs more capability —
      low confidence, a prompt too long for the current model, or a heavy task like writing a resume or cover letter.
      Put your cheapest capable model first and your strongest last.
    </div>
    <div id="ml-rows">${_tiers.map((t, i) => _tierRowHTML(t, i)).join('')}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;">
      <button class="cal-btn" id="ml-add" ${_tiers.length >= MAX_TIERS ? 'disabled' : ''}>+ Add a level</button>
      <button class="cal-btn cal-btn-primary" id="ml-save">Save ladder</button>
    </div>
    <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:8px;">Up to ${MAX_TIERS} levels. Each level needs a provider and a model.</span>`;

  _host.querySelectorAll('.ml-up').forEach((b, idx) => b.addEventListener('click', () => _move(_rowIndex(b), -1)));
  _host.querySelectorAll('.ml-down').forEach((b) => b.addEventListener('click', () => _move(_rowIndex(b), 1)));
  _host.querySelectorAll('.ml-del').forEach((b) => b.addEventListener('click', () => _remove(_rowIndex(b))));
  const addBtn = _host.querySelector('#ml-add');
  if (addBtn) addBtn.addEventListener('click', () => { _syncFromDOM(); if (_tiers.length < MAX_TIERS) { _tiers.push(_blankTier()); _render(false); } });
  const saveBtn = _host.querySelector('#ml-save');
  if (saveBtn) saveBtn.addEventListener('click', _save);
}

function _rowIndex(btn) {
  const row = btn.closest('[data-tier-row]');
  return row ? parseInt(row.getAttribute('data-tier-row'), 10) : -1;
}

function _move(i, delta) {
  _syncFromDOM();
  const j = i + delta;
  if (i < 0 || j < 0 || j >= _tiers.length) return;
  const tmp = _tiers[i]; _tiers[i] = _tiers[j]; _tiers[j] = tmp;
  _render(false);
}

function _remove(i) {
  _syncFromDOM();
  if (_tiers.length <= 1 || i < 0) return;
  _tiers.splice(i, 1);
  _render(false);
}

async function _save() {
  _syncFromDOM();
  // Validate before sending so the user gets a clear message, not a 400.
  for (let i = 0; i < _tiers.length; i += 1) {
    if (!_tiers[i].provider || !_tiers[i].model) {
      _toast(`Level ${i + 1} needs a provider and a model.`);
      return;
    }
  }
  const payload = {
    tiers: _tiers.map((t) => {
      const tier = {
        provider: t.provider,
        base_url: t.base_url || '',
        model: t.model,
        context_window: t.context_window || 8192,
      };
      if (t.api_key) tier.api_key = t.api_key;          // a newly typed key wins
      else if (t._hasKey && t.api_key_ref) tier.api_key_ref = t.api_key_ref;  // else keep the saved one
      return tier;
    }),
  };
  const saveBtn = _host.querySelector('#ml-save');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
  try {
    await _put(`${SETUP}/llm/tiers`, payload);
    _toast(`Saved a ${_tiers.length}-level model ladder.`);
    await _load(); // re-read so saved-key markers refresh
  } catch (e) {
    _toast(e.message || 'Could not save the model ladder.');
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save ladder'; }
  }
}

export function mountModelLadder(host) {
  if (!host) return false;
  _host = host;
  _tiers = [];
  _host.innerHTML = '<div class="hwfit-loading">Loading…</div>';
  _load().catch(e => {
    console.error('Failed to load model ladder:', e);
    if (_host) _host.innerHTML = '<div class="admin-card"><p class="admin-toggle-sub" style="opacity:0.7;margin:0;">Could not load the model ladder. Reload to try again.</p></div>';
  });
  return true;
}

if (typeof window !== 'undefined') window.mountApplicantModelLadder = mountModelLadder;

export default { mountModelLadder };
