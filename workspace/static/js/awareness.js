// Awareness panel — proactive triggers + notification feed.
// Talks to /api/awareness/* (see routes/awareness_routes.py).
import uiModule from './ui.js';

const showToast = uiModule.showToast;
const showError = uiModule.showError;

const API = `${window.location.origin}/api/awareness`;

let triggers = [];
let feed = [];

function el(id) { return document.getElementById(id); }

async function loadTriggers() {
  try {
    const r = await fetch(`${API}/triggers`, { credentials: 'same-origin' });
    if (!r.ok) { triggers = []; renderTriggers(); return; }
    const data = await r.json();
    triggers = data.triggers || [];
  } catch (e) { console.error('awareness loadTriggers', e); triggers = []; }
  renderTriggers();
}

function _conditionLabel(c) {
  if (!c) return 'fuzzy (LLM-judged)';
  if (c.fuzzy) return `fuzzy: ${c.fuzzy}`;
  if (c.field && c.op) return `${c.field} ${c.op} ${c.value}`;
  return JSON.stringify(c);
}

function renderTriggers() {
  const list = el('awareness-triggers-list');
  const empty = el('awareness-triggers-empty');
  if (!list) return;
  list.innerHTML = '';
  if (!triggers.length) { if (empty) empty.style.display = ''; return; }
  if (empty) empty.style.display = 'none';
  triggers.forEach((t) => {
    const row = document.createElement('div');
    row.className = 'list-item';
    row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px;border:1px solid var(--border);border-radius:8px';
    row.innerHTML = `
      <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
        <input type="checkbox" ${t.enabled ? 'checked' : ''} data-toggle="${t.id}">
      </label>
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:13px">${escapeHtml(t.name || 'Untitled')}</div>
        <div style="font-size:11px;opacity:0.55">${escapeHtml(_conditionLabel(t.condition))} · ${escapeHtml(t.channel || 'ntfy')}${t.enabled ? '' : ' · paused'}</div>
      </div>
      <button class="icon-btn" title="Delete" data-del="${t.id}" style="opacity:0.6">🗑</button>`;
    list.appendChild(row);
  });
  list.querySelectorAll('[data-toggle]').forEach((cb) => {
    cb.addEventListener('change', () => toggleTrigger(cb.getAttribute('data-toggle'), cb.checked));
  });
  list.querySelectorAll('[data-del]').forEach((b) => {
    b.addEventListener('click', () => deleteTrigger(b.getAttribute('data-del')));
  });
}

async function addTrigger() {
  const name = (el('awareness-new-name').value || '').trim();
  const minutes = parseInt(el('awareness-new-minutes').value, 10);
  if (!name) { showError('Give the trigger a name'); return; }
  const body = { name, channel: 'ntfy' };
  if (!Number.isNaN(minutes) && minutes > 0) {
    body.condition = { field: 'next_event_minutes', op: 'lte', value: minutes };
    body.description = `Heads up — next event in ${minutes} min or less.`;
  }
  try {
    const r = await fetch(`${API}/triggers`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify(body),
    });
    if (!r.ok) { showError('Failed to add trigger'); return; }
    el('awareness-new-name').value = '';
    el('awareness-new-minutes').value = '';
    showToast('Trigger added');
    await loadTriggers();
  } catch (e) { console.error(e); showError('Failed to add trigger'); }
}

async function toggleTrigger(id, enabled) {
  try {
    const r = await fetch(`${API}/triggers/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify({ enabled }),
    });
    if (!r.ok) { showError('Failed to update'); await loadTriggers(); return; }
    const t = triggers.find((x) => x.id === id); if (t) t.enabled = enabled;
    renderTriggers();
  } catch (e) { console.error(e); }
}

async function deleteTrigger(id) {
  try {
    const r = await fetch(`${API}/triggers/${id}`, { method: 'DELETE', credentials: 'same-origin' });
    if (!r.ok) { showError('Failed to delete'); return; }
    triggers = triggers.filter((x) => x.id !== id);
    renderTriggers();
    showToast('Trigger deleted');
  } catch (e) { console.error(e); }
}

async function loadFeed() {
  try {
    const r = await fetch(`${API}/notifications`, { credentials: 'same-origin' });
    if (!r.ok) { feed = []; renderFeed(); return; }
    const data = await r.json();
    feed = data.notifications || [];
  } catch (e) { console.error('awareness loadFeed', e); feed = []; }
  renderFeed();
}

function renderFeed() {
  const list = el('awareness-feed-list');
  const empty = el('awareness-feed-empty');
  if (!list) return;
  list.innerHTML = '';
  if (!feed.length) { if (empty) empty.style.display = ''; return; }
  if (empty) empty.style.display = 'none';
  feed.forEach((n) => {
    const row = document.createElement('div');
    row.style.cssText = 'padding:10px;border:1px solid var(--border);border-radius:8px';
    const when = n.created_at ? new Date(n.created_at).toLocaleString() : '';
    row.innerHTML = `
      <div style="font-weight:600;font-size:13px">${escapeHtml(n.title || '(no title)')}</div>
      <div style="font-size:12px;opacity:0.7;margin:2px 0">${escapeHtml(n.body || '')}</div>
      <div style="font-size:11px;opacity:0.45;display:flex;gap:8px;align-items:center">
        <span>${escapeHtml(when)} · ${escapeHtml(n.status || '')}</span>
        <span style="flex:1"></span>
        ${n.outcome ? `<em>marked ${escapeHtml(n.outcome)}</em>` : `<button class="icon-btn" data-useful="${n.id}">👍 useful</button><button class="icon-btn" data-dismiss="${n.id}">👎 dismiss</button>`}
      </div>`;
    list.appendChild(row);
  });
  list.querySelectorAll('[data-useful]').forEach((b) => b.addEventListener('click', () => setOutcome(b.getAttribute('data-useful'), 'useful')));
  list.querySelectorAll('[data-dismiss]').forEach((b) => b.addEventListener('click', () => setOutcome(b.getAttribute('data-dismiss'), 'dismissed')));
}

async function setOutcome(id, outcome) {
  try {
    const r = await fetch(`${API}/notifications/${id}/outcome`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify({ outcome }),
    });
    if (!r.ok) { showError('Failed to record'); return; }
    const n = feed.find((x) => x.id === id); if (n) n.outcome = outcome;
    renderFeed();
  } catch (e) { console.error(e); }
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function switchTab(name) {
  document.querySelectorAll('[data-awareness-tab]').forEach((b) => b.classList.toggle('active', b.getAttribute('data-awareness-tab') === name));
  document.querySelectorAll('[data-awareness-panel]').forEach((p) => p.classList.toggle('hidden', p.getAttribute('data-awareness-panel') !== name));
  if (name === 'feed') loadFeed();
}

let _wired = false;
function wireOnce() {
  if (_wired) return; _wired = true;
  const add = el('awareness-add-btn'); if (add) add.addEventListener('click', addTrigger);
  document.querySelectorAll('[data-awareness-tab]').forEach((b) => b.addEventListener('click', () => switchTab(b.getAttribute('data-awareness-tab'))));
}

export function openPanel() {
  const modal = el('awareness-modal');
  if (!modal) return;
  wireOnce();
  modal.classList.remove('hidden');
  switchTab('triggers');
  loadTriggers();
}

export function closePanel() {
  const modal = el('awareness-modal');
  if (modal) modal.classList.add('hidden');
}

const awarenessModule = { openPanel, closePanel, loadTriggers, loadFeed };
export default awarenessModule;
window.awarenessModule = awarenessModule;
