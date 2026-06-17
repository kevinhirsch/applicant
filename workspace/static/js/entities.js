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
  await Promise.all([loadProfileAttributes(), loadProfileLearning()]);
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
  items.forEach((a) => {
    const card = document.createElement('div');
    card.style.cssText = 'padding:10px;border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;gap:8px';
    const tags = [];
    if (a.is_sensitive) tags.push('<span class="pill" style="font-size:10px;opacity:0.7" title="Only ever taken from what you type — never guessed">sensitive</span>');
    if (a.is_integral) tags.push('<span class="pill" style="font-size:10px;opacity:0.7" title="A core detail — changing it asks you to confirm">core</span>');
    card.innerHTML = `
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:13px">${escapeHtml(a.name)} ${tags.join(' ')}</div>
        <div style="font-size:12px;opacity:0.75;word-break:break-word">${escapeHtml(a.value)}</div>
      </div>`;
    list.appendChild(card);
  });
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
    accept.className = 'primary-btn';
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
}

const entitiesModule = { loadEntities, initEntities, initApplicantProfile, loadApplicantProfile };
export default entitiesModule;
window.entitiesModule = entitiesModule;
