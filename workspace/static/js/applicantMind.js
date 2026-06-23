// static/js/applicantMind.js
//
// "What the assistant remembers" + "Saved playbooks" + learning curation
// approvals — the FR-MIND agent-learning substrate surfaced in the front door.
// ADDITIVE and self-contained: it opens its own modal panel, talks to the engine
// through the workspace proxy at /api/applicant/mind/*, and never touches the
// native Brain modal (memory.js / skills.js / entities.js) or its data.
//
// Reachability: the engine owns the logic (/api/agent-memory/*); this is a thin
// view over the owner-scoped proxy. The panel is reachable from the Brain modal
// (a "What the assistant remembers" button is appended when present) and from a
// global (window.applicantMindModule.openApplicantMind) for deep-links. When the
// engine is unreachable / no model is connected we render a graceful note instead
// of erroring, matching the rest of the Applicant front door.

import uiModule from './ui.js';

const API = '/api/applicant/mind';

let _modalEl = null;

function esc(s) {
  try {
    if (typeof uiModule.esc === 'function') return uiModule.esc(s);
  } catch { /* fall through */ }
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _toast(msg) {
  try { uiModule.showToast(msg); } catch { /* no-op */ }
}

async function _fetchJSON(url, opts = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data || {};
}

function _post(url) {
  return _fetchJSON(url, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
}

// --- modal shell -----------------------------------------------------------

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const el = document.createElement('div');
  el.id = 'applicant-mind-modal';
  el.style.cssText = 'position:fixed;inset:0;z-index:1200;display:none;align-items:center;'
    + 'justify-content:center;background:rgba(0,0,0,0.45);';
  el.innerHTML = `
    <div class="admin-card" role="dialog" aria-modal="true" aria-label="What the assistant remembers"
         style="width:min(720px,94vw);max-height:88vh;overflow:auto;padding:18px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <h3 style="margin:0;font-size:16px;">What the assistant remembers</h3>
        <button type="button" class="cal-btn applicant-mind-close" title="Close">Close</button>
      </div>
      <div class="applicant-mind-body" style="font-size:13px;"></div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (ev) => { if (ev.target === el) _close(); });
  el.querySelector('.applicant-mind-close').addEventListener('click', _close);
  _modalEl = el;
  return el;
}

function _close() {
  if (_modalEl) _modalEl.style.display = 'none';
}

function _body() {
  return _ensureModalEl().querySelector('.applicant-mind-body');
}

function _renderOffline() {
  _body().innerHTML = `
    <div class="memory-empty" style="padding:18px;text-align:center;opacity:0.85;">
      Connect an AI model to start building what the assistant remembers. You can do
      this in the setup wizard or under Settings.
    </div>`;
}

// --- section renderers -----------------------------------------------------

function _renderMemory(snap) {
  const env = (snap.environment || []);
  const usr = (snap.user || []);
  const line = (e) => `<li class="memory-item" style="margin:4px 0;">${esc(e.text)}</li>`;
  const block = (title, items, hint) => {
    const body = items.length
      ? `<ul style="margin:6px 0 0;padding-left:18px;">${items.map(line).join('')}</ul>`
      : `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">${esc(hint)}</div>`;
    return `<div class="memory-section" style="margin-bottom:14px;">
      <div style="font-weight:600;">${esc(title)}</div>${body}</div>`;
  };
  return block('Lessons about the work', env, 'Nothing remembered yet.')
    + block('Your preferences', usr, 'No preferences captured yet.');
}

function _renderSkills(skills) {
  const items = (skills.items || []);
  if (!items.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      No saved playbooks yet. The assistant writes these from its own work.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + items.map((s) => `
    <li class="memory-item" style="border:1px solid var(--border,#3334);border-radius:8px;
        padding:8px 10px;margin:6px 0;">
      <div style="font-weight:600;">${esc(s.name)}</div>
      <div style="opacity:0.85;">${esc(s.description || '')}</div>
      ${s.when_to_use ? `<div style="opacity:0.7;margin-top:2px;">When: ${esc(s.when_to_use)}</div>` : ''}
    </li>`).join('') + `</ul>`;
}

function _renderCuration(curation) {
  const items = (curation.items || []);
  if (!items.length) {
    return `<div class="memory-empty" style="opacity:0.7;padding:6px 0;">
      Nothing waiting for your review. New suggestions appear here before anything is saved.</div>`;
  }
  return `<ul style="margin:6px 0 0;padding-left:0;list-style:none;">` + items.map((p) => {
    const summary = p.type === 'skill'
      ? `${esc(p.label || 'Save a playbook')}: <b>${esc(p.name)}</b> — ${esc(p.description || '')}`
      : `${esc(p.label || 'Something to remember')}: ${esc(p.text || '')}`;
    const flag = p.claims_authority
      ? `<div style="color:var(--danger,#c0392b);margin-top:2px;">
           Heads up: this note mentions taking an action on its own — it is a suggestion only and
           grants no permission.</div>`
      : '';
    return `<li class="memory-item" data-proposal-id="${esc(p.id)}"
        style="border:1px solid var(--border,#3334);border-radius:8px;padding:8px 10px;margin:6px 0;">
      <div>${summary}</div>${flag}
      <div style="display:flex;gap:8px;margin-top:8px;">
        <button type="button" class="cal-btn applicant-mind-approve" data-id="${esc(p.id)}">Approve</button>
        <button type="button" class="cal-btn applicant-mind-deny" data-id="${esc(p.id)}">Dismiss</button>
      </div></li>`;
  }).join('') + `</ul>`;
}

function _wireCurationButtons() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-approve').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await _post(`${API}/curation/${encodeURIComponent(btn.dataset.id)}/approve`);
        _toast('Saved.');
        await openApplicantMind();
      } catch (e) {
        _toast(e.message || 'Could not save that.');
        btn.disabled = false;
      }
    });
  });
  body.querySelectorAll('.applicant-mind-deny').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await _post(`${API}/curation/${encodeURIComponent(btn.dataset.id)}/deny`);
        _toast('Dismissed.');
        await openApplicantMind();
      } catch (e) {
        _toast(e.message || 'Could not dismiss that.');
        btn.disabled = false;
      }
    });
  });
}

// --- open ------------------------------------------------------------------

export async function openApplicantMind() {
  const el = _ensureModalEl();
  el.style.display = 'flex';
  _body().innerHTML = '<div class="memory-empty" style="padding:18px;opacity:0.7;">Loading…</div>';
  try {
    const status = await _fetchJSON(`${API}/status`);
    if (!status.engine_available) { _renderOffline(); return; }
    const [snap, skills, curation] = await Promise.all([
      _fetchJSON(`${API}/memory`).catch(() => ({ environment: [], user: [] })),
      _fetchJSON(`${API}/skills`).catch(() => ({ items: [] })),
      _fetchJSON(`${API}/curation`).catch(() => ({ items: [] })),
    ]);
    _body().innerHTML = `
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">Waiting for your review</h4>
        ${_renderCuration(curation)}
      </div>
      <div class="memory-section" style="margin-bottom:18px;">
        <h4 style="margin:0 0 6px;">What the assistant remembers</h4>
        ${_renderMemory(snap)}
      </div>
      <div class="memory-section">
        <h4 style="margin:0 0 6px;">Saved playbooks</h4>
        ${_renderSkills(skills)}
      </div>`;
    _wireCurationButtons();
  } catch (e) {
    // 401 / engine unreachable — degrade to the connect-a-model note.
    _renderOffline();
  }
}

// --- launcher --------------------------------------------------------------

function _wireLauncher() {
  // Add a discreet entry point inside the Brain modal (the existing memory
  // surface) without hijacking its own launcher. We append a button once.
  const host = document.getElementById('memory-modal') || document.body;
  if (!host || host._applicantMindWired) return;
  const anchor = document.querySelector('#memory-modal h4') || null;
  if (anchor && !document.getElementById('applicant-mind-open-btn')) {
    const btn = document.createElement('button');
    btn.id = 'applicant-mind-open-btn';
    btn.type = 'button';
    btn.className = 'cal-btn';
    btn.textContent = 'What the assistant remembers';
    btn.style.cssText = 'margin-left:10px;font-size:12px;';
    btn.addEventListener('click', openApplicantMind);
    anchor.appendChild(btn);
    host._applicantMindWired = true;
  }
}

function _boot() {
  _wireLauncher();
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('applicant-mind-open-btn') || tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantMindModule = { openApplicantMind };
try { window.applicantMindModule = applicantMindModule; } catch { /* no-op */ }

export default applicantMindModule;
