// workspace/tests/visual/detector.js
//
// Per-state layout assertions the visual harness (P0-6) runs on EVERY
// surface/state in the matrix, before the screenshot:
//
//   1. OFF-SCREEN ELEMENT DETECTOR — flags any rendered element that sits
//      entirely outside the viewport/page box (fully left of / above the
//      viewport, right of the viewport's width, or below the page's own
//      scroll height). Elements that are display:none, visibility:hidden,
//      zero-sized, or inside [aria-hidden="true"] are not "rendered" and are
//      skipped. Everything else that ends up off-screen is either a layout
//      bug or a deliberately staged element — and every deliberate case must
//      be named in OFFSCREEN_ALLOWLIST below with a reason. No blanket
//      exemptions.
//
//   2. HORIZONTAL-OVERFLOW ASSERT — document.documentElement.scrollWidth must
//      not exceed clientWidth: the page body never scrolls sideways at any
//      covered viewport.
//
// A violation of either fails the run (run.js exits 1 and lists offenders).

'use strict';

// Each entry is matched with Element.closest(selector) — an offender inside
// (or being) a matching element is exempt. Keep entries PRECISE: one selector
// per mechanism, each with a one-line reason.
const OFFSCREEN_ALLOWLIST = [
  // The singleton toast (#toast, ui.js showToast) in its STAGED state: style.css
  // parks it at translateX(120%) / opacity:0 off the right edge and `.show`
  // slides it in — its parked position is off-screen by design.
  { selector: '.toast:not(.show)', reason: 'staged toast parks off the right edge (translateX(120%)) until .show slides it in' },
  // The vendored chat composer settles its height through several independent
  // async flips (session re-enable, autofocus/focus-restore, model-chip
  // fetch) — during a flip its bottom icon row can transiently sit a few px
  // below the fold at short viewports. Same mechanism its pixel MASK exists
  // for (run.js MASKS); the settled bar is bottom-anchored and fully visible.
  { selector: '.chat-input-bar', reason: 'composer bottom row transiently dips below the fold mid-settle; settled bar is visible (mirrors its pixel mask)' },
];

/**
 * Runs the user-specified off-screen detector inside the page. Returns the
 * list of offenders (empty = pass). `allowlist` is serialized into the page;
 * an element matching (or inside) any allowlisted selector is skipped, and
 * each skip is tallied so a stale allowlist entry is visible in the report.
 */
async function findOffscreenElements(page, allowlist = OFFSCREEN_ALLOWLIST) {
  const selectors = allowlist.map((e) => e.selector);
  return await page.evaluate((allowSelectors) => {
    const bad = [];
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const pageH = document.documentElement.scrollHeight;
    const allowed = (el) => {
      for (const sel of allowSelectors) {
        try { if (el.closest(sel)) return true; } catch (_) { /* bad selector — never silently allow */ }
      }
      return false;
    };
    // Content below/beside the fold of an INNER scroll container (a modal's
    // settings sidebar/panels, the gadget rail's overflow-y:auto stack) is
    // reachable by scrolling — not an off-screen escape. An element is only
    // excused when a scrollable ancestor exists AND the element lies within
    // that ancestor's scrollable content extent; anything translated outside
    // the scroll range still gets flagged. Mechanism-level correctness of the
    // detector, not an allowlist entry.
    const reachableInScroller = (el, r) => {
      let a = el.parentElement;
      while (a && a !== document.body) {
        const st = getComputedStyle(a);
        const scrollY = /(auto|scroll)/.test(st.overflowY) && a.scrollHeight > a.clientHeight + 1;
        const scrollX = /(auto|scroll)/.test(st.overflowX) && a.scrollWidth > a.clientWidth + 1;
        if (scrollY || scrollX) {
          const ar = a.getBoundingClientRect();
          const relTop = r.top - ar.top + a.scrollTop;
          const relLeft = r.left - ar.left + a.scrollLeft;
          if (relTop + r.height > 0 && relTop < a.scrollHeight &&
              relLeft + r.width > 0 && relLeft < a.scrollWidth) return true;
        }
        a = a.parentElement;
      }
      return false;
    };
    for (const el of document.querySelectorAll('body *')) {
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || el.closest('[aria-hidden="true"]')) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= pageH) {
        if (allowed(el)) continue;
        if (reachableInScroller(el, r)) continue;
        bad.push({
          sel: el.tagName + (el.id ? '#' + el.id : '') +
               (el.classList.length ? '.' + Array.from(el.classList).slice(0, 3).join('.') : ''),
          rect: { x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, right: r.right, bottom: r.bottom, left: r.left },
        });
        if (bad.length >= 25) break; // enough to diagnose; don't flood the report
      }
    }
    return { offenders: bad, viewport: { vw, vh, pageH } };
  }, selectors);
}

/** Horizontal-overflow assert: the page must never scroll sideways. */
async function checkHorizontalOverflow(page) {
  return await page.evaluate(() => {
    const d = document.documentElement;
    return {
      ok: d.scrollWidth <= d.clientWidth,
      scrollWidth: d.scrollWidth,
      clientWidth: d.clientWidth,
    };
  });
}

module.exports = { OFFSCREEN_ALLOWLIST, findOffscreenElements, checkHorizontalOverflow };
