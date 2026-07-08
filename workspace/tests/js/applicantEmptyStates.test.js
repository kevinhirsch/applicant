// workspace/tests/js/applicantEmptyStates.test.js
//
// Headless behavioral tests for the P0-5 shared empty-state component
// (../../static/js/applicantCore.js `emptyHTML`): the agreed design is
// icon + sentence + one real CTA, theme-safe in light and dark.
//
// Like applicantRail.test.js, this does NOT import the module: applicantCore
// statically imports ui.js, which touches browser globals at module-eval time.
// So these tests read the REAL source, extract the exact function text via a
// balanced-brace slicer, and execute it with the collaborators it names
// (ui.js's real `emptyStateIcon`, a spec-faithful `esc`). Reverting the
// component in the source changes the extracted text, so these assertions go
// red on revert and green on restore.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CORE_PATH = fileURLToPath(new URL('../../static/js/applicantCore.js', import.meta.url));
const UI_PATH = fileURLToPath(new URL('../../static/js/ui.js', import.meta.url));
const CORE_SRC = readFileSync(CORE_PATH, 'utf8');
const UI_SRC = readFileSync(UI_PATH, 'utf8');

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
  throw new Error(`unbalanced braces starting at index ${openIdx}`);
}

// Finds `function NAME(` even when preceded by `export ` — indexOf lands on
// the `function` keyword, yielding a standalone executable function.
function extractFunction(src, name, path) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in ${path}`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// The component under test, executed with the REAL ui.js icon helper wired in
// as `uiModule` — exactly the collaborator the shipped module resolves.
function buildEmptyHTML() {
  const code = [
    extractFunction(UI_SRC, 'emptyStateIcon', 'ui.js'),
    'const uiModule = { emptyStateIcon };',
    // Spec-faithful esc (same table as applicantCore's own fallback branch).
    `function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c])); }`,
    extractFunction(CORE_SRC, 'emptyHTML', 'applicantCore.js'),
    'return emptyHTML;',
  ].join('\n');
  return new Function(code)();
}

// ── icon + sentence + one CTA composition ─────────────────────────────────

test('emptyHTML composes icon + title + sub + CTA in the shared shell', () => {
  const emptyHTML = buildEmptyHTML();
  const html = emptyHTML(
    'Nothing to track yet',
    'Once I submit an application, it shows up here.',
    '<button class="cal-btn" id="cta">See what I’m working on</button>',
  );
  assert.ok(html.includes('class="applicant-empty"'), 'shared shell class present');
  assert.ok(html.includes('Nothing to track yet'), 'title rendered');
  assert.ok(html.includes('Once I submit an application'), 'sub-line rendered');
  assert.ok(html.includes('id="cta"'), 'CTA slot rendered verbatim');
  assert.ok(html.includes('<svg'), 'icon rendered by default');
  assert.ok(html.indexOf('<svg') < html.indexOf('id="cta"'), 'icon precedes the CTA');
});

test('emptyHTML default icon is the smiley; offline call sites can pick neutral', () => {
  const emptyHTML = buildEmptyHTML();
  const smiley = emptyHTML('T');
  const neutral = emptyHTML('T', '', '', 'neutral');
  // The smiley mouth is a curve; the neutral mouth is a straight line.
  assert.ok(smiley.includes('M8 14s1.5 2 4 2 4-2 4-2'), 'default renders the smiley mouth');
  assert.ok(neutral.includes('x1="8" y1="15" x2="16" y2="15"'), 'neutral renders the flat mouth');
});

test('emptyHTML icon can be omitted and is a11y-hidden decoration when present', () => {
  const emptyHTML = buildEmptyHTML();
  const bare = emptyHTML('T', 'S', '', null);
  assert.ok(!bare.includes('<svg'), 'icon=null omits the icon entirely');
  const withIcon = emptyHTML('T');
  assert.ok(withIcon.includes('aria-hidden="true"'), 'icon wrapper is aria-hidden');
});

test('emptyHTML is theme-safe: icon inherits currentColor, text uses CSS vars', () => {
  const emptyHTML = buildEmptyHTML();
  const html = emptyHTML('T', 'S');
  assert.ok(html.includes('stroke="currentColor"'), 'icon stroke follows the theme');
  assert.ok(html.includes('var(--fg-muted)') && html.includes('var(--fg)'),
    'copy colors come from theme variables, never hard-coded hex');
});

test('emptyHTML escapes the title and sub (CTA slot alone is trusted HTML)', () => {
  const emptyHTML = buildEmptyHTML();
  const html = emptyHTML('<b>x</b>', '<i>y</i>');
  assert.ok(html.includes('&lt;b&gt;x&lt;/b&gt;'), 'title escaped');
  assert.ok(html.includes('&lt;i&gt;y&lt;/i&gt;'), 'sub escaped');
});
