// static/js/commandPalette.js
//
// Command palette — a single "type a few letters, hit enter" launcher for
// every Applicant surface (Portal, Activity, Debug, Results, Tracker, Vault,
// Remote, Gallery, Mind, Compare, Chat, Update). ADDITIVE and self-contained
// (design-audit ux-flows backlog: "a command palette + keyboard shortcuts for
// the surfaces users live in"):
//
//   - It does NOT edit any of the 12 applicant*.js surface files, app.js, or
//     index.html — it only CALLS the launcher functions those files already
//     export on `window` (grepped from each file's bottom export block; see
//     the per-entry comments below for exactly which global each row calls).
//   - It self-boots: this file wires its own trigger keydown listener at
//     module-eval time (mirrors keyboard-shortcuts.js's module-level
//     `document.addEventListener('keydown', ...)` pattern) instead of
//     requiring app.js to import and call an init function. Importing this
//     file (a plain `import './js/commandPalette.js';` side-effect import,
//     same shape as the existing `import './js/modalManager.js';` /
//     `import './js/tileManager.js';` lines in app.js) is the only wiring a
//     future change would need — nothing here depends on app.js internals.
//   - It builds its own modal DOM node lazily (same `_ensureModalEl()` +
//     `document.body.appendChild` pattern every other applicant*.js surface
//     uses) rather than requiring markup in index.html.
//
// Trigger key: Ctrl+Shift+P (Cmd+Shift+P on Mac). Chosen after checking every
// combo already reserved by the workspace's OWN keybind system
// (static/js/keyboard-shortcuts.js `_defaultKeybinds` + settings.js
// `SHORTCUT_DEFAULTS`, which is what the Settings → Shortcuts panel displays
// and what an earlier round in this session fixed a default/display mismatch
// for): ctrl+k (search), ctrl+alt+b/n/f/d (sidebar/session actions),
// ctrl+alt+c (calendar), ctrl+, (settings), ctrl+/ (focus chat input),
// alt+shift+t (tts), escape (cancel) are ALL taken. Ctrl+Shift+P is free in
// that registry, free in every other static/js/*.js keydown handler (grepped
// for `shiftKey` + `ctrlKey`/`metaKey` combinations before picking it), and is
// the industry-standard "command palette" chord (VS Code, Slack, GitHub) —
// recognizable without a legend. It intentionally does NOT go through
// keyboard-shortcuts.js / SHORTCUT_DEFAULTS (that registry is user-rebindable
// per-action storage tied to `/api/auth/settings`; this palette is a fixed,
// always-on launcher in the same spirit as Ctrl+K's search overlay, which
// also isn't rebindable from that panel beyond its `search` entry). If a
// future pass wants it user-configurable, add a `command_palette` entry to
// both `_defaultKeybinds` and `SHORTCUT_DEFAULTS` and read it here instead of
// the hardcoded check below — that is an additive follow-up, not required for
// this backlog item.

function _el(id) { return document.getElementById(id); }

function _isEditableTarget(target) {
  if (!target) return false;
  const tag = (target.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || target.isContentEditable;
}

/** Call the first argument that is actually a function, with no `this` binding needed
 * (every launcher below is a closure over its own module state, not a method). */
function _callFirst(...fns) {
  for (const fn of fns) {
    if (typeof fn === 'function') { fn(); return true; }
  }
  return false;
}

// ── The surface registry ────────────────────────────────────────────────────
// One entry per already-reachable Applicant surface. `open` tries the
// window.applicantXModule.openApplicantX() form first (present on all 12),
// falling back to the bare window.openApplicantX() alias where a surface also
// exports one (Results, Tracker, Vault, Remote — grepped from each file's
// export block). Keywords are extra, lower-cased search terms beyond the
// label itself so e.g. typing "creds" still finds Vault.
const _SURFACES = [
  {
    id: 'portal', label: 'Portal', keywords: 'pending actions notifications home inbox',
    open: () => _callFirst(
      window.applicantPortalModule && window.applicantPortalModule.openApplicantPortal,
      window.openApplicantPortal,
    ),
  },
  {
    id: 'activity', label: 'Activity', keywords: 'history applications log timeline',
    open: () => _callFirst(
      window.applicantActivityModule && window.applicantActivityModule.openApplicantActivity,
      window.openApplicantActivity,
    ),
  },
  {
    id: 'debug', label: 'Debug', keywords: 'diagnostics ops insights logs variants run controls config activity',
    open: () => _callFirst(
      window.applicantDebugModule && window.applicantDebugModule.openApplicantDebug,
      window.openApplicantDebug,
    ),
  },
  {
    id: 'results', label: 'Results', keywords: 'funnel outcomes learning stats',
    open: () => _callFirst(
      window.applicantResultsModule && window.applicantResultsModule.openApplicantResults,
      window.openApplicantResults,
    ),
  },
  {
    id: 'tracker', label: 'Tracker', keywords: 'post-submission outcomes applied interview offer rejected ghosted',
    open: () => _callFirst(
      window.applicantTrackerModule && window.applicantTrackerModule.openApplicantTracker,
      window.openApplicantTracker,
    ),
  },
  {
    id: 'vault', label: 'Vault', keywords: 'credentials passwords sign-in login accounts',
    open: () => _callFirst(
      window.applicantVaultModule && window.applicantVaultModule.openApplicantVault,
      window.openApplicantVault,
    ),
  },
  {
    id: 'remote', label: 'Remote', keywords: 'live takeover session watch submit',
    open: () => _callFirst(
      window.applicantRemoteModule && window.applicantRemoteModule.openApplicantRemoteSession,
      window.openApplicantRemoteSession,
    ),
  },
  {
    id: 'gallery', label: 'Gallery', keywords: 'screenshots materials drafts',
    open: () => _callFirst(
      window.applicantGalleryModule && window.applicantGalleryModule.openApplicantGallery,
      window.openApplicantGallery,
    ),
  },
  {
    id: 'mind', label: 'Mind', keywords: 'memory playbooks learning what the assistant remembers',
    open: () => _callFirst(
      window.applicantMindModule && window.applicantMindModule.openApplicantMind,
      window.openApplicantMind,
    ),
  },
  {
    id: 'compare', label: 'Compare', keywords: 'diff applications postings side by side',
    open: () => _callFirst(
      window.applicantCompareModule && window.applicantCompareModule.openApplicantCompare,
      window.openApplicantCompare,
    ),
  },
  {
    id: 'chat', label: 'Chat', keywords: 'assistant ask job agent',
    open: () => _callFirst(
      window.applicantChatModule && window.applicantChatModule.openApplicantChat,
      window.openApplicantChat,
    ),
  },
  {
    id: 'update', label: 'Update', keywords: 'upgrade deploy version',
    open: () => _callFirst(
      window.applicantUpdateModule && window.applicantUpdateModule.openApplicantUpdate,
      window.openApplicantUpdate,
    ),
  },
];

// ── State ────────────────────────────────────────────────────────────────────

let _modalEl = null;
let _modalA11yCleanup = null;
let _filtered = _SURFACES.slice();
let _selectedIndex = 0;

const CLOSE_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

function _esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-command-palette-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Command palette — jump to a surface');
  // Reuses the shared modal/window chrome (`.modal` / `.modal-content` from
  // style.css, `.ow-window` AppKit theming per applicantPortal.js's own
  // established `'modal hidden ow-window'` pattern) and `.admin-card` for the
  // list rows — no new visual kit invented for this.
  modal.innerHTML = `
    <div class="modal-content ow-window" style="--window-w:420px;display:flex;flex-direction:column;max-height:70vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          Jump to
        </h4>
        <button class="close-btn" id="applicant-command-palette-close" title="Close" aria-label="Close">${CLOSE_SVG}</button>
      </div>
      <div style="padding:10px 14px 0;">
        <input type="text" id="applicant-command-palette-input" placeholder="Type a surface name…"
          autocomplete="off" spellcheck="false"
          style="width:100%;box-sizing:border-box;font-size:14px;padding:8px 10px;border-radius:8px;border:1px solid var(--border,#3334);background:var(--bg-input,var(--bg));color:var(--fg);outline:none;">
      </div>
      <div class="modal-body" id="applicant-command-palette-list" style="flex:1;overflow-y:auto;padding:10px 14px 14px;"></div>
    </div>`;
  document.body.appendChild(modal);

  modal.querySelector('#applicant-command-palette-close').addEventListener('click', closeCommandPalette);
  // Click outside the content box closes (mirrors app.js's generic
  // "click outside .modal-content dismisses the modal" handler, duplicated
  // here since this module wires itself independently of app.js).
  modal.addEventListener('click', (e) => { if (e.target === modal) closeCommandPalette(); });

  const input = modal.querySelector('#applicant-command-palette-input');
  input.addEventListener('input', () => _applyFilter(input.value));
  input.addEventListener('keydown', _onListKeydown);

  _modalEl = modal;
  return modal;
}

function _rowHTML(surface, index) {
  return `<div class="admin-card applicant-command-palette-row${index === _selectedIndex ? ' selected' : ''}"
      data-index="${index}" data-id="${_esc(surface.id)}" role="option"
      style="cursor:pointer;padding:8px 12px;margin-bottom:4px;display:flex;align-items:center;justify-content:space-between;${index === _selectedIndex ? 'background:var(--accent-soft,var(--bg-hover,#8882));' : ''}">
    <span>${_esc(surface.label)}</span>
  </div>`;
}

function _renderList() {
  const list = _el('applicant-command-palette-list');
  if (!list) return;
  if (!_filtered.length) {
    list.innerHTML = `<div class="admin-toggle-sub" style="opacity:0.7;padding:8px 4px;">No matching surface</div>`;
    return;
  }
  list.innerHTML = _filtered.map((s, i) => _rowHTML(s, i)).join('');
  list.querySelectorAll('.applicant-command-palette-row').forEach((row) => {
    row.addEventListener('click', () => {
      const idx = Number(row.dataset.index);
      _activate(idx);
    });
  });
}

function _matches(surface, needle) {
  if (!needle) return true;
  const hay = (surface.label + ' ' + (surface.keywords || '')).toLowerCase();
  return hay.includes(needle);
}

function _applyFilter(query) {
  const needle = (query || '').trim().toLowerCase();
  _filtered = _SURFACES.filter((s) => _matches(s, needle));
  _selectedIndex = _filtered.length ? 0 : -1;
  _renderList();
}

function _activate(index) {
  const surface = _filtered[index];
  if (!surface) return;
  closeCommandPalette();
  try { surface.open(); } catch (e) { console.error('commandPalette: failed to open surface', surface.id, e); }
}

function _onListKeydown(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (!_filtered.length) return;
    _selectedIndex = Math.min(_selectedIndex + 1, _filtered.length - 1);
    _renderList();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (!_filtered.length) return;
    _selectedIndex = Math.max(_selectedIndex - 1, 0);
    _renderList();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    _activate(_selectedIndex);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeCommandPalette();
  }
}

// ── Public open/close/toggle ────────────────────────────────────────────────

export function openCommandPalette() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  _filtered = _SURFACES.slice();
  _selectedIndex = 0;
  _renderList();
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Reuse the workspace's shared modal a11y helper (focus trap + Escape
  // arbitration against any other open overlay) when available; degrade to a
  // plain focus() if ui.js isn't reachable for some reason (defensive only —
  // it always is once app.js has booted).
  try {
    if (window.uiModule && typeof window.uiModule.initModalA11y === 'function') {
      _modalA11yCleanup = window.uiModule.initModalA11y(modal, closeCommandPalette);
    }
  } catch (_) { /* no-op */ }
  const input = _el('applicant-command-palette-input');
  if (input) {
    input.value = '';
    input.focus();
  }
}

export function closeCommandPalette() {
  if (!_modalEl || _modalEl.classList.contains('hidden')) return;
  _modalEl.classList.add('hidden');
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
}

export function isCommandPaletteOpen() {
  return !!(_modalEl && !_modalEl.classList.contains('hidden'));
}

export function toggleCommandPalette() {
  if (isCommandPaletteOpen()) closeCommandPalette();
  else openCommandPalette();
}

/** Exposed for tests / debugging — the exact surface list this palette knows about. */
export function listSurfaces() {
  return _SURFACES.map((s) => s.id);
}

// ── Self-boot: wire the trigger key ─────────────────────────────────────────
// Module-level listener (runs once, at import time) — no app.js/index.html
// edit needed. Ctrl+Shift+P / Cmd+Shift+P, ignored while typing in a text
// field so it never steals the chord from an editable surface.
document.addEventListener('keydown', (e) => {
  const ctrlOrMeta = e.ctrlKey || e.metaKey;
  if (!ctrlOrMeta || !e.shiftKey || e.altKey) return;
  if ((e.key || '').toLowerCase() !== 'p') return;
  if (_isEditableTarget(e.target)) return;
  e.preventDefault();
  toggleCommandPalette();
});

const commandPaletteModule = {
  openCommandPalette, closeCommandPalette, isCommandPaletteOpen, toggleCommandPalette, listSurfaces,
};
// Expose for non-module callers / debugging, mirroring the window.applicant*Module pattern.
try { window.applicantCommandPaletteModule = commandPaletteModule; } catch (_) { /* no-op */ }

export default commandPaletteModule;
