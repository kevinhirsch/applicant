// workspace/tests/js/applicantCampaignSwitcher.test.js
//
// Behavioral regression tests for the shared campaign switcher's one
// filtering rule (P1-10 — multi-campaign) in
// ../../static/js/applicantCampaignSwitcher.js:
//
//   * '' (no search selected) keeps every item;
//   * a selected search keeps ONLY that search's items…
//   * …EXCEPT items carrying no campaign_id at all, which are ALWAYS kept —
//     deployment-level rows ("finish setup", engine notices) must never
//     silently vanish under a search filter (H-series: nothing degrades
//     silently, and a filter must never hide action-required work).
//
// Same approach as applicantPortal.test.js (see its header for the full
// rationale): the module imports applicantCore.js whose import chain touches
// browser globals at module-eval time, so instead of import()ing we slice the
// REAL function bodies out of the shipped source with a balanced-brace
// extractor and execute that exact text with minimal stubs. Reverting the
// shipped rule changes the extracted text, so these go red on revert.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SWITCHER_PATH = fileURLToPath(
  new URL('../../static/js/applicantCampaignSwitcher.js', import.meta.url),
);
const SRC = readFileSync(SWITCHER_PATH, 'utf8');

// ── tiny source-slicer (brace-balanced, mirrors applicantPortal.test.js) ───

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${SWITCHER_PATH}`);
}

function extractFunction(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in applicantCampaignSwitcher.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// filterByCampaign reads the persisted selection through _read(), which needs
// the real ACTIVE_CAMPAIGN_KEY const; slice that line out of the source too
// (a stubbed-in copy would go stale if the shipped key ever changed). Stub the
// localStorage it touches so each test controls the selection directly.
function extractConstLine(src, name) {
  const m = src.match(new RegExp(`const ${name} = [^;]+;`));
  if (!m) throw new Error(`const ${name} not found in applicantCampaignSwitcher.js`);
  return m[0];
}

function makeFilter(selection) {
  const keySrc = extractConstLine(SRC, 'ACTIVE_CAMPAIGN_KEY');
  const readSrc = extractFunction(SRC, '_read');
  const filterSrc = extractFunction(SRC, 'filterByCampaign');
  const factory = new Function(
    'localStorage',
    `${keySrc}\n${readSrc}\n${filterSrc}\nreturn filterByCampaign;`,
  );
  return factory({ getItem: () => selection });
}

const ITEMS = [
  { id: 1, campaign_id: 'camp-a', title: 'A-only row' },
  { id: 2, campaign_id: 'camp-b', title: 'B-only row' },
  { id: 3, title: 'deployment-level row (no campaign id)' },
];

test('no selection keeps every item', () => {
  const filter = makeFilter('');
  assert.deepEqual(filter(ITEMS).map((i) => i.id), [1, 2, 3]);
});

test("a selected search keeps that search's items and drops the sibling's", () => {
  const filter = makeFilter('camp-a');
  const ids = filter(ITEMS).map((i) => i.id);
  assert.ok(ids.includes(1), 'own-campaign item must be kept');
  assert.ok(!ids.includes(2), "the sibling campaign's item must be filtered out");
});

test('items with no campaign id are ALWAYS kept (never silently hidden)', () => {
  const filter = makeFilter('camp-a');
  const ids = filter(ITEMS).map((i) => i.id);
  assert.ok(ids.includes(3), 'a deployment-level row must survive any search filter');
});

test('non-array input degrades to an empty list, never throws', () => {
  const filter = makeFilter('camp-a');
  assert.deepEqual(filter(null), []);
  assert.deepEqual(filter(undefined), []);
});
