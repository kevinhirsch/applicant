// static/js/applicantCapabilities.js
//
// "What the assistant can do" capability list (dark-engine audit item 24:
// "MCP tool surface is entirely undocumented product capability"). The engine
// exposes a native, read-only MCP tool surface
// (src/applicant/app/routers/mcp.py, GET /mcp/tools) advertising the exact
// tools the agent (and any external MCP client) can call -- but the owner
// never saw what the assistant can actually do. This module surfaces that
// SAME list, proxied read-only through routes/applicant_capabilities_routes.py
// (GET /api/applicant/capabilities), as a plain-language overlay.
//
// Never fabricates a tool: it renders exactly what the engine's own list
// returns (today: list your campaigns, list your stored facts, list your
// applications, list pending actions, and a health check -- all read-only;
// consequential actions like final-submit are deliberately absent from the
// engine's list and so can never appear here). If the engine's tool surface
// changes, this list changes with it.
//
// ADDITIVE and self-contained, mirroring applicantShortcuts.js's own precedent
// (an overlay reached via a self-boot trigger, no nav/index.html markup
// beyond the one required <script> tag):
//
//   - Does NOT edit app.js, index.html (beyond its own <script> tag), or any
//     other applicant*.js module. It builds its own trigger AND its own modal
//     DOM node lazily, appended to document.body -- the same
//     `_ensureModalEl()` + `document.body.appendChild` pattern every other
//     applicant*.js surface uses.
//   - Reuses the shared `.modal` / `.modal-content` / `.ow-window` /
//     `.modal-header` / `.modal-body` / `.admin-card` / `.cal-btn` chrome
//     from style.css -- no new CSS added anywhere.
//   - Trigger: a small floating launcher button (bottom-left, out of the way
//     of the existing bottom-right toast/status stack) so the capability list
//     is discoverable by click, not just a hotkey -- reachability shouldn't
//     depend on a user already knowing a keybind for a first-run disclosure
//     surface. Also bound to a bare `Ctrl+Shift+?` chord for keyboard parity
//     with the rest of the power-user surfaces (commandPalette.js /
//     applicantShortcuts.js), ignored while typing in an editable field.

import { esc, _fetchJSON, loadingHTML, errorHTML, wireRetry } from './applicantCore.js';

const CLOSE_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

function _isEditableTarget(target) {
  if (!target) return false;
  const tag = (target.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || !!target.isContentEditable;
}

// #110/#111: the engine's tool surface intentionally uses plain machine
// identifiers ("list_campaigns") and its own stock description ("List all
// campaigns.", predating this product's "job search" wording) -- fine for an
// MCP client, unreadable for the owner looking at this overlay. This is a
// presentation-only relabeling: it still renders every tool the proxy
// actually returned (see the module doc's "never fabricates" contract),
// just with a plain-language name/description instead of the raw id. A
// tool name outside this map (a future engine addition) still renders --
// humanized rather than dropped — so nothing here can hide a real tool.
const FRIENDLY_TOOL_LABELS = {
  list_campaigns: { label: 'Look up your job searches', desc: 'Lists your job searches and where each one stands.' },
  get_attributes: { label: 'Look up your saved details', desc: 'Lists the facts I have on file about you — name, skills, and the rest of your profile.' },
  get_applications: { label: 'Look up your applications', desc: 'Lists your applications and their current status.' },
  get_pending_actions: { label: 'Look up what needs your attention', desc: 'Lists the open items waiting on your review.' },
  health: { label: 'Check that I’m running', desc: 'Confirms the assistant is up and responding.' },
};

function _humanizeToolName(name) {
  return String(name || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function _rowHTML(tool) {
  const rawName = tool.name || '';
  const friendly = FRIENDLY_TOOL_LABELS[rawName];
  const name = esc(friendly ? friendly.label : _humanizeToolName(rawName));
  const desc = esc((friendly && friendly.desc) || tool.description || '');
  return `<div class="admin-card applicant-capabilities-row" style="padding:10px 12px;margin-bottom:8px;">
    <div style="font-weight:600;">${name}</div>
    ${desc ? `<div style="margin-top:4px;font-size:12px;opacity:0.8;">${desc}</div>` : ''}
  </div>`;
}

function _bodyHTML(tools) {
  if (!tools.length) {
    return `<div class="applicant-empty" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">
      <div style="font-weight:600;color:var(--fg);">Nothing to show yet</div>
      <div style="margin-top:6px;font-size:12px;">The assistant hasn't advertised any tools yet.</div>
    </div>`;
  }
  return `<div style="margin-bottom:10px;font-size:12px;opacity:0.75;">These are the read-only things the assistant can look up on your behalf. Any consequential action — like submitting an application — always goes through your review and approval first.</div>`
    + tools.map(_rowHTML).join('');
}

// ── State ────────────────────────────────────────────────────────────────

let _modalEl = null;
let _modalA11yCleanup = null;
let _triggerEl = null;

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-capabilities-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'What the assistant can do');
  modal.innerHTML = `
    <div class="modal-content ow-window" style="--window-w:460px;display:flex;flex-direction:column;max-height:74vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 2-3 4"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          What the assistant can do
        </h4>
        <button class="close-btn" id="applicant-capabilities-close" title="Close" aria-label="Close">${CLOSE_SVG}</button>
      </div>
      <div class="modal-body" id="applicant-capabilities-list" style="flex:1;overflow-y:auto;padding:10px 14px 14px;"></div>
    </div>`;
  document.body.appendChild(modal);

  modal.querySelector('#applicant-capabilities-close').addEventListener('click', closeApplicantCapabilities);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeApplicantCapabilities(); });

  _modalEl = modal;
  return modal;
}

async function _render() {
  const list = document.getElementById('applicant-capabilities-list');
  if (!list) return;
  list.innerHTML = loadingHTML('Checking what the assistant can do…');
  try {
    const data = await _fetchJSON('/api/applicant/capabilities');
    if (data && data.gated) {
      list.innerHTML = `<div class="applicant-gated" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">
        <div style="font-weight:600;color:var(--fg);">Not set up yet</div>
        <div style="margin-top:6px;font-size:12px;">${esc(data.message || 'Connect an AI model first to see what the assistant can do.')}</div>
      </div>`;
      return;
    }
    if (data && data.engine_available === false) {
      list.innerHTML = errorHTML('Can’t reach the assistant right now.');
      wireRetry(list, _render);
      return;
    }
    const tools = Array.isArray(data && data.tools) ? data.tools : [];
    list.innerHTML = _bodyHTML(tools);
  } catch (err) {
    list.innerHTML = errorHTML((err && err.message) || 'Something went wrong.');
    wireRetry(list, _render);
  }
}

function _ensureTriggerEl() {
  if (_triggerEl) return _triggerEl;
  const btn = document.createElement('button');
  btn.id = 'applicant-capabilities-trigger';
  btn.type = 'button';
  btn.className = 'cal-btn';
  btn.title = 'What can the assistant do?';
  btn.setAttribute('aria-label', 'What can the assistant do?');
  // #31: bottom-left put this pill directly over the sidebar's own bottom-left
  // user bar (avatar/name), covering it and intercepting clicks meant for it,
  // on any sidebar width (full, resized, or collapsed to the icon rail).
  // Bottom-right mirrors the top-right toast corner and stays clear of the
  // sidebar at every width.
  btn.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:850;border-radius:999px;width:auto;padding:0 14px;box-shadow:0 4px 12px rgba(0,0,0,0.25);';
  btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 2-3 4"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Assistant can…';
  btn.addEventListener('click', () => toggleApplicantCapabilities());
  document.body.appendChild(btn);
  _triggerEl = btn;
  return btn;
}

// ── Public open/close/toggle ────────────────────────────────────────────

export function openApplicantCapabilities() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  _render();
  if (_modalA11yCleanup) _modalA11yCleanup();
  try {
    if (window.uiModule && typeof window.uiModule.initModalA11y === 'function') {
      _modalA11yCleanup = window.uiModule.initModalA11y(modal, closeApplicantCapabilities);
    }
  } catch (_) { /* no-op — degrade to a plain open with no focus trap */ }
}

export function closeApplicantCapabilities() {
  if (!_modalEl || _modalEl.classList.contains('hidden')) return;
  _modalEl.classList.add('hidden');
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
}

export function isApplicantCapabilitiesOpen() {
  return !!(_modalEl && !_modalEl.classList.contains('hidden'));
}

export function toggleApplicantCapabilities() {
  if (isApplicantCapabilitiesOpen()) closeApplicantCapabilities();
  else openApplicantCapabilities();
}

// ── Self-boot: floating trigger + keyboard chord ────────────────────────
// The trigger button is injected once the DOM is ready (no index.html markup
// needed). A `Ctrl+Shift+/` chord (reads as "Ctrl+Shift+?" on most keyboard
// layouts, mirroring the bare `?` used by applicantShortcuts.js for the
// power-user shortcuts overlay) offers keyboard-only parity, ignored while
// typing in an editable field.
function _boot() {
  _ensureTriggerEl();
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot, { once: true });
} else {
  _boot();
}

document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey) || !e.shiftKey) return;
  if (e.key !== '/' && e.key !== '?') return;
  if (_isEditableTarget(e.target)) return;
  e.preventDefault();
  toggleApplicantCapabilities();
});

const applicantCapabilitiesModule = {
  openApplicantCapabilities, closeApplicantCapabilities,
  isApplicantCapabilitiesOpen, toggleApplicantCapabilities,
};
try { window.applicantCapabilitiesModule = applicantCapabilitiesModule; } catch (_) { /* no-op */ }

export default applicantCapabilitiesModule;
