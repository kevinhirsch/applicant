// workspace/tests/js/applicantDemoBanner.test.js
//
// Behavioral tests for the seeded-demo banner's pure render helper
// (demoBannerHTML) in ../../static/js/applicantDemoBanner.js (P0-2).
//
// Like applicantPortal.test.js, this file does NOT import() the module: its
// static import chain pulls in applicantCore.js -> ui.js, which touches browser
// globals (HTMLInputElement, timers/observers) at module-eval time and hangs a
// headless Node process. So it reads the REAL source and slices out just the
// pure demoBannerHTML function (via a balanced-brace slicer, not a hand copy)
// and executes that exact text with a minimal esc() stub. Reverting the render
// logic in the shipped source changes the extracted text, so these assertions
// go red on revert and green on restore — a genuine regression guard.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const MOD_PATH = fileURLToPath(new URL('../../static/js/applicantDemoBanner.js', import.meta.url));
const SRC = readFileSync(MOD_PATH, 'utf8');

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${MOD_PATH}`);
}

function extractFunction(src, name) {
  // `export function NAME(` contains `function NAME(` as a substring, so this
  // slices the standalone function body (dropping the `export` keyword).
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in applicantDemoBanner.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

const ESC_STUB = `function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}`;

function loadDemoBannerHTML() {
  const body = [ESC_STUB, extractFunction(SRC, 'demoBannerHTML'), 'return demoBannerHTML;'].join('\n');
  // eslint-disable-next-line no-new-func
  return new Function(body)();
}

test('demoBannerHTML returns empty string when demo is not active', () => {
  const demoBannerHTML = loadDemoBannerHTML();
  assert.equal(demoBannerHTML(null), '');
  assert.equal(demoBannerHTML(undefined), '');
  assert.equal(demoBannerHTML({ demo_active: false }), '');
  assert.equal(demoBannerHTML({}), '');
});

test('demoBannerHTML renders a labelled banner with a Clear control when active', () => {
  const demoBannerHTML = loadDemoBannerHTML();
  const html = demoBannerHTML({ demo_active: true, counts: { applications: 5 } });
  assert.ok(html.includes('Demo data'), 'banner is labelled "Demo data"');
  assert.ok(html.includes('5 sample applications'), 'summarises the seeded volume');
  assert.ok(html.includes('Nothing here is real'), 'reads as synthetic, not production data');
  assert.ok(html.includes('id="applicant-demo-clear"'), 'exposes the one-click clear control');
  assert.ok(html.includes('Clear demo data'), 'the clear control is labelled');
});

test('demoBannerHTML pluralises and falls back honestly', () => {
  const demoBannerHTML = loadDemoBannerHTML();
  const one = demoBannerHTML({ demo_active: true, counts: { applications: 1 } });
  assert.ok(one.includes('1 sample application '), 'singular for a single application');
  assert.ok(!one.includes('1 sample applications'), 'no incorrect plural');
  // No/blank counts -> a generic, non-fabricated summary (never a made-up number).
  const none = demoBannerHTML({ demo_active: true });
  assert.ok(none.includes('Sample data is loaded'), 'generic summary when counts absent');
  assert.ok(!/\d/.test(none.replace('applicant-demo', '')), 'never invents a count');
});
