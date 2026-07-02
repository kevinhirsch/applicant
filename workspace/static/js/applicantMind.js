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
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const API = '/api/applicant/mind';

let _modalEl = null;
let _modalA11yCleanup = null;





// --- modal shell -----------------------------------------------------------

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const el = document.createElement('div');
  el.id = 'applicant-mind-modal';
  // Item #48 (a11y-driven visual fix): `initModalA11y` (called from openApplicantMind)
  // moves focus to the FIRST focusable node inside this element. Without a tabindex
  // here, that node was the Close button (the first <button> in the markup, since the
  // body content loads async) — so Close silently grabbed initial focus and picked up
  // the shared system-blue focus-visible ring on every open, reading as the one
  // primary CTA even though it's a dismiss. Giving the dialog itself a tabindex makes
  // IT the first focusable node instead — a neutral outline on the panel, not a
  // colored ring on Close.
  el.style.cssText = 'position:fixed;inset:0;z-index:1200;display:none;align-items:center;'
    + 'justify-content:center;background:rgba(0,0,0,0.45);';
  el.innerHTML = `
    <div class="admin-card" role="dialog" aria-modal="true" aria-label="What the assistant remembers"
         tabindex="0"
         style="width:min(720px,94vw);max-height:88vh;overflow:auto;padding:18px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <h3 style="margin:0;font-size:16px;">What the assistant remembers</h3>
        <button type="button" class="cal-btn applicant-mind-close" aria-label="Close" title="Close">Close</button>
      </div>
      <div class="applicant-mind-body" style="font-size:13px;max-width:66ch;margin:0 auto;"></div>
    </div>`;
  document.body.appendChild(el);
  el.addEventListener('click', (ev) => { if (ev.target === el) _close(); });
  el.querySelector('.applicant-mind-close').addEventListener('click', _close);
  _modalEl = el;
  return el;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) _modalEl.style.display = 'none';
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('mind');
}

// Exported so other modules/tests can close Mind without reaching into its
// private state, mirroring openApplicantMind's public export.
export function closeApplicantMind() {
  _close();
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
  // Each line carries a stable ref so its "Forget" button can target exactly it.
  const line = (e) => `
    <li class="memory-item" data-mem-ref="${esc(e.ref || '')}" data-mem-text="${esc(e.text)}"
        style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;
        list-style:none;margin:4px 0;padding:2px 0;">
      <span style="flex:1;">${esc(e.text)}</span>
      <button type="button" class="cal-btn applicant-mind-forget"
          data-ref="${esc(e.ref || '')}" data-text="${esc(e.text)}"
          title="Ask the assistant to forget this"
          style="font-size:11px;opacity:0.85;">Forget</button>
    </li>`;
  const block = (title, items, hint) => {
    const body = items.length
      ? `<ul style="margin:6px 0 0;padding-left:0;">${items.map(line).join('')}</ul>`
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
    <li class="memory-item og-card applicant-mind-skill" data-skill="${esc(s.name)}" tabindex="0"
        role="button" title="Open this playbook"
        style="border:1px solid var(--border,#3334);border-radius:8px;
        padding:8px 10px;margin:6px 0;cursor:pointer;">
      <div style="font-weight:600;">${esc(s.name)}</div>
      <div style="opacity:0.85;">${esc(s.description || '')}</div>
      ${s.when_to_use ? `<div style="opacity:0.7;margin-top:2px;">When: ${esc(s.when_to_use)}</div>` : ''}
      <div class="applicant-mind-skill-body" style="display:none;margin-top:8px;"></div>
    </li>`).join('') + `</ul>`;
}

function _renderSkillBody(skill) {
  const list = (title, arr) => {
    const items = (arr || []).filter(Boolean);
    if (!items.length) return '';
    return `<div style="margin-top:6px;"><div style="font-weight:600;">${esc(title)}</div>
      <ul style="margin:4px 0 0;padding-left:18px;">${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
  };
  const when = skill.when_to_use
    ? `<div style="margin-top:6px;"><span style="font-weight:600;">When to use:</span> ${esc(skill.when_to_use)}</div>`
    : '';
  const body = when + list('Procedure', skill.procedure)
    + list('Pitfalls', skill.pitfalls) + list('How I check it worked', skill.verification);
  return body || `<div style="opacity:0.7;">No further detail saved for this playbook yet.</div>`;
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
    return `<li class="memory-item og-card" data-proposal-id="${esc(p.id)}"
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

function _wireForgetButtons() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-forget').forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      const text = btn.dataset.text || '';
      // Confirm first — a forget is a real change to what I remember.
      const ok = window.confirm(`Forget this note?\n\n${text}`);
      if (!ok) return;
      btn.disabled = true;
      try {
        const ref = btn.dataset.ref || '';
        const payload = ref ? { ref } : { text };
        const res = await _fetchJSON(`${API}/forget`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        // Honest feedback: the engine may apply now or stage for approval.
        _toast(res && res.staged
          ? 'Sent to your review queue — approve it to forget this.'
          : 'Forgotten.');
        await openApplicantMind();
      } catch (e) {
        _toast(e.message || 'Could not forget that.');
        btn.disabled = false;
      }
    });
  });
}

function _wireSkillRows() {
  const body = _body();
  body.querySelectorAll('.applicant-mind-skill').forEach((row) => {
    const open = async () => {
      const slot = row.querySelector('.applicant-mind-skill-body');
      if (!slot) return;
      // Toggle: collapse if already open.
      if (slot.style.display !== 'none' && slot.dataset.loaded === '1') {
        slot.style.display = 'none';
        return;
      }
      if (slot.dataset.loaded === '1') { slot.style.display = 'block'; return; }
      slot.style.display = 'block';
      slot.innerHTML = '<div style="opacity:0.7;">Loading…</div>';
      try {
        const skill = await _fetchJSON(`${API}/skills/${encodeURIComponent(row.dataset.skill)}`);
        slot.innerHTML = _renderSkillBody(skill);
        slot.dataset.loaded = '1';
      } catch (e) {
        slot.innerHTML = `<div style="opacity:0.7;">${esc(e.message || 'Could not open that playbook.')}</div>`;
      }
    };
    row.addEventListener('click', open);
    row.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); open(); }
    });
  });
}

// --- open ------------------------------------------------------------------

export async function openApplicantMind(opts) {
  const el = _ensureModalEl();
  el.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('mind');
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(el, _close);
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
        <!-- Item #62: was "What the assistant remembers" again — the dialog's own
             title already says that; this inner section needs its own, distinct
             label rather than repeating the header. -->
        <h4 style="margin:0 0 6px;">Memory</h4>
        ${_renderMemory(snap)}
      </div>
      <div class="memory-section">
        <h4 style="margin:0 0 6px;">Saved playbooks</h4>
        ${_renderSkills(skills)}
      </div>`;
    _wireCurationButtons();
    _wireForgetButtons();
    _wireSkillRows();
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

// Hash routing (audit #7): '#mind' deep-links straight into "What the
// assistant remembers" — a refresh/shared-link/back-forward on that hash
// opens/closes it. Registered at module-eval time (runs as soon as app.js's
// dynamic import resolves, well before app.js calls
// hashRouter.initHashRouting()).
registerRoute('mind', { open: openApplicantMind, close: _close });

const applicantMindModule = { openApplicantMind, closeApplicantMind };
try { window.applicantMindModule = applicantMindModule; } catch { /* no-op */ }

export default applicantMindModule;
