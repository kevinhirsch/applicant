// static/js/applicantShortcuts.js
//
// Global keyboard-shortcuts help overlay — design-audit
// docs/design/audits/exhaustive2/07_power_users.md #36 ("A global '?'
// shortcuts cheat-sheet"): "Only the image editor has a shortcuts overlay
// (static/js/editor/keyboard-shortcuts.js); the global, customizable map has
// zero discoverability. A '?' overlay rendered *from* the live keybind map
// (so custom binds show correctly) is the standard affordance."
//
// ADDITIVE and self-contained, mirroring commandPalette.js's own precedent
// (docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md backlog item, see
// workspace/tests/test_applicant_backlog_commandpalette.py):
//
//   - Does NOT edit keyboard-shortcuts.js, settings.js, commandPalette.js,
//     app.js, or index.html beyond the one required <script> tag. It only
//     READS the globals those files already publish at runtime:
//       * `window._applicantKeybinds` — the live (defaults + user-saved)
//         keybind map keyboard-shortcuts.js's initKeyboardShortcuts()
//         assigns (workspace/static/js/keyboard-shortcuts.js:50,55) — so a
//         custom rebind saved in Settings shows up here automatically.
//       * `window.__galleryEditLive` — the flag galleryEditor.js flips
//         true/false around its own image-editor session
//         (workspace/static/js/galleryEditor.js:3505,3781). Used only to
//         suppress OUR overlay while the editor's own '?' cheatsheet
//         (editor/keyboard-shortcuts.js:71, gated on `state.editorOpen`) is
//         showing, so the two never both pop for one keypress.
//       * `window.uiModule.initModalA11y` — the shared focus-trap +
//         Escape-arbitration helper every other modal already uses
//         (ui.js:968), reused here instead of re-implementing focus
//         trapping. Degrades to a bare open/close if `uiModule` isn't on
//         `window` yet (defensive only — it always is once app.js boots).
//   - Self-boots: wires its own module-level `document.addEventListener
//     ('keydown', ...)` at import time, exactly like commandPalette.js and
//     keyboard-shortcuts.js already do — no init-function call from app.js
//     needed.
//   - Builds its own modal DOM node lazily on first open (same
//     `_ensureModalEl()` + `document.body.appendChild` pattern every other
//     applicant*.js / commandPalette.js surface uses) instead of requiring
//     markup in index.html.
//   - Reuses the shared `.modal` / `.modal-content` / `.ow-window` / `.modal-
//     header` / `.modal-body` / `.admin-card` chrome from style.css — no new
//     CSS added anywhere. Those classes' own `@media
//     (prefers-reduced-motion: reduce)` rules (style.css has ~30 of them)
//     apply automatically; no separate motion handling is needed here.
//
// Trigger key: `?` (bare, no modifier — matches the editor's own convention
// at editor/keyboard-shortcuts.js:71). Checked against every OTHER
// global-keydown listener in static/js before picking it (keyboard-
// shortcuts.js's `_defaultKeybinds`, settings.js's `SHORTCUT_DEFAULTS`,
// commandPalette.js's Ctrl+Shift+P) — nothing else in the workspace binds a
// bare `?`, so this is a genuinely free key, and `?` reads as "help" without
// a legend (the same reasoning commandPalette.js's own header comment gives
// for choosing Ctrl+Shift+P). Ignored whenever the event target is an
// editable field (input/textarea/contentEditable) so a user typing a
// question mark into chat, a redline note, or any other field never
// triggers it — mirrors `_isEditableTarget` from commandPalette.js and the
// INPUT/TEXTAREA check in editor/keyboard-shortcuts.js.

function _isEditableTarget(target) {
  if (!target) return false;
  const tag = (target.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || !!target.isContentEditable;
}

const CLOSE_SVG = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

function _esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Fallback copy of keyboard-shortcuts.js's own `_defaultKeybinds` (that
// module keeps it module-private, i.e. not exported), used ONLY if
// `window._applicantKeybinds` hasn't been populated yet (defensive — by the
// time a user can press `?` the page has long finished booting and
// app.js's initKeyboardShortcuts() call has already set the real map; this
// exists so the overlay still renders something sensible rather than
// nothing if that ordering assumption is ever wrong). The live global is
// always preferred so a user's own rebinds show correctly, per the audit's
// own requirement.
const _FALLBACK_KEYBINDS = {
  search: 'ctrl+k', toggle_sidebar: 'ctrl+alt+b', new_session: 'ctrl+alt+n',
  fav_session: 'ctrl+alt+f', delete_session: 'ctrl+alt+d',
  cancel: 'escape', tts: 'alt+shift+t',
  settings: 'ctrl+,', focus_input: 'ctrl+/',
  open_calendar: 'ctrl+alt+c', open_compare: '', open_cookbook: '',
  open_research: '', open_gallery: '', open_library: '', open_memory: '',
  open_notes: '', open_tasks: '', open_theme: '',
};

// Friendly labels, mirroring settings.js's own (module-private, not
// exported) SHORTCUT_LABELS so the same action reads with the same name in
// both the Settings editor and this cheat-sheet.
const _LABELS = {
  search: 'Search conversations', toggle_sidebar: 'Toggle sidebar',
  new_session: 'New session', fav_session: 'Favorite session',
  delete_session: 'Delete session', cancel: 'Cancel / close',
  tts: 'Play/stop TTS', settings: 'Toggle window',
  focus_input: 'Focus chat input', open_calendar: 'Open Calendar',
  open_compare: 'Open Compare', open_cookbook: 'Open Cookbook',
  open_research: 'Open Deep Research', open_gallery: 'Open Gallery',
  open_library: 'Open Library', open_memory: 'Open Memory',
  open_notes: 'Open Notes', open_tasks: 'Open Tasks', open_theme: 'Open Theme',
};

const _CATEGORIES = [
  { name: 'Navigation', keys: ['search', 'toggle_sidebar', 'focus_input', 'settings', 'cancel'] },
  { name: 'Sessions', keys: ['new_session', 'fav_session', 'delete_session'] },
  { name: 'Tools', keys: ['tts'] },
  { name: 'Open a tool', keys: ['open_calendar', 'open_compare', 'open_cookbook', 'open_research', 'open_gallery', 'open_library', 'open_memory', 'open_notes', 'open_tasks', 'open_theme'] },
];

function _formatCombo(combo) {
  if (!combo) return '';
  return combo.split('+').map((part) => {
    if (part === 'ctrl') return 'Ctrl';
    if (part === 'alt') return 'Alt';
    if (part === 'shift') return 'Shift';
    if (part === 'escape') return 'Esc';
    if (part.length === 1) return part.toUpperCase();
    return part.charAt(0).toUpperCase() + part.slice(1);
  }).join('+');
}

function _liveKeybinds() {
  const live = (typeof window !== 'undefined' && window._applicantKeybinds) || null;
  return { ..._FALLBACK_KEYBINDS, ...(live || {}) };
}

// Mirrors settings.js's own OPEN_TOOL_NAV_IDS / _toolShortcutIsReachable.
// #107: a few "Open X" actions target tools this deployment doesn't surface
// in the nav (Cookbook/Notes/Tasks/Theme are hidden via `style="display:
// none"` in index.html). Most are already dropped by the "only show bound
// combos" filter below since they default unbound, but if a user ever did
// bind one, this keeps it out of the cheat-sheet too rather than pointing
// at something unreachable. Checked live against the DOM, not a hardcoded
// list, so it can't drift from what the nav actually shows.
const _OPEN_TOOL_NAV_IDS = {
  open_calendar: 'tool-calendar-btn', open_compare: 'tool-compare-btn',
  open_cookbook: 'tool-cookbook-btn', open_research: 'tool-research-btn',
  open_gallery: 'tool-gallery-btn', open_library: 'tool-library-btn',
  open_memory: 'tool-memory-btn', open_notes: 'tool-notes-btn',
  open_tasks: 'tool-tasks-btn', open_theme: 'tool-theme-btn',
};

function _toolShortcutIsReachable(action) {
  const navId = _OPEN_TOOL_NAV_IDS[action];
  if (!navId) return true;
  const btn = typeof document !== 'undefined' && document.getElementById(navId);
  if (!btn) return false;
  try { return getComputedStyle(btn).display !== 'none'; } catch { return true; }
}

function _rowHTML(action, combo) {
  const label = _LABELS[action] || action;
  const display = _formatCombo(combo);
  return `<div class="admin-card applicant-shortcuts-row" style="display:flex;align-items:center;justify-content:space-between;padding:6px 12px;margin-bottom:4px;">
    <span>${_esc(label)}</span>
    <kbd style="font-family:inherit;font-size:12px;padding:2px 8px;border-radius:6px;border:1px solid var(--border,#3334);background:var(--bg-input,var(--bg));white-space:nowrap;">${_esc(display)}</kbd>
  </div>`;
}

function _sectionHTML(name, rowsHTML) {
  if (!rowsHTML) return '';
  return `<div class="applicant-shortcuts-section" style="margin-bottom:14px;">
    <div class="admin-toggle-sub" style="opacity:0.7;padding:2px 4px 6px;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:0.03em;">${_esc(name)}</div>
    ${rowsHTML}
  </div>`;
}

function _buildBodyHTML() {
  const kb = _liveKeybinds();
  const categorySections = _CATEGORIES.map((cat) => {
    const rows = cat.keys
      .filter((k) => kb[k]) // only show bound combos — unbound (empty) actions have no shortcut to show
      .filter(_toolShortcutIsReachable) // #107: never advertise a bound key for a tool that isn't in the nav
      .map((k) => _rowHTML(k, kb[k]))
      .join('');
    return _sectionHTML(cat.name, rows);
  }).join('');
  const alwaysOn = _sectionHTML('This help', [
    _rowHTML('__help_toggle', '?'),
    _rowHTML('__help_palette', 'ctrl+shift+p'),
    _rowHTML('__help_close', 'escape'),
  ].join(''));
  return categorySections + alwaysOn;
}

// _LABELS lookup fallback for the three synthetic "always on" rows above,
// which aren't real keybind-map actions (they're fixed, non-rebindable
// chords owned by this file and commandPalette.js respectively).
_LABELS.__help_toggle = 'Toggle this shortcuts help';
_LABELS.__help_palette = 'Command palette (jump to a surface)';
_LABELS.__help_close = 'Close this help / any dialog';

// ── State ────────────────────────────────────────────────────────────────

let _modalEl = null;
let _modalA11yCleanup = null;

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-shortcuts-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Keyboard shortcuts');
  modal.innerHTML = `
    <div class="modal-content ow-window" style="--window-w:440px;display:flex;flex-direction:column;max-height:74vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="6" y1="9" x2="6" y2="9"/><line x1="10" y1="9" x2="10" y2="9"/><line x1="14" y1="9" x2="14" y2="9"/><line x1="18" y1="9" x2="18" y2="9"/><line x1="6" y1="13" x2="18" y2="13"/></svg>
          Keyboard shortcuts
        </h4>
        <button class="close-btn" id="applicant-shortcuts-close" title="Close" aria-label="Close">${CLOSE_SVG}</button>
      </div>
      <div class="modal-body" id="applicant-shortcuts-list" style="flex:1;overflow-y:auto;padding:10px 14px 14px;"></div>
    </div>`;
  document.body.appendChild(modal);

  modal.querySelector('#applicant-shortcuts-close').addEventListener('click', closeApplicantShortcuts);
  // Click outside the content box closes — mirrors commandPalette.js's own
  // duplicate of app.js's generic "click outside .modal-content" behavior
  // (this module wires itself independently of app.js, same as that file).
  modal.addEventListener('click', (e) => { if (e.target === modal) closeApplicantShortcuts(); });

  _modalEl = modal;
  return modal;
}

function _render() {
  const list = document.getElementById('applicant-shortcuts-list');
  if (!list) return;
  list.innerHTML = _buildBodyHTML();
}

// ── Public open/close/toggle ────────────────────────────────────────────

export function openApplicantShortcuts() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  _render();
  if (_modalA11yCleanup) _modalA11yCleanup();
  try {
    if (window.uiModule && typeof window.uiModule.initModalA11y === 'function') {
      _modalA11yCleanup = window.uiModule.initModalA11y(modal, closeApplicantShortcuts);
    }
  } catch (_) { /* no-op — degrade to a plain open with no focus trap */ }
}

export function closeApplicantShortcuts() {
  if (!_modalEl || _modalEl.classList.contains('hidden')) return;
  _modalEl.classList.add('hidden');
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
}

export function isApplicantShortcutsOpen() {
  return !!(_modalEl && !_modalEl.classList.contains('hidden'));
}

export function toggleApplicantShortcuts() {
  if (isApplicantShortcutsOpen()) closeApplicantShortcuts();
  else openApplicantShortcuts();
}

// ── Self-boot: wire the trigger key ─────────────────────────────────────
// Module-level listener (runs once, at import time) — no app.js/index.html
// edit needed beyond the one <script> tag. Bare `?`, ignored while typing in
// an editable field, and ignored while the image editor's own cheatsheet
// owns the key (state.editorOpen, mirrored here via the `__galleryEditLive`
// flag it sets) so the two overlays never both respond to one keypress.
document.addEventListener('keydown', (e) => {
  if (e.key !== '?') return;
  if (_isEditableTarget(e.target)) return;
  if (typeof window !== 'undefined' && window.__galleryEditLive) return;
  e.preventDefault();
  toggleApplicantShortcuts();
});

const applicantShortcutsModule = {
  openApplicantShortcuts, closeApplicantShortcuts,
  isApplicantShortcutsOpen, toggleApplicantShortcuts,
};
// Expose for non-module callers / debugging, mirroring the window.applicant*Module pattern.
try { window.applicantShortcutsModule = applicantShortcutsModule; } catch (_) { /* no-op */ }

export default applicantShortcutsModule;
