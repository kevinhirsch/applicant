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

const entitiesModule = { loadEntities, initEntities };
export default entitiesModule;
window.entitiesModule = entitiesModule;
