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
//
// Lens-11 settings-audit follow-ups (#9, #33, #55):
//  * #9  — a tier row can PICK from the "Saved model connections" list below
//    instead of re-typing provider/base URL, and gets a "Test this level" button
//    that reuses the same probe-without-saving route the connections list and
//    admin.js's endpoint manager already call (`POST .../model-endpoints/test`).
//    The saved connection's sealed API key is never sent to the browser (same
//    security boundary the connections list already has), so picking a
//    connection fills address + provider + a model picklist, and — only when
//    the connection actually has a saved key — leaves an honest note that the
//    key itself needs a one-time re-entry at this level.
//  * #33 — an "Unsaved changes" badge (mirrors the campaign-settings dirty
//    indicator) appears the moment any tier is edited/added/removed/reordered
//    and clears on a successful Save.
//  * #55 — context_window no longer *silently* defaults to 8192: a missing or
//    unparseable stored value is labeled as a fallback, a recognized model name
//    autofills a real known window (small ported table, same approach as the
//    workspace's own `src/model_context.py` KNOWN_CONTEXT_WINDOWS), and either
//    case is visibly captioned rather than presented as a real number.

import uiModule from './ui.js';
import { esc, _toast, _fetchJSON, _put } from './applicantCore.js';
// lens 01 #51: the shared drag-reorder kit already used by models.js /
// sessions.js / the image editor's layer panel — the ladder previously only
// had the up/down buttons. Reused as-is (see _wireDragReorder below), not
// reimplemented.
import dragSortModule from './dragSort.js';

const SETUP = '/api/applicant/setup';
const MAX_TIERS = 5;

// Plain-language labels for the engine's model-type enum (dark-engine audit
// item 20's saved-connections list below).
const _TYPE_LABEL = {
  llm: 'Chat / writing model',
  embedding: 'Embedding model',
  image: 'Image model',
  rerank: 'Re-ranking model',
  stt: 'Speech-to-text model',
  tts: 'Text-to-speech model',
};

// Provider options the engine accepts. Cloud providers are OpenAI-compatible from
// the engine's perspective; "Local" is the Ollama-compatible path.
const PROVIDERS = [
  ['openrouter', 'OpenRouter (cloud)'],
  ['openai', 'OpenAI-compatible (cloud)'],
  ['anthropic', 'Anthropic (cloud)'],
  ['ollama', 'Local model (Ollama-compatible)'],
];

// Known context windows for common models (lens 11 #55), ported from the
// workspace's own `src/model_context.py` KNOWN_CONTEXT_WINDOWS — same idea
// (substring match on the model id, shortest unique prefix), just re-expressed
// in JS since this module can't import Python. Used only to AUTOFILL a
// reasonable starting value; the field stays editable and this never overrides
// a value the user typed by hand.
const _KNOWN_CONTEXT_WINDOWS = {
  'claude-sonnet-4-5': 200000, 'claude-sonnet-4-6': 200000, 'claude-sonnet-4': 200000,
  'claude-opus-4': 200000, 'claude-haiku-4': 200000, 'claude-haiku-3-5': 200000,
  'claude-3-5-sonnet': 200000, 'claude-3-5-haiku': 200000, 'claude-3-opus': 200000,
  'claude-3-sonnet': 200000, 'claude-3-haiku': 200000,
  'gpt-5': 400000, 'gpt-4.1': 1047576, 'gpt-4o': 128000, 'gpt-4o-mini': 128000,
  'gpt-4-turbo': 128000, 'gpt-4': 8192, 'gpt-3.5-turbo': 16385,
  'o1-mini': 128000, 'o1': 200000, 'o3-mini': 200000, 'o3': 200000, 'o4-mini': 200000,
  'deepseek-chat': 64000, 'deepseek-coder': 64000, 'deepseek-r1': 64000, 'deepseek-v3': 64000,
  'gemini-2.5-pro': 1048576, 'gemini-2.5-flash': 1048576, 'gemini-1.5-pro': 1048576,
  'gemini-1.5-flash': 1048576, 'gemma-3': 128000, 'gemma-2': 8192,
  'mistral-large': 128000, 'mistral-small': 32000, 'mixtral': 32000, 'codestral': 32000,
  'grok-4': 131072, 'grok-3': 131072,
  'llama-3.3': 131072, 'llama-3.2': 131072, 'llama-3.1': 131072, 'llama-3': 131072,
  'qwen3': 131072, 'qwen2.5': 131072, 'qwen2': 32768,
  'command-r-plus': 128000, 'command-r': 128000,
  'phi-4': 16000, 'phi-3': 128000,
};

/** Substring-match a model id against the known-context table. Returns a
 * window in tokens, or null when nothing matches (caller decides the fallback). */
function _lookupKnownContext(model) {
  const name = (model || '').trim().toLowerCase();
  if (!name) return null;
  const basename = (name.includes('/') ? name.split('/').pop() : name).split(':')[0];
  for (const key of Object.keys(_KNOWN_CONTEXT_WINDOWS)) {
    if (basename.includes(key) || name.includes(key)) return _KNOWN_CONTEXT_WINDOWS[key];
  }
  return null;
}

/** Best-effort provider guess for a saved connection (lens 11 #9): the saved
 * connections list only carries `base_url` + `category` (local/api), not the
 * ladder's provider enum, so infer the closest match rather than forcing a
 * re-pick. Always editable afterward. */
function _guessProvider(baseUrl, category) {
  const u = (baseUrl || '').toLowerCase();
  if (u.includes('openrouter')) return 'openrouter';
  if (u.includes('anthropic')) return 'anthropic';
  if (category === 'local' || u.includes('ollama') || u.includes('11434')) return 'ollama';
  return 'openai';
}

let _host = null;
let _tiers = [];
// Live smart-routing status from the engine (dark-engine audit item 74): which
// endpoint is actually being called and why, straight from the router the LLM
// adapter itself uses — never fabricated/guessed here.
let _routing = null;
// Saved model-endpoint records the engine's registry accumulates (dark-engine
// audit item 20) — a separate store from the tiers above, read here so stale
// or mistyped ones can be disabled/removed instead of piling up forever, AND
// (lens 11 #9) so a tier can pick one instead of re-typing it.
let _endpoints = [];
// Dirty flag (lens 11 #33): true once any tier field/add/remove/reorder has
// happened since the last successful load or save.
let _dirty = false;




function _markDirty() {
  _dirty = true;
  const badge = _host && _host.querySelector('#ml-dirty-badge');
  if (badge) badge.style.display = '';
}

function _blankTier() {
  return {
    provider: 'openrouter',
    base_url: 'https://openrouter.ai/api/v1',
    model: '',
    api_key: '',
    api_key_ref: '',
    context_window: 128000,
    // DISC-4: when set, this tier is bound to a saved connection's key BY
    // REFERENCE — the engine resolves that connection's sealed key server-side
    // at use time, so no key is ever re-typed or sent to the browser.
    connection_id: '',
    _hasKey: false,
    _connectionId: '',
    _connectionModels: [],
    _connectionHasKey: false,
    _ctxKnown: false,
    _ctxFallback: false,
    _ctxManual: false,
  };
}

async function _load() {
  let data = {};
  try { data = await _fetchJSON(`${SETUP}/llm/tiers`); } catch { data = { tiers: [], engine_available: false }; }
  const tiers = (data.tiers || []).map((t) => {
    // lens 11 #55: only treat a genuinely missing/unparseable stored value as
    // the fallback case — a real (even unusual) stored number is the user's
    // own value and is never relabeled as a guess.
    const parsed = parseInt(t.context_window, 10);
    const isFallback = !(Number.isFinite(parsed) && parsed > 0);
    // DISC-4: a tier persisted with a by-reference connection binding comes back
    // carrying `connection_id` (never a key). Keep it so the picker shows the
    // bound connection selected and Save re-sends the same reference.
    const connectionId = t.connection_id || '';
    return {
      provider: t.provider || 'openrouter',
      base_url: t.base_url || '',
      model: t.model || '',
      api_key: '', // never populated from the server (secret omitted)
      api_key_ref: t.api_key_ref || '',
      context_window: isFallback ? 8192 : parsed,
      connection_id: connectionId,
      // `_hasKey` is this tier's OWN sealed key (leave-blank-to-keep). A
      // connection binding is tracked separately (`_connectionHasKey`) so the
      // two are never conflated in the notes or the remove-confirm.
      _hasKey: !!(t.api_key_ref || t.api_key),
      _connectionId: connectionId,
      _connectionModels: [],
      _connectionHasKey: false,
      _ctxKnown: false,
      _ctxFallback: isFallback,
      _ctxManual: !isFallback,
    };
  });
  _tiers = tiers.length ? tiers : [_blankTier()];
  _routing = data.routing || null;
  try {
    const eps = await _fetchJSON(`${SETUP}/model-endpoints`);
    _endpoints = Array.isArray(eps) ? eps : [];
  } catch {
    _endpoints = [];
  }
  // DISC-4: reconcile each tier's by-ref binding against the freshly loaded
  // connections so the row can honestly say whether the bound connection still
  // exists and still carries a sealed key (its key is never sent here).
  _tiers.forEach((t) => {
    if (!t.connection_id) return;
    const ep = _endpoints.find((e) => String(e.id) === String(t.connection_id));
    if (ep) {
      t._connectionHasKey = !!ep.has_key;
      if (Array.isArray(ep.models)) t._connectionModels = ep.models;
    } else {
      // The bound connection was removed — drop the stale binding so the row
      // falls back to manual entry rather than pointing at nothing.
      t.connection_id = '';
      t._connectionId = '';
      t._connectionHasKey = false;
    }
  });
  _dirty = false;
  _render(data.engine_available === false);
}

// Saved model connections list (dark-engine audit item 20): the engine's own
// endpoint registry, separate from the ordered tier ladder above. Nothing in
// the front door could previously edit or remove a saved entry once added —
// this renders it read/enable-disable/remove, reusing the same admin-card +
// cal-btn design system as the rest of Settings.
function _savedEndpointsHTML() {
  if (!_endpoints.length) return '';
  const rows = _endpoints.map((ep) => {
    const id = esc(ep.id || '');
    const name = esc(ep.name || ep.base_url || 'Untitled connection');
    const typeLabel = esc(_TYPE_LABEL[ep.model_type] || ep.model_type || 'Model');
    const enabled = ep.is_enabled !== false;
    const online = ep.online !== false;
    const statusBits = [typeLabel, online ? 'online' : 'offline', enabled ? '' : 'disabled']
      .filter(Boolean).join(' · ');
    return `
      <div class="admin-card og-card" data-ep-row="${id}" style="margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
        <div style="min-width:0;">
          <div style="font-weight:600;">${name}</div>
          <div class="admin-toggle-sub" style="opacity:0.7;">${statusBits}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;">
          <button type="button" class="cal-btn ml-ep-toggle" data-ep-id="${id}"
            title="${enabled ? 'Stop this connection from being used, without deleting it' : 'Make this connection available again'}">${enabled ? 'Disable' : 'Enable'}</button>
          <button type="button" class="cal-btn ml-ep-remove" data-ep-id="${id}" data-ep-name="${name}"
            title="Permanently delete this connection">Remove</button>
        </div>
      </div>`;
  }).join('');
  return `
    <div style="margin-top:16px;">
      <div style="font-weight:600;margin-bottom:6px;">Saved model connections</div>
      <div class="admin-toggle-sub" style="opacity:0.75;margin-bottom:8px;">
        Other model connections I've found or been given, separate from the levels above. Disable or remove ones you no longer use.
        Pick one into a level above with that level's "Pick a saved connection" menu instead of retyping it.
      </div>
      ${rows}
    </div>`;
}

function _wireSavedEndpoints() {
  if (!_host) return;
  _host.querySelectorAll('.ml-ep-toggle').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.epId;
      btn.disabled = true;
      try {
        await _fetchJSON(`${SETUP}/model-endpoints/${encodeURIComponent(id)}`, { method: 'PATCH' });
        await _load();
      } catch (e) {
        _toast(e.message || 'Could not update that connection.');
        btn.disabled = false;
      }
    });
  });
  _host.querySelectorAll('.ml-ep-remove').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.epId;
      const name = btn.dataset.epName || 'this connection';
      const ok = await uiModule.styledConfirm(`Remove ${name}?`, { confirmText: 'Remove', danger: true });
      if (!ok) return;
      btn.disabled = true;
      try {
        await _fetchJSON(`${SETUP}/model-endpoints/${encodeURIComponent(id)}`, { method: 'DELETE' });
        _toast('Connection removed.');
        await _load();
      } catch (e) {
        _toast(e.message || 'Could not remove that connection.');
        btn.disabled = false;
      }
    });
  });
}

// Renders the live routing status row: which endpoint is actually being used
// right now, and why (health-based reorder / local preference), sourced only
// from the engine's real router state (`data.routing`, never guessed here).
function _routingStatusHTML() {
  const r = _routing;
  if (!r) return '';
  if (!r.enabled) {
    return '<div class="admin-toggle-sub" style="opacity:0.7;margin-bottom:10px;">Smart routing is off — requests always start at Level 1, in the order above.</div>';
  }
  const active = r.active_endpoint;
  const health = r.health || {};
  let line;
  if (active && active.name) {
    line = r.reordered
      ? `Right now, requests are actually going to <strong>${esc(active.name)}</strong> — ahead of Level 1 because ${r.prefer_local ? 'a local model is online and preferred' : 'it is the best available match right now'}.`
      : `Right now, requests are going to <strong>${esc(active.name)}</strong> — the configured Level 1.`;
  } else {
    line = 'No online endpoint reported yet — requests fall back to the level order above.';
  }
  const healthBits = [];
  if (typeof health.endpoints_online === 'number') {
    healthBits.push(`${health.endpoints_online}/${health.endpoints_total || 0} endpoints online`);
  }
  if (health.has_local_fallback) healthBits.push('a local fallback is available');
  const healthLine = healthBits.length
    ? ` <span style="opacity:0.6;">(${esc(healthBits.join(' · '))})</span>`
    : '';
  return `
    <div class="admin-card og-card" id="ml-routing-status" style="margin-bottom:10px;">
      <div style="font-weight:600;margin-bottom:4px;">Smart routing
        <span class="admin-toggle-sub" style="font-weight:400;opacity:0.7;"> — ${r.prefer_local ? 'prefers a local model when one is online' : 'balances cost against capability'}</span>
      </div>
      <div class="admin-toggle-sub">${line}${healthLine}</div>
    </div>`;
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
    const ctxParsed = parseInt(get('.ml-ctx'), 10);
    if (Number.isFinite(ctxParsed) && ctxParsed > 0) {
      _tiers[i].context_window = ctxParsed;
    } else {
      // lens 11 #55: still fall back to a usable default, but mark it as one
      // rather than pretending it's a value the user actually confirmed.
      _tiers[i].context_window = 8192;
      _tiers[i]._ctxFallback = true;
      _tiers[i]._ctxKnown = false;
    }
    // lens 01 #11: an untrimmed API key (a stray leading/trailing space from a
    // paste) is a silent auth failure later — the key looks right everywhere
    // it's displayed (never echoed back) but the engine call fails. Trim it
    // the same way base_url/model already are above.
    const key = get('.ml-key').trim();
    if (key) { _tiers[i].api_key = key; }
    // DISC-4: keep the persisted by-ref binding (`connection_id`) in lock-step
    // with the picker's current selection — "— enter manually —" (value "")
    // clears it so the tier falls back to a typed/own key.
    const connSel = row.querySelector('.ml-connection');
    if (connSel) {
      _tiers[i]._connectionId = connSel.value;
      _tiers[i].connection_id = connSel.value;
    }
  });
}

// lens 11 #55: the note under the context-window field — always says whether
// the number shown is a real stored value, an autofill guess, or an
// unlabeled-until-now silent fallback.
function _ctxNoteText(t) {
  if (t._ctxFallback) {
    return "I don't know this model's real context window — using a safe fallback (8192) until you set the real number.";
  }
  if (t._ctxKnown) {
    return `Filled in automatically for "${esc(t.model)}" — change it if you know a different number.`;
  }
  return '';
}

function _connectionPickerHTML(t, i) {
  if (!_endpoints.length) return '';
  const opts = _endpoints.map((ep) => {
    const id = esc(String(ep.id != null ? ep.id : ''));
    const label = esc(ep.name || ep.base_url || 'Untitled connection');
    const offline = ep.online === false ? ' (offline)' : '';
    const selected = t._connectionId && String(t._connectionId) === id ? ' selected' : '';
    return `<option value="${id}"${selected}>${label}${offline}</option>`;
  }).join('');
  return `
    <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Pick a saved connection
      <span style="opacity:0.6;font-weight:normal">(optional — fills in the address and model below)</span>
      <select class="settings-select ml-connection" data-tier-idx="${i}" style="display:block;margin-top:3px;min-width:240px;">
        <option value="">— enter manually —</option>
        ${opts}
      </select>
    </label>`;
}

function _tierRowHTML(t, i) {
  const last = _tiers.length - 1;
  const providerOpts = PROVIDERS.map(
    ([v, label]) => `<option value="${v}"${t.provider === v ? ' selected' : ''}>${esc(label)}</option>`,
  ).join('');
  // DISC-4: a tier bound to a saved connection that HAS a key reuses that key
  // by reference — no re-entry. The key stays sealed server-side (it is never
  // sent to the browser), and typing here only overrides it at this level.
  const boundWithKey = !!(t.connection_id && t._connectionHasKey);
  let keyNote = '';
  if (boundWithKey) {
    keyNote = '<span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:2px;">Using the saved key from this connection — it stays sealed and is applied by reference, so there\'s no need to re-enter it here. Type a key only to override it at this level.</span>';
  } else if (t._hasKey) {
    keyNote = '<span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:2px;">A key is saved — leave blank to keep it.</span>';
  }
  const modelListId = `ml-models-${i}`;
  const modelList = (t._connectionModels || [])
    .map((m) => `<option value="${esc(m)}"></option>`).join('');
  const ctxNote = _ctxNoteText(t);
  return `
    <div class="admin-card og-card" data-tier-row="${i}" style="margin-bottom:10px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          <span class="ml-drag-handle" aria-hidden="true" title="Drag to reorder" style="cursor:grab;opacity:0.5;padding:2px;user-select:none;">⠿</span>
          <div style="font-weight:600;">Level ${i + 1}${i === 0 ? ' · entry model' : ''}</div>
        </div>
        <div style="display:flex;gap:4px;">
          <button class="cal-btn ml-up" title="Move up" aria-label="Move up" ${i === 0 ? 'disabled' : ''}>↑</button>
          <button class="cal-btn ml-down" title="Move down" aria-label="Move down" ${i === last ? 'disabled' : ''}>↓</button>
          <button class="cal-btn ml-del" title="Remove this level" aria-label="Remove this level" ${_tiers.length <= 1 ? 'disabled' : ''}>✕</button>
        </div>
      </div>
      ${_connectionPickerHTML(t, i)}
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Provider
        <select class="settings-select ml-provider" style="display:block;margin-top:3px;min-width:240px;">${providerOpts}</select>
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Server address
        <input type="text" class="settings-select ml-base" value="${esc(t.base_url)}" placeholder="https://openrouter.ai/api/v1 (blank for a local default)" style="display:block;margin-top:3px;width:100%;max-width:420px;" />
      </label>
      <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">Model
        <input type="text" class="settings-select ml-model" list="${modelListId}" value="${esc(t.model)}" placeholder="e.g. deepseek/deepseek-v4-flash" style="display:block;margin-top:3px;width:100%;max-width:420px;" />
        <datalist id="${modelListId}">${modelList}</datalist>
      </label>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;">API key
          <span style="display:flex;gap:6px;align-items:center;margin-top:3px;">
            <input type="password" class="settings-select ml-key" value="" placeholder="${boundWithKey ? "•••••••• (using this connection's saved key)" : (t._hasKey ? '•••••••• (saved)' : 'cloud key (local models need none)')}" autocomplete="off" style="display:block;width:240px;" />
            <button type="button" class="ml-key-toggle cal-btn" aria-pressed="false"
              title="Show/hide this level's API key as you type" style="flex-shrink:0;padding:2px 8px;font-size:11px;">Show</button>
          </span>
          ${keyNote}
        </label>
        <label class="admin-toggle-sub" style="display:block;margin-bottom:6px;" title="How much text (roughly, words and pieces of words) this model can read at once. Check the model's own listing if you're unsure — I trim older context to fit, so an accurate number just avoids wasted capacity.">Context window
          <input type="number" class="settings-select ml-ctx" min="1024" value="${esc(t.context_window)}" style="display:block;margin-top:3px;width:140px;" />
          ${ctxNote ? `<span class="admin-toggle-sub ml-ctx-note" style="opacity:0.6;display:block;margin-top:2px;max-width:320px;">${ctxNote}</span>` : `<span class="admin-toggle-sub ml-ctx-note" style="display:block;margin-top:2px;"></span>`}
        </label>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:4px;flex-wrap:wrap;">
        <button type="button" class="cal-btn ml-test">Test this level</button>
        <span class="admin-toggle-sub ml-test-msg" style="opacity:0.8;"></span>
      </div>
    </div>`;
}

function _render(offline) {
  if (!_host) return;
  if (offline) {
    _host.innerHTML = `<p class="admin-toggle-sub" style="opacity:0.7;">I can't reach my back end right now — open this again in a moment to edit your model levels.</p>`;
    return;
  }
  _host.innerHTML = `
    <div class="admin-toggle-sub" style="opacity:0.8;margin-bottom:10px;">
      I start at <strong>Level 1</strong> and climb to a higher level only when a task needs more capability —
      low confidence, a prompt too long for the current model, or a heavy task like writing a resume or cover letter.
      Put your cheapest capable model first and your strongest last.
    </div>
    ${_routingStatusHTML()}
    <div id="ml-rows">${_tiers.map((t, i) => _tierRowHTML(t, i)).join('')}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;align-items:center;">
      <button class="cal-btn" id="ml-add" ${_tiers.length >= MAX_TIERS ? 'disabled' : ''}>+ Add a level</button>
      <button class="cal-btn cal-btn-primary" id="ml-save">Save levels</button>
      <span class="memory-badge" id="ml-dirty-badge" style="font-size:0.7rem;${_dirty ? '' : 'display:none;'}" role="status">Unsaved changes</span>
    </div>
    <span class="admin-toggle-sub" style="opacity:0.6;display:block;margin-top:8px;">Up to ${MAX_TIERS} levels. Each level needs a provider and a model.</span>
    ${_savedEndpointsHTML()}`;

  _host.querySelectorAll('.ml-up').forEach((b) => b.addEventListener('click', () => _move(_rowIndex(b), -1)));
  _host.querySelectorAll('.ml-down').forEach((b) => b.addEventListener('click', () => _move(_rowIndex(b), 1)));
  _host.querySelectorAll('.ml-del').forEach((b) => b.addEventListener('click', async () => {
    // lens 01 #13: _remove() is now async (it may await a confirm dialog) —
    // disable the clicked button for the duration so a second click during
    // that confirm can't double-fire. If the row survives (cancelled), put it
    // back; if it was removed, _render() already replaced this button.
    if (b.disabled) return;
    const i = _rowIndex(b);
    b.disabled = true;
    try {
      await _remove(i);
    } finally {
      b.disabled = false;
    }
  }));
  const addBtn = _host.querySelector('#ml-add');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      _syncFromDOM();
      if (_tiers.length < MAX_TIERS) {
        _tiers.push(_blankTier());
        _markDirty();
        _render(false);
      }
    });
  }
  const saveBtn = _host.querySelector('#ml-save');
  if (saveBtn) saveBtn.addEventListener('click', _save);
  _wireSavedEndpoints();
  _wireTierEditing();
  _wireKeyToggles();
  _wireDragReorder();
}

// lens 11 #9 / #33 / #55 — per-row wiring for the connection picker, the
// dirty-tracking listeners, the context-window autofill, and the Test button.
function _wireTierEditing() {
  if (!_host) return;
  _host.querySelectorAll('[data-tier-row]').forEach((row) => {
    const i = parseInt(row.getAttribute('data-tier-row'), 10);
    if (isNaN(i) || !_tiers[i]) return;

    // Plain edits (provider / address / key) just mark the ladder dirty.
    ['.ml-provider'].forEach((sel) => {
      const el = row.querySelector(sel);
      if (el) el.addEventListener('change', _markDirty);
    });
    ['.ml-base', '.ml-key'].forEach((sel) => {
      const el = row.querySelector(sel);
      if (el) el.addEventListener('input', _markDirty);
    });

    // Model field: dirty + context-window autofill from the known-model table
    // (lens 11 #55). Never overrides a value the user set by hand.
    const modelEl = row.querySelector('.ml-model');
    if (modelEl) {
      modelEl.addEventListener('input', () => {
        _markDirty();
        const t = _tiers[i];
        if (!t) return;
        t.model = modelEl.value.trim();
        if (t._ctxManual) return; // the user already set this level's context by hand
        const known = _lookupKnownContext(t.model);
        const ctxEl = row.querySelector('.ml-ctx');
        const noteEl = row.querySelector('.ml-ctx-note');
        if (known) {
          t.context_window = known;
          t._ctxKnown = true;
          t._ctxFallback = false;
          if (ctxEl) ctxEl.value = String(known);
        } else {
          t._ctxKnown = false;
        }
        if (noteEl) noteEl.textContent = _ctxNoteText(t);
      });
    }

    // Context field: a direct edit means the value is the user's own from now
    // on — stop relabeling it as known/fallback and stop autofilling over it.
    const ctxEl = row.querySelector('.ml-ctx');
    if (ctxEl) {
      ctxEl.addEventListener('input', () => {
        _markDirty();
        const t = _tiers[i];
        if (!t) return;
        t._ctxManual = true;
        t._ctxKnown = false;
        t._ctxFallback = false;
        const noteEl = row.querySelector('.ml-ctx-note');
        if (noteEl) noteEl.textContent = '';
      });
    }

    // Saved-connection picker (lens 11 #9): fills provider/address/model
    // picklist from the chosen connection instead of forcing re-entry.
    // DISC-4: it ALSO binds the tier to that connection's key BY REFERENCE
    // (`connection_id`), so a connection with a saved key is reused with no
    // re-entry — the engine resolves the sealed key server-side at use time and
    // the plaintext is never sent to the browser.
    const connEl = row.querySelector('.ml-connection');
    if (connEl) {
      connEl.addEventListener('change', () => {
        _syncFromDOM();
        const epId = connEl.value;
        const t = _tiers[i];
        if (!t) return;
        t._connectionId = epId;
        t.connection_id = epId; // persisted by-ref binding (cleared when epId is "")
        if (epId) {
          const ep = _endpoints.find((e) => String(e.id) === epId);
          if (ep) {
            t.provider = _guessProvider(ep.base_url, ep.category);
            t.base_url = ep.base_url || '';
            t._connectionModels = Array.isArray(ep.models) ? ep.models : [];
            t._connectionHasKey = !!ep.has_key;
            if (!t.model && t._connectionModels.length) t.model = t._connectionModels[0];
          }
        } else {
          // Back to manual entry — drop the binding and its key marker.
          t._connectionHasKey = false;
        }
        _markDirty();
        _render(false);
      });
    }

    // Test this level (lens 11 #9): reuses the exact probe-without-saving
    // route the saved-connections form and admin.js's endpoint manager call —
    // POST .../model-endpoints/test with the level's own (unsaved) address/key.
    const testBtn = row.querySelector('.ml-test');
    if (testBtn) {
      testBtn.addEventListener('click', async () => {
        _syncFromDOM();
        const t = _tiers[i];
        const msgEl = row.querySelector('.ml-test-msg');
        if (msgEl) { msgEl.textContent = ''; msgEl.className = 'admin-toggle-sub ml-test-msg'; }
        if (!t || !t.base_url) {
          if (msgEl) { msgEl.textContent = 'Enter a server address to test.'; msgEl.className = 'admin-toggle-sub ml-test-msg admin-error'; }
          return;
        }
        testBtn.disabled = true;
        testBtn.textContent = 'Testing…';
        try {
          const fd = new FormData();
          fd.append('base_url', t.base_url);
          const keyEl = row.querySelector('.ml-key');
          const typedKey = keyEl ? keyEl.value.trim() : '';
          if (typedKey) fd.append('api_key', typedKey);
          const d = await _fetchJSON(`${SETUP}/model-endpoints/test`, { method: 'POST', body: fd });
          if (msgEl) {
            if (d && d.online) {
              const n = (d.models || []).length;
              msgEl.textContent = n ? `Online — found ${n} model${n !== 1 ? 's' : ''}` : 'Online — no models found';
              msgEl.className = 'admin-toggle-sub ml-test-msg admin-success';
            } else {
              msgEl.textContent = (d && d.ping_error) || 'Offline';
              msgEl.className = 'admin-toggle-sub ml-test-msg admin-error';
            }
          }
        } catch (e) {
          if (msgEl) { msgEl.textContent = e.message || 'Test failed.'; msgEl.className = 'admin-toggle-sub ml-test-msg admin-error'; }
        }
        testBtn.disabled = false;
        testBtn.textContent = 'Test this level';
      });
    }
  });
}

// lens 01 #19: the ladder's API-key field had no show/hide toggle, unlike the
// Vault's password fields — a masked key can't be visually double-checked
// before saving (a wrong paste just silently fails auth later). Mirrors
// applicantVault.js's `_wireSecretToggles` pattern exactly, scoped to this
// row's own key input.
function _wireKeyToggles() {
  if (!_host) return;
  _host.querySelectorAll('.ml-key-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      const row = btn.closest('[data-tier-row]');
      const input = row && row.querySelector('.ml-key');
      if (!input) return;
      const revealing = input.type === 'password';
      input.type = revealing ? 'text' : 'password';
      btn.textContent = revealing ? 'Hide' : 'Show';
      btn.setAttribute('aria-pressed', String(revealing));
    });
  });
}

// lens 01 #51: wires the shared dragSort.js kit onto the ladder's own drag
// handle (`.ml-drag-handle`), the same pattern models.js/sessions.js and the
// image editor's layer panel already use (`handleSelector` scoped to a
// dedicated grip icon, never the whole row — dragSort's mouse path has no
// input/button exclusion of its own, so without a handle a single click to
// focus a text field would instead start a drag). The Up/Down buttons stay:
// they're the keyboard-operable path (dragSort is mouse/touch-only), and
// keep working for #50's focus-restore.
function _wireDragReorder() {
  if (!_host || !dragSortModule) return;
  dragSortModule.enable('ml-rows', '[data-tier-row]', {
    handleSelector: '.ml-drag-handle',
    onReorder: _onDragReorder,
  });
}

// Rebuilds _tiers in the dropped-into-place DOM order. dragSort physically
// moves the row elements before calling back, but each row still carries its
// PRE-drag `data-tier-row` index (rows aren't re-rendered until after this),
// so map each element back to its tier by that old index rather than trusting
// position. Flush any in-flight field edits first (_syncFromDOM keys off the
// same old index, so it's order-agnostic) so a drag never discards a
// not-yet-blurred edit the way it would if we reordered from stale data.
function _onDragReorder(orderedEls) {
  _syncFromDOM();
  const newTiers = orderedEls
    .map((el) => {
      const oldIdx = parseInt(el.getAttribute('data-tier-row'), 10);
      return Number.isFinite(oldIdx) ? _tiers[oldIdx] : undefined;
    })
    .filter(Boolean);
  if (newTiers.length !== _tiers.length) return; // safety net: never apply a partial/mismatched reorder
  _tiers = newTiers;
  _markDirty();
  _render(false);
}

function _rowIndex(btn) {
  const row = btn.closest('[data-tier-row]');
  return row ? parseInt(row.getAttribute('data-tier-row'), 10) : -1;
}

// lens 01 #50: _render() rebuilds every row from scratch (fresh DOM nodes)
// on every reorder, which silently drops keyboard focus back to <body> — a
// keyboard user pressing the Up/Down move buttons repeatedly loses their
// place after the very first move and has to re-find the row by hand. Find
// the row for the SAME tier object (by identity, since its index just
// changed) after the re-render and refocus one of its own controls so
// repeated keyboard reordering keeps working from where the user actually is.
function _restoreFocusForTier(tier, preferredSelectors) {
  if (!_host || !tier) return;
  const idx = _tiers.indexOf(tier);
  if (idx < 0) return;
  const row = _host.querySelector(`[data-tier-row="${idx}"]`);
  if (!row) return;
  const selectors = preferredSelectors || ['.ml-up', '.ml-down', '.ml-del'];
  for (const sel of selectors) {
    const el = row.querySelector(sel);
    if (el && !el.disabled) {
      try { el.focus(); } catch { /* no-op */ }
      return;
    }
  }
}

function _move(i, delta) {
  _syncFromDOM();
  const j = i + delta;
  if (i < 0 || j < 0 || j >= _tiers.length) return;
  const movedTier = _tiers[i];
  const tmp = _tiers[i]; _tiers[i] = _tiers[j]; _tiers[j] = tmp;
  _markDirty();
  _render(false);
  _restoreFocusForTier(movedTier);
}

// lens 01 #13: removing a level was a single click with no confirmation, even
// when that level had a saved API key — a stray misclick silently deleted a
// credential the user would otherwise have to re-enter (or re-generate) with
// no undo. A keyless row stays the previous 1-click removal (nothing at risk);
// a row with a saved key (`_hasKey`) now requires an explicit, danger-styled
// confirm first, same shape as the saved-connections "Remove" confirm above.
async function _remove(i) {
  _syncFromDOM();
  if (_tiers.length <= 1 || i < 0 || !_tiers[i]) return;
  const t = _tiers[i];
  if (t._hasKey) {
    const ok = await uiModule.styledConfirm(
      `Remove Level ${i + 1}? Its saved API key will be deleted too — you'd need to re-enter it to use this level again.`,
      { confirmText: 'Remove', cancelText: 'Cancel', danger: true },
    );
    if (!ok) return;
  }
  _tiers.splice(i, 1);
  _markDirty();
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
      // DISC-4 precedence (matches the engine's own resolution order):
      //  1. a newly typed key wins;
      //  2. else a by-reference connection binding (send only the id — the
      //     engine resolves that connection's sealed key server-side at use
      //     time; the key never travels through the browser);
      //  3. else keep this tier's own already-sealed key by ref.
      if (t.api_key) tier.api_key = t.api_key;
      else if (t.connection_id) tier.connection_id = t.connection_id;
      else if (t._hasKey && t.api_key_ref) tier.api_key_ref = t.api_key_ref;
      return tier;
    }),
  };
  const saveBtn = _host.querySelector('#ml-save');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
  try {
    await _put(`${SETUP}/llm/tiers`, payload);
    _dirty = false; // cleared before the reload's re-render (lens 11 #33)
    _toast("Saved. I'll start at Level 1 and step up only when a task needs more.");
    await _load(); // re-read so saved-key markers refresh
  } catch (e) {
    _toast(e.message || "I couldn't save your levels.");
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save levels'; }
  }
}

export function mountModelLadder(host) {
  if (!host) return false;
  _host = host;
  _tiers = [];
  _dirty = false;
  _host.innerHTML = '<div class="hwfit-loading">Loading…</div>';
  _load().catch(e => {
    console.error('Failed to load model ladder:', e);
    if (_host) _host.innerHTML = `<div class="admin-card"><p class="admin-toggle-sub" style="opacity:0.7;margin:0;">I couldn't load your model levels. Reload to try again.</p></div>`;
  });
  return true;
}

if (typeof window !== 'undefined') window.mountApplicantModelLadder = mountModelLadder;

export default { mountModelLadder };
