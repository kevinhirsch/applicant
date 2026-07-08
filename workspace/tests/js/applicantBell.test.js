// workspace/tests/js/applicantBell.test.js
//
// Headless behavioral tests for the P0-3b top-bar notification BELL's PURE
// helpers (../../static/js/applicantBell.js): the compact count label and the
// dropdown row builder.
//
// Like applicantRail.test.js, this does NOT import the module: applicantBell
// statically imports applicantCore.js, whose chain pulls ui.js and registers
// real timers/observers at module-eval time (the documented headless hang). So
// these tests read the REAL source and extract just the pure functions (via a
// balanced-brace slicer, not a hand copy) and execute that exact text. Reverting
// a helper in the source changes the extracted text, so these assertions go red
// on revert and green on restore — the same guarantee an import() would give
// without a browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const BELL_PATH = fileURLToPath(new URL('../../static/js/applicantBell.js', import.meta.url));
const SRC = readFileSync(BELL_PATH, 'utf8');

// ── tiny source-slicer (brace-balanced, not a naive regex) ────────────────

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${BELL_PATH}`);
}

function extractFunction(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in applicantBell.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// The helpers lean on applicantCore's `esc` and the module-level
// MAX_DROPDOWN_ROWS const — supply matching stand-ins so the sliced body runs
// exactly as it does in the browser.
const PRELUDE = `
  const MAX_DROPDOWN_ROWS = 8;
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
`;

// ── _bellCountLabel ───────────────────────────────────────────────────────

test('_bellCountLabel hides at zero, caps at 99+, and never throws on junk', () => {
  const _bellCountLabel = new Function(`${extractFunction(SRC, '_bellCountLabel')}\nreturn _bellCountLabel;`)();
  assert.equal(_bellCountLabel(0), '', 'zero -> empty (badge hidden)');
  assert.equal(_bellCountLabel(-3), '', 'negative -> empty');
  assert.equal(_bellCountLabel(1), '1', 'one shown as-is');
  assert.equal(_bellCountLabel(99), '99', '99 shown as-is');
  assert.equal(_bellCountLabel(100), '99+', '100 caps at 99+');
  assert.equal(_bellCountLabel(4000), '99+', 'large caps at 99+');
  assert.equal(_bellCountLabel('7'), '7', 'numeric string coerced');
  assert.equal(_bellCountLabel(undefined), '', 'undefined -> empty, no throw');
  assert.equal(_bellCountLabel('not-a-number'), '', 'junk -> empty, no throw');
});

// ── _bellItemRows ─────────────────────────────────────────────────────────

test('_bellItemRows mirrors the shared pending feed, escapes, and caps with a "+N more"', () => {
  const _bellItemRows = new Function(`${PRELUDE}\n${extractFunction(SRC, '_bellItemRows')}\nreturn _bellItemRows;`)();

  // Empty / malformed input -> no rows, no throw.
  assert.equal(_bellItemRows([], 8), '', 'empty list -> empty string');
  assert.equal(_bellItemRows(undefined, 8), '', 'undefined -> empty string');

  // A well-formed item renders its title + campaign context, each escaped.
  const one = _bellItemRows([
    { id: 'act-1', title: 'Approve <b>Acme</b> role', campaign_name: 'Backend & SRE' },
  ], 8);
  assert.ok(one.includes('data-action-id="act-1"'), 'carries the action id');
  assert.ok(one.includes('applicant-bell-item'), 'uses the bell item class (styled from the design system)');
  assert.ok(one.includes('Approve &lt;b&gt;Acme&lt;/b&gt; role'), 'title is HTML-escaped');
  assert.ok(one.includes('Backend &amp; SRE'), 'campaign name is HTML-escaped');
  assert.ok(!one.includes('+') || !/\+\d+ more/.test(one), 'no "+N more" footer when nothing is truncated');

  // A title-less row falls back to the calm generic line (never blank/undefined).
  const generic = _bellItemRows([{ id: 'x' }], 8);
  assert.ok(generic.includes('Needs your attention'), 'blank title -> generic fallback line');

  // The cap truncates and adds a "+N more in Today" footer for the remainder.
  const many = Array.from({ length: 11 }, (_, i) => ({ id: `a${i}`, title: `Item ${i}` }));
  const capped = _bellItemRows(many, 8);
  const rendered = (capped.match(/applicant-bell-item"/g) || []).length;
  assert.equal(rendered, 8, 'renders exactly the cap');
  assert.ok(capped.includes('+3 more in Today'), 'footer names the truncated remainder and points at Today');
});
