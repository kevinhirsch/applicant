// workspace/tests/js/researchWsTransport.test.js
//
// Headless behavioral tests for the research-WS transport's PURE helpers
// (../../static/js/research/jobs.js): the WS URL builder, the subscribe-frame
// shape, and the incoming-message classifier.
//
// Like chatWsTransport.test.js, this does NOT import the module (jobs.js touches
// EventSource/WebSocket/window/localStorage at eval time). It reads the REAL
// source and extracts just the pure functions via a balanced-brace slicer, then
// executes that exact text — so reverting a helper flips these assertions red.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC_PATH = fileURLToPath(new URL('../../static/js/research/jobs.js', import.meta.url));
const SRC = readFileSync(SRC_PATH, 'utf8');

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

function extractFunction(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in research/jobs.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// eslint-disable-next-line no-new-func
function load(...names) {
  const body = names.map((n) => extractFunction(SRC, n)).join('\n');
  return new Function(`${body}\nreturn { ${names.join(', ')} };`)();
}

test('researchWsUrl picks wss for https and carries the session', () => {
  const { researchWsUrl } = load('researchWsUrl');
  const secure = researchWsUrl({ origin: 'https://x.io' }, '', 'rp-1');
  assert.equal(secure, 'wss://x.io/api/research/ws?session=rp-1');
  // http origin → ws.
  const plain = researchWsUrl({ origin: 'http://y:7000' }, '', 'rp-1');
  assert.equal(plain, 'ws://y:7000/api/research/ws?session=rp-1');
});

test('researchWsUrl prefers an absolute apiBase over loc', () => {
  const { researchWsUrl } = load('researchWsUrl');
  const url = researchWsUrl({ origin: 'https://front.io' }, 'https://api.internal:8000', 'rp-9');
  assert.ok(url.startsWith('wss://api.internal:8000/api/research/ws'));
  assert.ok(url.includes('session=rp-9'));
  // A relative apiBase ('' or '/foo') is ignored in favor of the location origin.
  const rel = researchWsUrl({ origin: 'https://front.io' }, '', 'rp-9');
  assert.ok(rel.startsWith('wss://front.io/api/research/ws'));
});

test('buildResearchSubscribeFrame shapes the sole upstream verb', () => {
  const { buildResearchSubscribeFrame } = load('buildResearchSubscribeFrame');
  assert.deepEqual(buildResearchSubscribeFrame('rp-1', 3), { type: 'subscribe', session: 'rp-1', resume: 3 });
  // resume defaults to 0 (fresh subscribe) for undefined / negative.
  assert.deepEqual(buildResearchSubscribeFrame('rp-1'), { type: 'subscribe', session: 'rp-1', resume: 0 });
  assert.deepEqual(buildResearchSubscribeFrame('rp-1', -5), { type: 'subscribe', session: 'rp-1', resume: 0 });
});

test('parseResearchWsMessage classifies event / end / error / ignore', () => {
  const { parseResearchWsMessage } = load('parseResearchWsMessage');
  assert.deepEqual(
    parseResearchWsMessage(JSON.stringify({ type: 'event', seq: 0, data: { status: 'running' } })),
    { kind: 'event', data: { status: 'running' } },
  );
  assert.deepEqual(parseResearchWsMessage(JSON.stringify({ type: 'end', seq: 4 })), { kind: 'end' });
  assert.deepEqual(
    parseResearchWsMessage(JSON.stringify({ type: 'error', error: 'nope' })),
    { kind: 'error', error: 'nope' },
  );
  // Unparseable / unknown / malformed-event → ignore (never throws).
  assert.deepEqual(parseResearchWsMessage('not json'), { kind: 'ignore' });
  assert.deepEqual(parseResearchWsMessage(JSON.stringify({ type: 'event' })), { kind: 'ignore' });
  assert.deepEqual(parseResearchWsMessage(JSON.stringify({ type: 'other' })), { kind: 'ignore' });
});
