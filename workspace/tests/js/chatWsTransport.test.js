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

test('_open does NOT reset the reconnect budget on bare onopen (Greptile #808): an accept-then-drop-before-data cycle must consume the budget and reach fallback, not loop forever', () => {
  // The reconnecting _open() socket: resetting _attempts in onopen would let a
  // proxy that accepts then immediately drops the WS reconnect indefinitely,
  // never reaching CHAT_WS_MAX_RECONNECTS. The budget is cleared only when a
  // REAL frame arrives (onmessage), proving the stream is genuinely alive.
  const openIdx = SRC.indexOf('_open() {');
  assert.ok(openIdx !== -1, '_open is present');
  // Bound the slice to the _open method (up to the next method / waitForOpen).
  const end = SRC.indexOf('waitForOpen', openIdx);
  const openBody = SRC.slice(openIdx, end === -1 ? openIdx + 1400 : end);
  const onopenIdx = openBody.indexOf('ws.onopen');
  const onmsgIdx = openBody.indexOf('ws.onmessage');
  const onopenBlock = openBody.slice(onopenIdx, onmsgIdx);
  assert.ok(!/_attempts\s*=\s*0/.test(onopenBlock), 'onopen must NOT reset the reconnect budget');
  const onmsgBlock = openBody.slice(onmsgIdx);
  assert.ok(/_attempts\s*=\s*0/.test(onmsgBlock), 'the budget resets on a real server frame (onmessage), not on bare open');
});

test('reconnect resume offset counts RECEIVED events, not just drained ones (Greptile #808): buffered-but-unread chunks must not replay twice', () => {
  // `_delivered` only advances on read(); a chunk received into `_queue` but not
  // yet drained is still client-side, so the server resume offset must include it
  // (`_delivered + _queue.length`) or the server replays it AND the queued copy
  // drains — a duplicate. `_open` must resume from `_resumeOffset()`, not `_delivered`.
  assert.ok(
    /_resumeOffset\(\)\s*\{[\s\S]*?this\._delivered\s*\+\s*this\._queue\.length/.test(SRC),
    '_resumeOffset() sums delivered + still-queued (all received events)',
  );
  const openIdx = SRC.indexOf('_open() {');
  const end = SRC.indexOf('waitForOpen', openIdx);
  const openBody = SRC.slice(openIdx, end === -1 ? openIdx + 1400 : end);
  assert.ok(/chatWsUrl\([^)]*_resumeOffset\(\)\)/.test(openBody), '_open resumes the URL from _resumeOffset()');
  assert.ok(/buildChatSubscribeFrame\([^)]*_resumeOffset\(\)\)/.test(openBody), '_open resumes the subscribe frame from _resumeOffset()');
  assert.ok(!/chatWsUrl\([^)]*this\._delivered\)/.test(openBody), '_open no longer resumes from the drain-only _delivered');
});
