// workspace/tests/js/applicantSnapshotFidelity.test.js
//
// H3 (full-fidelity review): behavioral tests for the ONE submission-snapshot
// renderer both pre-submit surfaces share (the live-session modal's "Review
// exactly what will be sent" panel and the Portal/Today final-approval cards,
// which call the same exported `renderSubmissionSnapshot`). What the owner
// reviews must be the LITERAL payload — every answer verbatim, never elided or
// summarized — and the empty state must be honest, never fabricated.
//
// Like applicantPortal.test.js, this file does not `import()` the module
// (applicantRemote.js pulls ui.js's browser-global machinery at module-eval
// time); it slices the real function bodies out of the shipped source with the
// same balanced-brace extractor and executes that exact text with an `esc`
// stub. Reverting the renderer changes the extracted text, so these go red on
// revert and green on restore.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const REMOTE_PATH = fileURLToPath(new URL('../../static/js/applicantRemote.js', import.meta.url));
const SRC = readFileSync(REMOTE_PATH, 'utf8');

// ── tiny source-slicer (brace-balanced, same approach as applicantPortal.test.js) ──

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${REMOTE_PATH}`);
}

function extractFunction(src, name) {
  const asyncMarker = `async function ${name}(`;
  const plainMarker = `function ${name}(`;
  let start = src.indexOf(asyncMarker);
  if (start === -1) start = src.indexOf(plainMarker);
  if (start === -1) throw new Error(`function ${name} not found in ${REMOTE_PATH}`);
  const braceIdx = src.indexOf('{', start);
  return src.slice(start, braceIdx) + extractBalanced(src, braceIdx);
}

// The renderer and its private helpers, executed as the exact shipped text.
const RENDER_SRC = [
  extractFunction(SRC, '_scalar'),
  extractFunction(SRC, '_kvRows'),
  extractFunction(SRC, '_fmtTs'),
  extractFunction(SRC, '_snapshotEmptyHTML'),
  extractFunction(SRC, '_renderSnapshot'),
].join('\n');

// Minimal `esc` stub matching applicantCore.js's contract (HTML-escape only —
// content must otherwise pass through UNCHANGED, that is the invariant).
const factory = new Function(`
  const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  ${RENDER_SRC}
  return { render: _renderSnapshot, empty: _snapshotEmptyHTML };
`);
const { render, empty } = factory();

// ── the literal payload renders verbatim ────────────────────────────────────

test('every answer renders verbatim — long text is never truncated or summarized', () => {
  const longAnswer = 'I led the migration of a 40-service platform to event-driven '
    + 'architecture over 18 months, cutting p99 latency 62% and on-call pages by half, '
    + 'then trained four teams on the new patterns so the change stuck.';
  const html = render({
    has_snapshot: true,
    stage: 'reviewed',
    answers: {
      'Why do you want this role?': longAnswer,
      '#salary': '185000',
    },
    materials: [{ kind: 'resume', name: 'ada-resume.pdf' }],
    posting_url: 'https://jobs.example.com/42',
  });
  assert.ok(html.includes(longAnswer), 'the full answer text must appear, word for word');
  assert.ok(html.includes('Why do you want this role?'));
  assert.ok(html.includes('185000'));
  assert.ok(html.includes('ada-resume.pdf'));
  assert.ok(html.includes('https://jobs.example.com/42'));
});

test('the reviewed stage says plainly this is what WILL be sent', () => {
  const html = render({ has_snapshot: true, stage: 'reviewed', answers: { q: 'a' } });
  assert.ok(html.includes('exactly what will be sent'));
  assert.ok(!html.includes('exactly what was sent'));
});

test('the submitted stage says plainly this is what WAS sent', () => {
  const html = render({ has_snapshot: true, stage: 'submitted', answers: { q: 'a' } });
  assert.ok(html.includes('exactly what was sent'));
  assert.ok(!html.includes('exactly what will be sent'));
});

test('an unknown stage claims neither — no fabricated capture point', () => {
  const html = render({ has_snapshot: true, answers: { q: 'a' } });
  assert.ok(!html.includes('exactly what will be sent'));
  assert.ok(!html.includes('exactly what was sent'));
});

// ── honesty at the edges ─────────────────────────────────────────────────────

test('no snapshot renders the honest empty state, never fabricated content', () => {
  const html = render({ has_snapshot: false });
  assert.equal(html, empty());
  assert.ok(html.includes('Nothing recorded to send yet'));
});

test('answer values are HTML-escaped but content-complete (fidelity + safety)', () => {
  const html = render({
    has_snapshot: true,
    stage: 'reviewed',
    answers: { 'Notes': 'I know <C++> & "Rust"' },
  });
  assert.ok(html.includes('I know &lt;C++&gt; &amp; &quot;Rust&quot;'));
});
