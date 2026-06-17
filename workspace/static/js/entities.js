// Entity inspector — structured people/places/projects with confidence.
// Lives as a tab inside the Brain modal. Talks to /api/entities/* .
import uiModule from './ui.js';

const showToast = uiModule.showToast;
const showError = uiModule.showError;
const API = `${window.location.origin}/api/entities`;

let entities = [];
const expanded = new Set();

function el(id) { return document.getElementById(id); }

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export async function loadEntities() {
  try {
    const r = await fetch(`${API}`, { credentials: 'same-origin' });
    if (!r.ok) { entities = []; render(); return; }
    const data = await r.json();
    entities = data.entities || [];
  } catch (e) { console.error('loadEntities', e); entities = []; }
  const c = el('entities-count'); if (c) c.textContent = entities.length;
  render();
}

function confidenceBar(conf) {
  const pct = Math.round((conf || 0) * 100);
  const hue = Math.round(120 * (conf || 0)); // red→green
  return `<span style="display:inline-flex;align-items:center;gap:6px">
    <span style="width:60px;height:6px;border-radius:3px;background:var(--border);overflow:hidden;display:inline-block">
      <span style="display:block;height:100%;width:${pct}%;background:hsl(${hue},70%,45%)"></span>
    </span><span style="font-size:10px;opacity:0.6">${pct}%</span></span>`;
}

async function toggleExpand(id, card) {
  if (expanded.has(id)) { expanded.delete(id); renderDetail(card, null); return; }
  expanded.add(id);
  try {
    const r = await fetch(`${API}/${id}`, { credentials: 'same-origin' });
    if (!r.ok) return;
    renderDetail(card, await r.json());
  } catch (e) { console.error(e); }
}

function renderDetail(card, detail) {
  let box = card.querySelector('.entity-detail');
  if (!detail) { if (box) box.remove(); return; }
  if (!box) {
    box = document.createElement('div');
    box.className = 'entity-detail';
    box.style.cssText = 'margin-top:8px;padding-top:8px;border-top:1px solid var(--border)';
    card.appendChild(box);
  }
  const facts = (detail.facts || []).map((f) =>
    `<div style="display:flex;align-items:center;gap:8px;font-size:12px;padding:2px 0">
       <span style="flex:1">${escapeHtml(f.text)}</span>${confidenceBar(f.confidence)}
     </div>`).join('') || '<div style="font-size:12px;opacity:0.5">No facts yet.</div>';
  const rels = (detail.relationships || []).map((r) =>
    `<span class="pill" style="font-size:11px;opacity:0.7">${escapeHtml(r.type)} →</span>`).join(' ');
  box.innerHTML = `<div style="font-size:11px;opacity:0.6;margin-bottom:3px">Facts</div>${facts}
    ${rels ? `<div style="font-size:11px;opacity:0.6;margin:6px 0 3px">Relationships</div>${rels}` : ''}`;
}

function render() {
  const list = el('entities-list');
  const empty = el('entities-empty');
  if (!list) return;
  list.innerHTML = '';
  if (!entities.length) { if (empty) empty.style.display = ''; return; }
  if (empty) empty.style.display = 'none';
  entities.forEach((e) => {
    const card = document.createElement('div');
    card.style.cssText = 'padding:10px;border:1px solid var(--border);border-radius:8px';
    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;cursor:pointer" data-exp="${e.id}">
        <span class="pill" style="font-size:10px;text-transform:uppercase;opacity:0.6">${escapeHtml(e.type)}</span>
        <span style="font-weight:600;font-size:13px;flex:1">${escapeHtml(e.name)}</span>
        <button class="icon-btn" data-del="${e.id}" title="Delete" style="opacity:0.5">🗑</button>
      </div>`;
    list.appendChild(card);
    card.querySelector('[data-exp]').addEventListener('click', (ev) => {
      if (ev.target.closest('[data-del]')) return;
      toggleExpand(e.id, card);
    });
    card.querySelector('[data-del]').addEventListener('click', () => deleteEntity(e.id));
  });
}

async function addEntity() {
  const name = (el('entity-new-name').value || '').trim();
  const type = el('entity-new-type').value || 'person';
  if (!name) { showError('Enter a name'); return; }
  try {
    const r = await fetch(`${API}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify({ name, type }),
    });
    if (!r.ok) { showError('Failed to add entity'); return; }
    el('entity-new-name').value = '';
    showToast('Entity added');
    await loadEntities();
  } catch (e) { console.error(e); showError('Failed to add entity'); }
}

async function deleteEntity(id) {
  try {
    const r = await fetch(`${API}/${id}`, { method: 'DELETE', credentials: 'same-origin' });
    if (!r.ok) { showError('Failed to delete'); return; }
    entities = entities.filter((x) => x.id !== id);
    const c = el('entities-count'); if (c) c.textContent = entities.length;
    render();
    showToast('Entity deleted');
  } catch (e) { console.error(e); }
}

let _wired = false;
export function initEntities() {
  loadEntities();
  if (_wired) return; _wired = true;
  const add = el('entity-add-btn'); if (add) add.addEventListener('click', addEntity);
}

// ===========================================================================
// Job-application Profile — the engine-backed attribute cloud + what the
// assistant has learned. Lives as the "Profile" tab inside the Brain modal and
// talks to the workspace proxy at /api/applicant/memory/* (which forwards to the
// application engine). Plain-language UI; no engine internals leak to the user.
// The tab is greyed by the feature-activation layer until the engine is set up,
// and this module additionally degrades to a friendly "not ready" note if the
// engine is unreachable or onboarding is unfinished.
// ===========================================================================

const PROFILE_API = `${window.location.origin}/api/applicant/memory`;
let _profileCampaign = null;

function _show(id, on) { const e = el(id); if (e) e.classList.toggle('hidden', !on); }

async function _profileFetch(path, opts) {
  // Returns { ok, status, data }. Never throws — callers branch on status so the
  // engine's own gates (409 confirm-required, 422 sensitive) reach the UI.
  try {
    const r = await fetch(`${PROFILE_API}${path}`, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...(opts || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (_) { data = null; }
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    console.error('profileFetch', path, e);
    return { ok: false, status: 0, data: null };
  }
}

function _detailOf(data, fallback) {
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && data.detail != null) { try { return JSON.stringify(data.detail); } catch (_) { /* noop */ } }
  return fallback;
}

async function loadApplicantProfile() {
  const status = await _profileFetch('/status');
  const ready = !!(status.data && status.data.ready);
  _profileCampaign = (status.data && status.data.campaign_id) || null;
  _show('applicant-profile-unready', !ready);
  _show('applicant-profile-body', ready);
  if (!ready) return;
  await Promise.all([
    loadProfileAttributes(),
    loadProfileLearning(),
    loadProfileCriteria(),
    loadSuggestedAttributes(),
    loadBannedPhrases(),
  ]);
}

// ===========================================================================
// Criteria — what jobs to look for (FR-CRIT-2/3). UI-editable titles/locations/
// work-modes/keywords/salary floor, with learned (auto-tuned) adjustments shown
// and clearable. Integral edits route through the engine's 409 confirm gate.
// ===========================================================================

let _criteria = null;

function _csvToList(s) {
  return String(s || '').split(',').map((x) => x.trim()).filter(Boolean);
}
function _listToCsv(arr) {
  return (Array.isArray(arr) ? arr : []).join(', ');
}

async function loadProfileCriteria() {
  const res = await _profileFetch('/criteria');
  if (!res.ok) { _criteria = null; return; }
  _criteria = res.data || {};
  const set = (id, v) => { const e = el(id); if (e) e.value = v; };
  set('applicant-crit-titles', _listToCsv(_criteria.titles));
  set('applicant-crit-locations', _listToCsv(_criteria.locations));
  set('applicant-crit-workmodes', _listToCsv(_criteria.work_modes));
  set('applicant-crit-keywords', _listToCsv(_criteria.keywords));
  set('applicant-crit-salary', _criteria.salary_floor != null ? _criteria.salary_floor : '');
  // Learned adjustments (auto-tuning the assistant applied from your feedback).
  const learned = _criteria.learned_adjustments;
  const card = el('applicant-crit-learned');
  const body = el('applicant-crit-learned-body');
  const has = learned && (Array.isArray(learned) ? learned.length : Object.keys(learned).length);
  _show('applicant-crit-learned', !!has);
  if (has && body) {
    try {
      body.textContent = typeof learned === 'string' ? learned : JSON.stringify(learned, null, 2);
    } catch (_) { body.textContent = String(learned); }
  }
}

async function saveProfileCriteria(confirm) {
  const salaryRaw = (el('applicant-crit-salary') && el('applicant-crit-salary').value || '').trim();
  const body = {
    titles: _csvToList(el('applicant-crit-titles') && el('applicant-crit-titles').value),
    locations: _csvToList(el('applicant-crit-locations') && el('applicant-crit-locations').value),
    work_modes: _csvToList(el('applicant-crit-workmodes') && el('applicant-crit-workmodes').value),
    keywords: _csvToList(el('applicant-crit-keywords') && el('applicant-crit-keywords').value),
    confirm: !!confirm,
  };
  if (salaryRaw !== '') {
    const n = parseInt(salaryRaw, 10);
    if (!isNaN(n)) body.salary_floor = n;
  }
  const res = await _profileFetch('/criteria', { method: 'PUT', body: JSON.stringify(body) });
  if (res.ok) { showToast('Search settings saved'); _criteria = res.data || _criteria; await loadProfileCriteria(); return; }
  if (res.status === 409) {
    // Integral change — the engine wants explicit confirmation.
    if (window.confirm('This is a major change to what jobs are targeted. Save it anyway?')) await saveProfileCriteria(true);
    return;
  }
  if (res.status === 503) { showError('The assistant is not ready yet. Try again shortly.'); return; }
  showError(_detailOf(res.data, 'Could not save your search settings'));
}

async function clearLearnedCriteria() {
  if (!window.confirm('Discard the assistant’s auto-tuning and keep only your own settings?')) return;
  // clear_learned is honoured by the engine PUT; send it with confirm so an
  // integral reset is not blocked by the gate.
  const res = await _profileFetch('/criteria', { method: 'PUT', body: JSON.stringify({ clear_learned: true, confirm: true }) });
  if (res.ok) { showToast('Auto-tuning cleared'); await loadProfileCriteria(); return; }
  showError(_detailOf(res.data, 'Could not clear auto-tuning'));
}

// ===========================================================================
// Suggested attributes — the confirm queue for engine-proposed details
// (FR-ATTR-4). The assistant proposes non-sensitive details it noticed; the
// owner confirms (commit via ai-add) or dismisses. We surface suggestions from
// the status payload's pending list when present; otherwise the section hides.
// ===========================================================================

const _dismissedSuggestions = new Set();

async function loadSuggestedAttributes() {
  // Suggestions ride along on /status (engine-proposed, awaiting confirm). If the
  // engine does not surface any, the card stays hidden — no empty noise.
  let items = [];
  try {
    const res = await _profileFetch('/status');
    const s = res.data || {};
    const raw = s.suggested_attributes || s.pending_attributes || [];
    if (Array.isArray(raw)) items = raw;
  } catch (_) { items = []; }
  items = items.filter((it) => it && it.name && !_dismissedSuggestions.has(it.name + '=' + (it.value || '')));
  const card = el('applicant-suggested-card');
  const list = el('applicant-suggested-list');
  const count = el('applicant-suggested-count');
  if (count) count.textContent = items.length ? items.length : '';
  _show('applicant-suggested-card', items.length > 0);
  if (!list) return;
  list.innerHTML = '';
  items.forEach((it) => {
    const row = document.createElement('div');
    row.className = 'admin-card';
    row.style.cssText = 'margin-bottom:0;display:flex;align-items:center;gap:8px';
    row.innerHTML = `<div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:13px">${escapeHtml(it.name)}</div>
        <div style="font-size:12px;opacity:0.75;word-break:break-word">${escapeHtml(it.value || '')}</div>
      </div>`;
    const add = document.createElement('button');
    add.className = 'admin-btn-add'; add.textContent = 'Add'; add.title = 'Confirm and save this detail';
    add.addEventListener('click', () => confirmSuggestedAttribute(it));
    const skip = document.createElement('button');
    skip.className = 'memory-toolbar-btn'; skip.textContent = 'Dismiss'; skip.title = 'Ignore this suggestion';
    skip.addEventListener('click', () => { _dismissedSuggestions.add(it.name + '=' + (it.value || '')); loadSuggestedAttributes(); });
    row.appendChild(add); row.appendChild(skip);
    list.appendChild(row);
  });
}

async function confirmSuggestedAttribute(it, confirm) {
  const body = { name: it.name, value: it.value || '', confirm: !!confirm };
  const res = await _profileFetch('/attributes/ai-add', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    showToast('Detail added');
    _dismissedSuggestions.add(it.name + '=' + (it.value || ''));
    await Promise.all([loadSuggestedAttributes(), loadProfileAttributes()]);
    return;
  }
  if (res.status === 409) {
    if (window.confirm(`"${it.name}" looks like a core detail. Add it anyway?`)) await confirmSuggestedAttribute(it, true);
    return;
  }
  if (res.status === 422) { showError('Sensitive details must be typed in by you — they are never guessed.'); return; }
  showError(_detailOf(res.data, 'Could not add that detail'));
}

// ===========================================================================
// Writing style — banned "no-AI-look" phrases (FR-RESUME-5) and the grayed
// aggressiveness dial (FR-RESUME-9). Banned phrases call the documents proxy.
// ===========================================================================

const DOCS_API = `${window.location.origin}/api/applicant/documents`;

async function _docsFetch(path, opts) {
  try {
    const r = await fetch(`${DOCS_API}${path}`, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...(opts || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (_) { data = null; }
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    console.error('docsFetch', path, e);
    return { ok: false, status: 0, data: null };
  }
}

async function loadBannedPhrases() {
  const res = await _docsFetch('/banned-phrases');
  const input = el('applicant-banned-input');
  const seed = el('applicant-banned-seed');
  if (!res.ok) {
    if (seed) seed.textContent = '';
    return;
  }
  const d = res.data || {};
  if (input) input.value = (d.phrases || []).join('\n');
  if (seed) {
    const baseline = d.seed_phrases || [];
    seed.textContent = baseline.length
      ? `Always removed (built-in): ${baseline.join(', ')}`
      : '';
  }
}

async function saveBannedPhrases() {
  const input = el('applicant-banned-input');
  const phrases = String(input && input.value || '')
    .split('\n').map((x) => x.trim()).filter(Boolean);
  const res = await _docsFetch('/banned-phrases', { method: 'POST', body: JSON.stringify({ phrases }) });
  if (res.ok) { showToast('Phrase list saved'); await loadBannedPhrases(); return; }
  if (res.status === 403) { showError('You do not have permission to change this.'); return; }
  showError((res.data && res.data.message) || 'Could not save the phrase list');
}

async function loadProfileAttributes() {
  const list = el('applicant-attr-list');
  const empty = el('applicant-attr-empty');
  const res = await _profileFetch('/attributes');
  const items = (res.data && res.data.items) || [];
  const countEl = el('applicant-attr-count'); if (countEl) countEl.textContent = items.length;
  const tabCount = el('applicant-profile-count'); if (tabCount) tabCount.textContent = items.length;
  if (!list) return;
  list.innerHTML = '';
  if (!items.length) { if (empty) empty.style.display = ''; return; }
  if (empty) empty.style.display = 'none';
  // Lifted from memory.js renderMemoryList (workspace/static/js/memory.js,
  // ~line 579): a `.memory-item` row with `.memory-item-content`
  // (`.memory-item-text` + `.memory-item-meta` pill badges) and a hover-revealed
  // `.memory-item-actions` cluster of `.memory-item-btn`s. Reusing the same
  // markup + classes gives the Profile attributes the workspace memory styling
  // and inline-edit behavior. The engine-backed proxy calls below are unchanged.
  items.forEach((a) => {
    const item = document.createElement('div');
    item.className = 'memory-item';

    const content = document.createElement('div');
    content.className = 'memory-item-content';

    const textSpan = document.createElement('span');
    textSpan.className = 'memory-item-text';
    textSpan.innerHTML = `<strong>${escapeHtml(a.name)}</strong>: ${escapeHtml(a.value)}`;
    textSpan.style.cursor = 'text';
    textSpan.title = 'Double-click to edit';
    textSpan.addEventListener('dblclick', (e) => { e.stopPropagation(); startAttrEdit(item, a); });

    const meta = document.createElement('div');
    meta.className = 'memory-item-meta';
    if (a.is_sensitive) {
      const b = document.createElement('span');
      b.className = 'memory-cat-badge';
      b.textContent = 'sensitive';
      b.title = 'Only ever taken from what you type — never guessed';
      meta.appendChild(b);
    }
    if (a.is_integral) {
      const b = document.createElement('span');
      b.className = 'memory-cat-badge memory-cat-pinned';
      b.textContent = 'core';
      b.title = 'A core detail — changing it asks you to confirm';
      meta.appendChild(b);
    }

    content.appendChild(textSpan);
    content.appendChild(meta);
    item.appendChild(content);

    // Edit / Bind / Delete affordances — same `.memory-item-actions` /
    // `.memory-item-btn` cluster as the memory rows.
    const actions = document.createElement('div');
    actions.className = 'memory-item-actions';
    const editBtn = document.createElement('button');
    editBtn.className = 'memory-item-btn';
    editBtn.textContent = 'edit';
    editBtn.title = 'Change this value';
    editBtn.addEventListener('click', () => startAttrEdit(item, a));
    const bindBtn = document.createElement('button');
    bindBtn.className = 'memory-item-btn';
    bindBtn.textContent = 'bind';
    bindBtn.title = 'Pin this detail to a specific application form field';
    bindBtn.addEventListener('click', () => startAttrBind(item, a));
    const delBtn = document.createElement('button');
    delBtn.className = 'memory-item-btn delete';
    delBtn.textContent = 'delete';
    delBtn.title = 'Remove this detail';
    delBtn.addEventListener('click', () => deleteProfileAttribute(a));
    actions.appendChild(editBtn);
    actions.appendChild(bindBtn);
    actions.appendChild(delBtn);
    item.appendChild(actions);

    list.appendChild(item);
  });
}

// --- attribute edit (re-uses the upsert endpoint; same name overwrites) -----
// Lifted from memory.js startInlineEdit (~line 862): swap the row for a
// `.memory-edit-row` holding a `.memory-item-edit-input`, plus a
// `.memory-item-actions` save/cancel pair, with Enter=save / Escape=cancel.
function startAttrEdit(item, a) {
  item.innerHTML = '';
  item.className = 'memory-item memory-item-editing';

  const editRow = document.createElement('div');
  editRow.className = 'memory-edit-row';
  const label = document.createElement('span');
  label.className = 'memory-item-text';
  label.style.cssText = 'flex-shrink:0;align-self:center';
  label.innerHTML = `<strong>${escapeHtml(a.name)}</strong>`;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'memory-item-edit-input';
  input.value = a.value;
  editRow.appendChild(label);
  editRow.appendChild(input);

  const actions = document.createElement('div');
  actions.className = 'memory-item-actions';
  actions.style.opacity = '1';
  const save = document.createElement('button');
  save.className = 'memory-item-btn save';
  save.textContent = 'save';
  const cancel = document.createElement('button');
  cancel.className = 'memory-item-btn';
  cancel.textContent = 'cancel';
  actions.appendChild(save);
  actions.appendChild(cancel);

  item.appendChild(editRow);
  item.appendChild(actions);
  input.focus();
  input.select();
  cancel.addEventListener('click', loadProfileAttributes);
  const commit = async (confirm) => {
    const value = input.value.trim();
    if (!value) { showError('Value cannot be empty'); return; }
    const body = { name: a.name, value, is_sensitive: !!a.is_sensitive, is_integral: !!a.is_integral, confirm: !!confirm };
    const res = await _profileFetch('/attributes', { method: 'POST', body: JSON.stringify(body) });
    if (res.ok) { showToast('Detail updated'); await loadProfileAttributes(); return; }
    if (res.status === 409) {
      if (window.confirm(`"${a.name}" is a core detail. Save the new value anyway?`)) await commit(true);
      return;
    }
    if (res.status === 422) { showError('Sensitive details must be typed in by you — they are never guessed.'); return; }
    showError(_detailOf(res.data, 'Could not update that detail'));
  };
  save.addEventListener('click', () => commit(false));
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(false); if (e.key === 'Escape') loadProfileAttributes(); });
}

// --- attribute -> form-field binding ----------------------------------------
// Same inline-edit-in-place pattern as startAttrEdit: replace the
// `.memory-item` row's contents with the bind form.
function startAttrBind(item, a) {
  item.innerHTML = '';
  item.className = 'memory-item memory-item-editing';
  const wrap = document.createElement('div');
  wrap.style.cssText = 'flex:1;display:flex;flex-direction:column;gap:6px';
  wrap.innerHTML = `<div class="memory-item-text"><strong>Pin “${escapeHtml(a.name)}” to a form field</strong></div>`;
  const siteIn = document.createElement('input');
  siteIn.type = 'text'; siteIn.className = 'memory-item-edit-input';
  siteIn.placeholder = 'Site (e.g. greenhouse)'; siteIn.title = 'Which application site this field is on';
  const selIn = document.createElement('input');
  selIn.type = 'text'; selIn.className = 'memory-item-edit-input';
  selIn.placeholder = 'Field (e.g. #phone)'; selIn.title = 'The form field this detail should fill';
  const sharedLabel = document.createElement('label');
  sharedLabel.style.cssText = 'font-size:11px;opacity:0.75;display:flex;align-items:center;gap:5px';
  sharedLabel.innerHTML = '<input type="checkbox"> Reuse this mapping across sites';
  const btnRow = document.createElement('div');
  btnRow.className = 'memory-item-actions';
  btnRow.style.opacity = '1';
  const save = document.createElement('button');
  save.className = 'memory-item-btn save'; save.textContent = 'save mapping';
  const cancel = document.createElement('button');
  cancel.className = 'memory-item-btn'; cancel.textContent = 'cancel';
  btnRow.appendChild(save); btnRow.appendChild(cancel);
  wrap.appendChild(siteIn); wrap.appendChild(selIn); wrap.appendChild(sharedLabel); wrap.appendChild(btnRow);
  item.appendChild(wrap);
  siteIn.focus();
  cancel.addEventListener('click', loadProfileAttributes);
  save.addEventListener('click', async () => {
    const site_key = siteIn.value.trim();
    const field_selector = selIn.value.trim();
    if (!site_key || !field_selector) { showError('Enter both a site and a field'); return; }
    const body = {
      site_key, field_selector, attribute_id: a.id,
      shared: !!sharedLabel.querySelector('input').checked,
    };
    const res = await _profileFetch('/attributes/bind', { method: 'POST', body: JSON.stringify(body) });
    if (res.ok) { showToast('Field mapping saved'); await loadProfileAttributes(); return; }
    if (res.status === 503) { showError('The assistant is not ready yet. Try again shortly.'); return; }
    showError(_detailOf(res.data, 'Could not save that mapping'));
  });
}

async function deleteProfileAttribute(a) {
  // Same delete-confirm pattern as memory.js deleteMemory (~line 1040).
  if (!await uiModule.styledConfirm(`Remove "${a.name}"?`, { confirmText: 'Delete', danger: true })) return;
  const res = await _profileFetch(`/attributes/${encodeURIComponent(a.id)}`, { method: 'DELETE' });
  if (res.ok) { showToast('Detail removed'); await loadProfileAttributes(); return; }
  showError(_detailOf(res.data, 'Could not remove that detail'));
}

async function addProfileAttribute(confirm) {
  const nameEl = el('applicant-attr-name');
  const valueEl = el('applicant-attr-value');
  const sensEl = el('applicant-attr-sensitive');
  const name = (nameEl && nameEl.value || '').trim();
  const value = (valueEl && valueEl.value || '').trim();
  if (!name || !value) { showError('Enter both a detail and a value'); return; }
  const body = { name, value, is_sensitive: !!(sensEl && sensEl.checked), confirm: !!confirm };
  const res = await _profileFetch('/attributes', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    if (nameEl) nameEl.value = '';
    if (valueEl) valueEl.value = '';
    if (sensEl) sensEl.checked = false;
    showToast('Detail saved');
    await loadProfileAttributes();
    return;
  }
  if (res.status === 409) {
    // Engine confirmation gate: this overwrites a core detail. Ask, then retry.
    if (window.confirm(`"${name}" looks like a core detail. Save the new value anyway?`)) {
      await addProfileAttribute(true);
    }
    return;
  }
  if (res.status === 422) {
    showError('Sensitive details must be typed in by you — they are never guessed.');
    return;
  }
  if (res.status === 503) { showError('The assistant is not ready yet. Try again shortly.'); return; }
  showError(_detailOf(res.data, 'Could not save that detail'));
}

const _ENGINE_LABEL = { latex: 'a typeset (LaTeX) resume', docx: 'a Word (.docx) resume' };
function _engineLabel(v) { return _ENGINE_LABEL[v] || (v ? `the “${escapeHtml(String(v))}” format` : 'no format yet'); }

async function loadProfileLearning() {
  const body = el('applicant-learning-body');
  const actions = el('applicant-learning-actions');
  if (actions) actions.innerHTML = '';
  const res = await _profileFetch('/learning');
  if (!res.ok) {
    if (body) body.textContent = 'Nothing learned yet.';
    return;
  }
  const engine = res.data && res.data.engine;
  if (body) body.innerHTML = `Right now the assistant prepares <strong>${_engineLabel(engine)}</strong> for your applications.`;
  if (actions) {
    const previewBtn = document.createElement('button');
    previewBtn.className = 'memory-toolbar-btn';
    previewBtn.textContent = 'Preview typeset version';
    previewBtn.title = 'Build a typeset (LaTeX) version of your resume to compare';
    previewBtn.addEventListener('click', previewProfileLearning);
    actions.appendChild(previewBtn);
  }
}

async function previewProfileLearning() {
  const body = el('applicant-learning-body');
  const actions = el('applicant-learning-actions');
  if (body) body.textContent = 'Building a preview…';
  const res = await _profileFetch('/learning/preview', { method: 'POST', body: JSON.stringify({}) });
  if (!res.ok) {
    showError(_detailOf(res.data, 'Could not build a preview'));
    await loadProfileLearning();
    return;
  }
  const d = res.data || {};
  const fidelity = d.fidelity_ok === false ? ' (some formatting may differ)' : '';
  const pages = d.page_count != null ? `${d.page_count}-page ` : '';
  if (body) body.innerHTML = `Preview ready: a ${escapeHtml(String(pages))}typeset resume${escapeHtml(fidelity)}. Keep it, or stay with the current format.`;
  if (actions) {
    actions.innerHTML = '';
    const accept = document.createElement('button');
    accept.className = 'admin-btn-add';
    accept.textContent = 'Use the typeset version';
    accept.addEventListener('click', () => decideProfileLearning('accept'));
    const reject = document.createElement('button');
    reject.className = 'memory-toolbar-btn';
    reject.textContent = 'Keep the current format';
    reject.addEventListener('click', () => decideProfileLearning('reject'));
    actions.appendChild(accept);
    actions.appendChild(reject);
  }
}

async function decideProfileLearning(which) {
  const res = await _profileFetch(`/learning/${which}`, { method: 'POST', body: JSON.stringify({}) });
  if (!res.ok) { showError(_detailOf(res.data, 'Could not save your choice')); return; }
  showToast(which === 'accept' ? 'Switched to the typeset resume' : 'Kept the current format');
  await loadProfileLearning();
}

let _profileWired = false;
export function initApplicantProfile() {
  loadApplicantProfile();
  if (_profileWired) return; _profileWired = true;
  const add = el('applicant-attr-add-btn'); if (add) add.addEventListener('click', () => addProfileAttribute(false));
  const refresh = el('applicant-attr-refresh-btn'); if (refresh) refresh.addEventListener('click', loadProfileAttributes);
  const lrefresh = el('applicant-learning-refresh-btn'); if (lrefresh) lrefresh.addEventListener('click', loadProfileLearning);
  // Enter-to-add from the value field.
  const valueEl = el('applicant-attr-value');
  if (valueEl) valueEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') addProfileAttribute(false); });

  // Criteria editor.
  const critSave = el('applicant-crit-save-btn'); if (critSave) critSave.addEventListener('click', () => saveProfileCriteria(false));
  const critRefresh = el('applicant-criteria-refresh-btn'); if (critRefresh) critRefresh.addEventListener('click', loadProfileCriteria);
  const critClear = el('applicant-crit-clear-learned-btn'); if (critClear) critClear.addEventListener('click', clearLearnedCriteria);

  // Suggested-attribute queue.
  const sugRefresh = el('applicant-suggested-refresh-btn'); if (sugRefresh) sugRefresh.addEventListener('click', loadSuggestedAttributes);

  // Writing style — banned phrases + (grayed) aggressiveness.
  const banSave = el('applicant-banned-save-btn'); if (banSave) banSave.addEventListener('click', saveBannedPhrases);
  const banRefresh = el('applicant-banned-refresh-btn'); if (banRefresh) banRefresh.addEventListener('click', loadBannedPhrases);
  const aggr = el('applicant-aggr-slider');
  const aggrVal = el('applicant-aggr-value');
  if (aggr && aggrVal) aggr.addEventListener('input', () => { aggrVal.textContent = aggr.value; });
}

const entitiesModule = {
  loadEntities, initEntities, initApplicantProfile, loadApplicantProfile,
  loadProfileCriteria, saveProfileCriteria, clearLearnedCriteria,
  loadSuggestedAttributes, loadBannedPhrases, saveBannedPhrases,
};
export default entitiesModule;
window.entitiesModule = entitiesModule;
