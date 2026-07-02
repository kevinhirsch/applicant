// static/js/lazyLaunch.js
//
// Perf audit (docs/design/audits/exhaustive2/03_performance.md, exhaustive2
// lens 03, finding #2 — "~47 eagerly loaded module scripts on every boot,
// including 400KB+ modules for rare surfaces"): applicantDebug.js,
// applicantGallery.js, and applicantCompare.js used to be eager
// `<script type="module">` tags in index.html, so their combined weight
// downloaded on EVERY boot even though each is a genuinely rare surface —
// reached only via an explicit launcher click (Activity/Debug, Application
// Gallery, Compare in the sidebar/rail) or a shared `#debug` / `#gallery` /
// `#compare` deep link. Nothing else in the eager module graph imports any
// of the three (verified: `grep -rn "from '.*applicant\(Debug\|Gallery\|
// Compare\)\.js'"` across static/js and app.js returns zero hits before this
// file existed), so removing their <script> tags and fetching them on demand
// is a pure win with no other eager module riding along.
//
// This file is the ONLY thing that stays eager in their place — and it is
// small (its only import is hashRouter.js, itself dependency-free). It
// preserves BOTH reachability paths every surface here already supports:
//
//   1. Launcher click — each surface's own module normally wires a
//      "_wireLauncher" click handler on its rail/list-item button(s) at
//      import time. Since the import hasn't happened yet, this file wires a
//      throwaway placeholder listener on those same button ids that
//      dynamic-`import()`s the real module on first click and calls its
//      open function once the import resolves.
//   2. Hash deep-link — each surface also self-registers a hashRouter route
//      (`registerRoute(token, {open, close})`) at module-eval time, so a
//      shared link / refresh / back-forward on `#debug` etc. opens it. Since
//      that registration hasn't happened yet either, this file registers a
//      placeholder route for each token that does the same dynamic import
//      before calling open — registered synchronously here, in the exact
//      load-order slot the three removed eager tags used to occupy, so it's
//      still in place well before app.js calls hashRouter.initHashRouting()
//      (matching every surface's own "registered ... well before app.js
//      calls hashRouter.initHashRouting()" comment).
//
// Once the dynamic import resolves, the real module's own module-eval-time
// code runs: it wires ITS OWN permanent click listener(s) on the same button
// id(s) and re-registers the real hashRouter route, transparently replacing
// this file's placeholders. To avoid a button ending up with two live click
// listeners (this placeholder + the module's own, both firing on every
// later click), the placeholder listener for a surface removes itself — and
// every other placeholder registered for that same surface (e.g. Compare's
// two buttons, #tool-compare-btn and #rail-compare) — the instant any one of
// them fires, before the import even starts. Route placeholders get the same
// treatment implicitly: `_open()` always funnels through `ensureLoaded()`,
// which detaches the click placeholders on its very first call regardless of
// whether it was triggered by a click or a hash-route open.

import { registerRoute } from './hashRouter.js';

// surfaceId -> { path, hashToken, buttonIds, openFn, closeFn }
const LAZY_SURFACES = {
  debug: {
    path: './applicantDebug.js',
    hashToken: 'debug',
    buttonIds: ['tool-debug-btn'],
    openFn: 'openApplicantDebug',
    closeFn: 'closeApplicantDebug',
  },
  gallery: {
    path: './applicantGallery.js',
    hashToken: 'gallery',
    buttonIds: ['tool-applicant-gallery-btn', 'rail-applicant-gallery'],
    openFn: 'openApplicantGallery',
    closeFn: 'closeApplicantGallery',
  },
  compare: {
    path: './applicantCompare.js',
    hashToken: 'compare',
    buttonIds: ['tool-compare-btn', 'rail-compare'],
    openFn: 'openApplicantCompare',
    closeFn: 'closeApplicantCompare',
  },
};

const _importPromises = {}; // surfaceId -> Promise<module|null>
const _loadedModules = {};  // surfaceId -> module namespace (once resolved)
const _placeholders = {};   // surfaceId -> [[button, listener], ...]

function _detachPlaceholders(id) {
  const list = _placeholders[id];
  if (!list) return;
  list.forEach(([btn, fn]) => {
    try { btn.removeEventListener('click', fn); } catch (_) { /* no-op */ }
  });
  _placeholders[id] = [];
}

/** Dynamic-import a lazy surface's module exactly once; every caller (click
 * or hash route) shares the same cached promise. */
function ensureLoaded(id) {
  const spec = LAZY_SURFACES[id];
  if (!spec) return Promise.resolve(null);
  if (!_importPromises[id]) {
    // Tear down the placeholder listeners now (synchronously, before the
    // import even starts) so the real module's own listeners — wired once
    // the import resolves — are the only ones left on these buttons.
    _detachPlaceholders(id);
    _importPromises[id] = import(spec.path)
      .then((mod) => { _loadedModules[id] = mod; return mod; })
      .catch((err) => {
        console.error(`lazyLaunch: failed to load ${spec.path}`, err);
        return null;
      });
  }
  return _importPromises[id];
}

function _open(id) {
  const spec = LAZY_SURFACES[id];
  return ensureLoaded(id).then((mod) => {
    if (mod && typeof mod[spec.openFn] === 'function') mod[spec.openFn]();
  });
}

function _wirePlaceholders(id) {
  const spec = LAZY_SURFACES[id];
  _placeholders[id] = _placeholders[id] || [];
  spec.buttonIds.forEach((btnId) => {
    const btn = document.getElementById(btnId);
    if (!btn || btn._applicantLazyWired) return;
    btn._applicantLazyWired = true;
    const fn = () => { _open(id); };
    btn.addEventListener('click', fn);
    _placeholders[id].push([btn, fn]);
  });
}

// Mirrors the retry-loop every applicant*.js surface already uses in its own
// `_boot()` (buttons can mount a tick after this module evaluates).
function _boot() {
  Object.keys(LAZY_SURFACES).forEach(_wirePlaceholders);
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    Object.keys(LAZY_SURFACES).forEach((id) => {
      if (_importPromises[id]) return; // already loading/loaded — nothing to wire
      _wirePlaceholders(id);
    });
    if (tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7 pattern, reused here): register a placeholder route
// per lazy surface so an initial '#debug' / '#gallery' / '#compare' deep
// link — or a hashchange navigation to one — also triggers the dynamic
// import instead of silently doing nothing. Registered synchronously at
// module-eval time, same as every surface's own registerRoute() call used
// to be when it ran eagerly.
Object.entries(LAZY_SURFACES).forEach(([id, spec]) => {
  registerRoute(spec.hashToken, {
    open: () => _open(id),
    close: () => {
      const mod = _loadedModules[id];
      if (mod && typeof mod[spec.closeFn] === 'function') mod[spec.closeFn]();
    },
  });
});

// Exposed so other already-eager modules that soft-link into one of these
// three surfaces (e.g. commandPalette.js's Ctrl+Shift+P launcher, which
// normally calls window.applicantXModule.openApplicantX() directly) can fall
// back to a lazy load when the surface hasn't been opened yet, instead of
// silently no-oping.
window.__applicantLazyOpen = function (id) { return _open(id); };

// Exported for tests (and any future caller that wants to await/inspect a
// specific lazy surface directly) -- production code only ever needs the
// click/hash triggers above.
export { LAZY_SURFACES, ensureLoaded };
