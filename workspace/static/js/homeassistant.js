// Home Assistant settings panel — connection config + entity allowlist.
// Talks to /api/homeassistant/* (gated on can_control_home).
import uiModule from './ui.js';

const showToast = uiModule.showToast;
const showError = uiModule.showError;
const API = `${window.location.origin}/api/homeassistant`;

function el(id) { return document.getElementById(id); }
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function loadConfig() {
  try {
    const r = await fetch(`${API}/config`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const c = await r.json();
    el('ha-base-url').value = c.base_url || '';
    el('ha-enabled').checked = !!c.enabled;
    el('ha-allowlist').value = (c.allowlist || []).join('\n');
    el('ha-token').placeholder = c.token_set ? '•••••• (saved — leave blank to keep)' : 'Long-lived access token';
    const status = el('ha-status');
    if (status) status.textContent = c.token_set ? (c.enabled ? 'Configured & enabled' : 'Configured (disabled)') : 'Not configured';
  } catch (e) { console.error('ha loadConfig', e); }
}

async function saveConfig() {
  const body = {
    base_url: el('ha-base-url').value.trim(),
    enabled: el('ha-enabled').checked,
    allowlist: el('ha-allowlist').value.split('\n').map((s) => s.trim()).filter(Boolean),
  };
  const tok = el('ha-token').value.trim();
  if (tok) body.token = tok;            // only send when changed
  try {
    const r = await fetch(`${API}/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin', body: JSON.stringify(body),
    });
    if (!r.ok) { showError('Failed to save'); return; }
    el('ha-token').value = '';
    showToast('Home Assistant settings saved');
    await loadConfig();
  } catch (e) { console.error(e); showError('Failed to save'); }
}

async function loadStates() {
  const out = el('ha-states');
  if (out) out.innerHTML = '<div style="opacity:0.5;font-size:12px">Loading…</div>';
  try {
    const r = await fetch(`${API}/states`, { credentials: 'same-origin' });
    if (!r.ok) {
      const msg = (await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`;
      if (out) out.innerHTML = `<div style="font-size:12px;color:var(--red)">${escapeHtml(msg)}</div>`;
      return;
    }
    const data = await r.json();
    const states = data.states || [];
    if (out) out.innerHTML = states.length
      ? states.map((s) => `<div style="font-size:12px;display:flex;gap:8px"><code>${escapeHtml(s.entity_id)}</code><span style="opacity:0.6">${escapeHtml(s.state)}</span></div>`).join('')
      : '<div style="opacity:0.5;font-size:12px">No allowlisted entities returned.</div>';
  } catch (e) {
    if (out) out.innerHTML = `<div style="font-size:12px;color:var(--red)">${escapeHtml(String(e))}</div>`;
  }
}

let _wired = false;
export function openPanel() {
  const modal = el('homeassistant-modal');
  if (!modal) return;
  if (!_wired) {
    _wired = true;
    el('ha-save-btn')?.addEventListener('click', saveConfig);
    el('ha-refresh-states-btn')?.addEventListener('click', loadStates);
  }
  modal.classList.remove('hidden');
  loadConfig();
}

export function closePanel() {
  const modal = el('homeassistant-modal');
  if (modal) modal.classList.add('hidden');
}

const haModule = { openPanel, closePanel, loadConfig };
export default haModule;
window.haModule = haModule;
