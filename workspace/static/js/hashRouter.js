// static/js/hashRouter.js
//
// Generic hash-based routing for modal/overlay "surfaces" (audit systemic
// theme #7 — "16 transient modals, zero URL routing, one-way deep-links").
// A surface registers a hash token with an open/close pair; from then on:
//   - loading the page (or refreshing) with that hash present opens it,
//   - the browser back/forward buttons open/close it like a real page,
//   - a shared link containing the hash is copy-pasteable and deep-links in.
//
// This module owns NONE of the actual open/close behavior — it only keeps
// location.hash in sync with a registry the surfaces themselves populate,
// so extending it to another surface is a couple of lines wherever that
// surface already exposes an open()/close() pair (see applicantPortal.js /
// applicantActivity.js for the pattern), no changes needed here.
//
// Existing hash usage this deliberately stays out of the way of:
//   - sessions.js owns bare `#<sessionId>` hashes for the current chat.
//   - emailInbox.js owns the one-shot `#email=<folder>:<uid>` deep link.
// Route tokens registered here (e.g. `portal`, `activity`) are plain words
// that never collide with a session id or the `email=` prefix, and this
// module never touches the hash unless it currently matches a token a
// surface registered — so it can't clobber either of those.

const _routes = new Map(); // token -> { open, close }

function _hashToken() {
  const h = window.location.hash || '';
  return h.startsWith('#') ? h.slice(1) : h;
}

// Sentinel (not a real token) so the very first _applyFromHash() call — run
// from initHashRouting() at boot — always processes whatever hash is
// present, instead of short-circuiting on "nothing changed".
let _lastToken = null;

// One-window-at-a-time (audit #7): the token of the surface currently treated
// as "open" via the click path, so opening another one can close it first
// (surfaces used to stack). Seeded by setActive() (the boot landing) and kept
// current by setHash(). The 'chat' token is transparent to this — the native
// chat pane is a persistent backdrop that is never closed by (and never
// closes) another surface opening over it, so it never becomes _activeToken.
let _activeToken = null;

/**
 * Register a surface under a hash token.
 * @param {string} token - e.g. 'portal' (the hash becomes '#portal').
 * @param {{open: Function, close: Function}} handlers - called with no args.
 */
export function registerRoute(token, { open, close } = {}) {
  if (!token) return;
  _routes.set(token, { open, close });
}

/** True if some surface has registered this token. */
export function hasRoute(token) {
  return _routes.has(token);
}

/**
 * Point location.hash at `token` (adds a history entry, so back navigates
 * away from it). No-op if the hash already matches — avoids piling up
 * redundant history entries when a caller re-confirms an already-open route.
 */
export function setHash(token) {
  if (!token || _hashToken() === token) return;
  // One-window-at-a-time: opening a new surface via the click path closes the
  // previously-active one first (the hashchange path in _applyFromHash already
  // does this for back/forward). 'chat' is exempt in BOTH directions — opening
  // chat never closes the active surface, and chat is never the active surface
  // that gets closed — so the native chat pane coexists with any modal.
  if (token !== 'chat' && _activeToken && _activeToken !== token && _activeToken !== 'chat') {
    const prev = _routes.get(_activeToken);
    if (prev && typeof prev.close === 'function') {
      try { prev.close(); } catch (_) { /* a surface's own close must not break routing */ }
    }
  }
  try {
    history.pushState(null, '', '#' + token);
  } catch (_) {
    window.location.hash = token;
  }
  _lastToken = token;
  if (token !== 'chat') _activeToken = token;
}

/**
 * Seed / update the one-window active token WITHOUT opening or closing
 * anything. Used by the boot landing (which opens its home-base surface with
 * skipHashUpdate, so setHash never runs) so the next click-path open knows
 * which surface to close. No-op semantics for 'chat' are the caller's concern.
 */
export function setActive(token) {
  _activeToken = token || null;
}

/**
 * Clear location.hash, but ONLY if it currently belongs to `token` — never
 * clobbers an unrelated hash (a session id, an in-flight `#email=` deep
 * link, or a different registered route that already took over).
 */
export function clearHash(token) {
  if (!token || _hashToken() !== token) return;
  try {
    history.pushState(null, '', window.location.pathname + window.location.search);
  } catch (_) { /* no-op — worst case the stale token lingers in the URL */ }
  if (_lastToken === token) _lastToken = '';
}

/** The current hash, without the leading '#'. */
export function currentHashToken() {
  return _hashToken();
}

/**
 * Re-sync the change detector to whatever the hash is RIGHT NOW, without
 * opening or closing anything. For a surface that hands its token over to a
 * different hash owner after opening — e.g. the Job Assistant's '#chat'
 * deep link resolves into the native chat's '#<sessionId>' hash via
 * history.replaceState, which never fires hashchange. Without this the
 * router still believes the surface's token is current, so the NEXT
 * navigation to that same token short-circuits as "nothing changed" and
 * the deep link goes dead.
 */
export function syncToken() {
  _lastToken = _hashToken();
}

function _applyFromHash() {
  const token = _hashToken();
  if (token === _lastToken) return;
  const prev = _routes.get(_lastToken);
  _lastToken = token;
  if (prev && typeof prev.close === 'function') {
    try { prev.close(); } catch (_) { /* surface's own close should never throw, but don't let routing break on it */ }
  }
  const route = _routes.get(token);
  if (route && typeof route.open === 'function') {
    try { route.open(); } catch (_) { /* same — routing keeps working even if one surface's open() fails */ }
  }
}

let _initialized = false;

/**
 * Start listening for hashchange (covers back/forward and manual hash
 * edits) and apply whatever hash is present right now (covers a deep link
 * or a refresh landing on an already-hashed URL). Idempotent — safe to call
 * from multiple surfaces' boot sequences; only the first call does anything.
 */
export function initHashRouting() {
  if (_initialized) return;
  _initialized = true;
  window.addEventListener('hashchange', _applyFromHash);
  _applyFromHash();
}

const hashRouterModule = {
  registerRoute, hasRoute, setHash, clearHash, currentHashToken, syncToken, initHashRouting, setActive,
};
// Expose for non-module callers / debugging, mirroring the window.applicant*Module pattern.
try { window.applicantHashRouter = hashRouterModule; } catch (_) { /* no-op */ }

export default hashRouterModule;
