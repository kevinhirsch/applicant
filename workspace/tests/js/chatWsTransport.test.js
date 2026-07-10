// workspace/tests/js/chatWsTransport.test.js
//
// Headless behavioral tests for the chat-WS transport's PURE helpers
// (../../static/js/chatWsTransport.js): the WS URL builder, the subscribe-frame
// shape, the incoming-message classifier, the [DONE] sentinel detector, and the
// reconnect backoff.
//
// Like applicantRealtime.test.js, this does NOT import the module (its browser
// code touches WebSocket/TextEncoder/window at eval time). It reads the REAL
// source and extracts just the pure functions via a balanced-brace slicer, then
// executes that exact text — so reverting a helper flips these assertions red.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC_PATH = fileURLToPath(new URL('../../static/js/chatWsTransport.js', import.meta.url));
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
  if (start === -1) throw new Error(`function ${name} not found in chatWsTransport.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// eslint-disable-next-line no-new-func
function load(...names) {
  const body = names.map((n) => extractFunction(SRC, n)).join('\n');
  return new Function(`${body}\nreturn { ${names.join(', ')} };`)();
}

test('chatWsUrl picks wss for https and carries session + resume', () => {
  const { chatWsUrl } = load('chatWsUrl');
  const secure = chatWsUrl({ protocol: 'https:', host: 'x.io' }, 'sess-1', 3);
  assert.ok(secure.startsWith('wss://x.io/api/chat/ws'));
  assert.ok(secure.includes('session=sess-1'));
  assert.ok(secure.includes('resume=3'));
  // http → ws, and resume=0 (or negative) is omitted (fresh subscribe).
  const plain = chatWsUrl({ protocol: 'http:', host: 'y:7000' }, 'sess-1', 0);
  assert.equal(plain, 'ws://y:7000/api/chat/ws?session=sess-1');
});

test('buildChatSubscribeFrame shapes the sole upstream verb', () => {
  const { buildChatSubscribeFrame } = load('buildChatSubscribeFrame');
  assert.deepEqual(buildChatSubscribeFrame('s', 5), { type: 'subscribe', session: 's', resume: 5 });
  // Missing / negative resume normalizes to 0 (a fresh full replay).
  assert.deepEqual(buildChatSubscribeFrame('s'), { type: 'subscribe', session: 's', resume: 0 });
  assert.deepEqual(buildChatSubscribeFrame('s', -4), { type: 'subscribe', session: 's', resume: 0 });
});

test('parseChatWsMessage classifies server frames', () => {
  const { parseChatWsMessage } = load('parseChatWsMessage');
  assert.deepEqual(
    parseChatWsMessage('{"type":"chunk","seq":0,"data":"data: {\\"delta\\": \\"hi\\"}\\n\\n"}'),
    { kind: 'chunk', data: 'data: {"delta": "hi"}\n\n' },
  );
  assert.deepEqual(parseChatWsMessage('{"type":"end","seq":4}'), { kind: 'end' });
  assert.deepEqual(parseChatWsMessage('{"type":"error","error":"nope"}'), { kind: 'error', error: 'nope' });
  // Non-string chunk data, unknown types, and garbage are ignored (never crash).
  assert.equal(parseChatWsMessage('{"type":"chunk","data":123}').kind, 'ignore');
  assert.equal(parseChatWsMessage('not json').kind, 'ignore');
  assert.equal(parseChatWsMessage(null).kind, 'ignore');
  // Accepts an already-parsed object too.
  assert.deepEqual(parseChatWsMessage({ type: 'end' }), { kind: 'end' });
});

test('chatChunkIsDone detects the terminal [DONE] sentinel', () => {
  const { chatChunkIsDone } = load('chatChunkIsDone');
  assert.equal(chatChunkIsDone('data: [DONE]\n\n'), true);
  assert.equal(chatChunkIsDone('data: {"delta": "x"}\n\n'), false);
  assert.equal(chatChunkIsDone(''), false);
  assert.equal(chatChunkIsDone(null), false);
});

test('chatWsBackoffMs grows exponentially and caps at 8s', () => {
  const { chatWsBackoffMs } = load('chatWsBackoffMs');
  assert.equal(chatWsBackoffMs(0), 500);
  assert.equal(chatWsBackoffMs(1), 1000);
  assert.equal(chatWsBackoffMs(2), 2000);
  assert.equal(chatWsBackoffMs(20), 8000); // capped
});
