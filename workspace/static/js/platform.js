// ============================================
// Platform detection + AltGr-keystroke helper
// ============================================
// Shared by the keybind code: root keyboard-shortcuts.js, the editor's
// keyboard-shortcuts.js, and settings.js. Single source of truth so the three
// guards can't drift.

// AltGr (right Alt on AZERTY/QWERTZ and most non-US layouts, used to type
// @ # { } [ ] | \ and €) is reported by browsers as Ctrl+Alt. macOS is the
// exception: there the Option key — a normal part of Mac shortcuts — also sets
// the AltGraph modifier state, so it must NOT be treated as AltGr.
//
// IS_MAC covers all Apple platforms, iPad/iPhone included: a Magic Keyboard's
// Option key sets AltGraph exactly like a Mac's, so they need the same carve-out
// — narrowing to macOS-only would re-break them. The name and the
// /Mac|iPhone|iPad/ test deliberately mirror the existing isMac checks in
// calendar.js and sessions.js; this is their single shared source of truth.
export const IS_MAC =
  /Mac|iPhone|iPad/.test((typeof navigator !== 'undefined' && navigator.platform) || '') ||
  /Mac/.test((typeof navigator !== 'undefined' && navigator.userAgent) || '');

// True when `e` is an AltGr keystroke we should ignore for Ctrl+Alt shortcut
// purposes. getModifierState('AltGraph') is true for AltGr but false for a
// genuine left Ctrl+Alt, so real shortcuts still work. Always false on macOS,
// where Option legitimately sets AltGraph.
//
// We also require ctrlKey+altKey: the collision we defend against is precisely
// "AltGr reported AS Ctrl+Alt", so an event that asserts AltGraph WITHOUT
// presenting as Ctrl+Alt (a Linux ISO_Level3_Shift layout, a stray modifier
// state) is left alone instead of being swallowed.
//
// Trade-off: on Windows AltGr *is* Ctrl+right-Alt, so a deliberate
// Ctrl+Alt+<char> shortcut typed via AltGr is unreachable too — accepted; use
// the left Ctrl+Alt.
//
// NOTE: the AltGr -> AltGraph mapping is taken from the UI Events spec / MDN,
// not proven by our tests. Older Firefox and some Linux setups historically did
// not report AltGraph; where a browser sets ctrlKey+altKey without it this
// guard is simply a no-op (the pre-fix behaviour) rather than a regression.
export function isAltGrEvent(e, isMac = IS_MAC) {
  return (
    !isMac &&
    !!e.ctrlKey &&
    !!e.altKey &&
    !!(e.getModifierState && e.getModifierState('AltGraph'))
  );
}

// ============================================
// Viewport mode (Stream S / ruling #16)
// ============================================
// THE one source of truth for "are we in the narrow (sheet) layout?". The app
// previously compared window.innerWidth to 768 in four different ways across
// 15 files — at exactly 768px modules disagreed which mode they were in. All
// width-mode checks now go through these matchMedia-backed helpers; the FE
// lint gate (tests/test_s_responsive_mechanism.py) bans literal innerWidth
// threshold comparisons anywhere else. The thresholds are the breakpoint
// tokens in static/css/responsive-tokens.css.

const NARROW_QUERY = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(max-width: 768px)') : { matches: false, addEventListener() {} };
const BELOW_MEDIUM_QUERY = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(max-width: 1024px)') : { matches: false, addEventListener() {} };

/** ≤768px — the narrow/sheet boundary (--bp-narrow). */
export function isNarrow() { return NARROW_QUERY.matches; }

/** ≤1024px — below the medium boundary (--bp-medium). */
export function isBelowMedium() { return BELOW_MEDIUM_QUERY.matches; }

/** Subscribe to narrow-mode flips (preferred over per-resize innerWidth reads). */
export function onNarrowChange(fn) {
  NARROW_QUERY.addEventListener('change', fn);
}

// ============================================
// Game freshness (Lane G15)
// ============================================
// THE one dispatcher for `appkit:gamechanged`. The game panels (status HUD,
// social, cast, finale, diary gate, engine banner, decision re-arm) already
// subscribe; what they lacked was a dispatcher at every mutation seam — the
// only inline dispatch was unreachable, so post-action UI waited out a
// 20–30s poll ("the sidebar is behind"). Every FE path that mutates engine
// game state calls this helper instead of dispatching ad hoc.
//
// Trailing debounce (~250ms): one agent turn can advance, record, and decide
// back-to-back, so a burst of tool results coalesces into ONE refresh wave.
// Exposed on window so classic-script surfaces and module code share the same
// seam without import coupling; `detail.reason` (the last trigger) is debug
// breadcrumb only — listeners must not branch on it.
const GAMECHANGED_DEBOUNCE_MS = 250;
let _gameChangedTimer = null;

export function appkitGameChanged(reason) {
  if (_gameChangedTimer) clearTimeout(_gameChangedTimer);
  _gameChangedTimer = setTimeout(() => {
    _gameChangedTimer = null;
    try {
      window.dispatchEvent(new CustomEvent('appkit:gamechanged', { detail: { reason: String(reason || '') } }));
    } catch (_) { /* fail open — every panel keeps its poll fallback */ }
  }, GAMECHANGED_DEBOUNCE_MS);
}

if (typeof window !== 'undefined') window.appkitGameChanged = appkitGameChanged;

// #570: a backgrounded tab misses cross-device game-updated server pushes (the panels' polls are
// gated on `!document.hidden`, and the server-push reconcile may be dropped while hidden), so it
// can sit stale for a whole poll cycle after the user returns. When the tab REGAINS visibility,
// route a reconcile through THE single dispatcher (never an ad-hoc `appkit:gamechanged`) so every
// game panel refreshes immediately — catching up on anything that changed while we were away. The
// helper is debounced + fail-open, and a no-op outside the game build (no panels listening).
if (typeof document !== 'undefined' && document.addEventListener) {
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      try { appkitGameChanged('tab-visible'); } catch (_) { /* fail open */ }
    }
  });
}

// ============================================
// Haptics + audio beat channel (issue #745)
// ============================================
// Side-effect import: haptics module self-registers its window listeners and rides
// the `appkit:gamechanged` reason this module dispatches above (crown / noms /
// veto / eviction / decision-confirm) to fire a sub-second vibrate + audio cue.
// Imported HERE — at the dispatcher hub, which is always loaded — so no
// index.html script tag is needed. Vault-free (reads only the public beat
// reason), gated behind a user setting + prefers-reduced-motion, fail-soft.
