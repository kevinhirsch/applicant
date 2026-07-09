// tests/js/glassBackdropFallback.test.js
//
// X-2 cross-browser smoke — the `@supports not (backdrop-filter)` solid-panel
// fallback contract. Chromium/WebKit/modern Firefox all support
// `backdrop-filter`, so the fallback branch never renders in the visual harness
// and can't be pinned by a screenshot. This is the deterministic, per-PR gate
// that the fallback EXISTS, is WELL-FORMED, and looks INTENTIONAL: it slices the
// `@supports not (...backdrop-filter...)` block out of the shipped
// workspace/static/style.css and asserts it solidifies the golden-path glass
// surfaces to the opaque `--panel` in BOTH themes (which is theme-driving, so a
// single opaque token covers white-glass and dark) with the blur removed.
//
// It complements kit-themes.css's POSITIVE `@supports (backdrop-filter)` frost
// gate (whose un-gated fallback is the solid --panel) — together they mean a
// no-backdrop-filter engine gets a deliberate solid panel, never a see-through
// low-contrast ghost shell.

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const STYLE = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'style.css'),
  'utf8',
);

// Brace-balanced extraction of the FIRST `@supports not (...backdrop-filter...)`
// block body (same technique the JS suite uses to slice function bodies).
function extractSupportsNotBackdrop(css) {
  const re = /@supports\s+not\s*\(([^{]*backdrop-filter[^{]*)\)\s*\{/gi;
  const m = re.exec(css);
  if (!m) return null;
  const header = m[0];
  let i = m.index + header.length;
  let depth = 1;
  const start = i;
  for (; i < css.length && depth > 0; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') depth--;
  }
  return { condition: m[1].trim(), body: css.slice(start, i - 1) };
}

test('style.css ships an @supports not (backdrop-filter) fallback block', () => {
  const block = extractSupportsNotBackdrop(STYLE);
  assert.ok(block, 'no @supports not (…backdrop-filter…) block found in style.css');
  // The condition must reference BOTH the unprefixed and -webkit- forms so the
  // fallback engages only when NEITHER is supported (the exact inverse of the
  // kit-themes.css positive gate) — never firing on a -webkit-only engine.
  assert.match(block.condition, /backdrop-filter/i);
  assert.match(block.condition, /-webkit-backdrop-filter/i);
});

test('the fallback solidifies the glass surfaces (opaque panel, no blur)', () => {
  const { body } = extractSupportsNotBackdrop(STYLE);
  // A deliberate solid panel: opaque --panel fill, no bg image, blur removed.
  assert.match(body, /background-color:\s*var\(--panel[^;]*\)\s*!important/i,
    'fallback must set an opaque var(--panel) background');
  assert.match(body, /background-image:\s*none\s*!important/i,
    'fallback must drop the translucent glass gradient fill');
  assert.match(body, /(^|[^-])backdrop-filter:\s*none\s*!important/i,
    'fallback must neutralize backdrop-filter');
  assert.match(body, /-webkit-backdrop-filter:\s*none\s*!important/i,
    'fallback must neutralize -webkit-backdrop-filter');
});

test('the fallback covers the golden-path glass surfaces', () => {
  const { body } = extractSupportsNotBackdrop(STYLE);
  // The core front-door glass chrome a user walks on the golden path. Each MUST
  // be listed in the fallback selector list, scoped to the glass body class, or
  // it renders see-through when backdrop-filter is unsupported.
  const required = [
    '.ow-window',        // windows / cards shell
    '#sidebar',          // nav sidebar
    '.chat-input-bar',   // chat composer
    '.modal-content',    // modals (settings, theme, etc.)
    '.admin-card',       // settings/admin cards
    '.model-picker-menu',
    '.toast',            // notification toasts
    '.search-popup',     // command/search palette (free-floating)
    '.ow-sheet',         // mobile bottom sheet (free-floating)
  ];
  for (const sel of required) {
    assert.ok(
      body.includes(sel),
      `@supports-not fallback is missing a solid-panel rule for '${sel}'`,
    );
  }
  // Every selector in the block is scoped to the frosted (glass) body so base /
  // dark non-glass themes — already opaque — are never touched.
  assert.match(body, /body\.theme-frosted/,
    'fallback rules must be scoped to body.theme-frosted');
});
