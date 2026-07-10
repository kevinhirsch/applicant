// workspace/tests/js/shellWsTransport.test.js
//
// Headless behavioral tests for the shell-WS transport's PURE helpers
// (../../static/js/shellWsTransport.js): the WS URL builder, the run-frame shape,
// the incoming-message classifier, and the exit-code sentinel detector — plus
// source-shape assertions that pin the two load-bearing durability invariants
// (no reconnect; the fallback POST is DEFERRED so the command never double-runs).
//
// Like chatWsTransport.test.js, this does NOT import the module (its browser code
// touches WebSocket/TextEncoder/window at eval time). It reads the REAL source
// and extracts just the pure functions via a balanced-brace slicer, then executes
// that exact text — so reverting a helper flips these assertions red.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC_PATH = fileURLToPath(new URL('../../static/js/shellWsTransport.js', import.meta.url));
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
  if (start === -1) throw new Error(`function ${name} not found in shellWsTransport.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// eslint-disable-next-line no-new-func
function load(...names) {
  const body = names.map((n) => extractFunction(SRC, n)).join('\n');
  return new Function(`${body}\nreturn { ${names.join(', ')} };`)();
}

test('shellWsUrl picks wss for https and ws for http', () => {
  const { shellWsUrl } = load('shellWsUrl');
  assert.equal(shellWsUrl({ protocol: 'https:', host: 'x.io' }), 'wss://x.io/api/shell/ws');
  assert.equal(shellWsUrl({ protocol: 'http:', host: 'y:7000' }), 'ws://y:7000/api/shell/ws');
});

test('buildShellRunFrame carries the command + optional opts (the SAME POST body, no resume)', () => {
  const { buildShellRunFrame } = load('buildShellRunFrame');
  assert.deepEqual(
    buildShellRunFrame({ command: 'ollama pull x', timeout: 0, use_pty: true, use_tmux: true }),
    { type: 'run', command: 'ollama pull x', timeout: 0, use_pty: true, use_tmux: true },
  );
  // Falsy opts are omitted; missing command normalizes to ''.
  assert.deepEqual(buildShellRunFrame({ command: 'echo hi' }), { type: 'run', command: 'echo hi' });
  assert.deepEqual(buildShellRunFrame(null), { type: 'run', command: '' });
  assert.deepEqual(buildShellRunFrame({ command: 'c', use_pty: false }), { type: 'run', command: 'c' });
});

test('parseShellWsMessage classifies server frames', () => {
  const { parseShellWsMessage } = load('parseShellWsMessage');
  assert.deepEqual(
    parseShellWsMessage('{"type":"chunk","seq":0,"data":"data: {\\"stream\\":\\"stdout\\",\\"data\\":\\"hi\\"}\\n\\n"}'),
    { kind: 'chunk', data: 'data: {"stream":"stdout","data":"hi"}\n\n' },
  );
  assert.deepEqual(parseShellWsMessage('{"type":"end","seq":4}'), { kind: 'end' });
  assert.deepEqual(parseShellWsMessage('{"type":"error","error":"nope"}'), { kind: 'error', error: 'nope' });
  // Non-string chunk data, unknown types, and garbage are ignored (never crash).
  assert.equal(parseShellWsMessage('{"type":"chunk","data":123}').kind, 'ignore');
  assert.equal(parseShellWsMessage('not json').kind, 'ignore');
  assert.equal(parseShellWsMessage(null).kind, 'ignore');
  assert.deepEqual(parseShellWsMessage({ type: 'end' }), { kind: 'end' });
});

test('shellChunkIsExit detects the terminal exit_code marker', () => {
  const { shellChunkIsExit } = load('shellChunkIsExit');
  assert.equal(shellChunkIsExit('data: {"exit_code": 0}\n\n'), true);
  assert.equal(shellChunkIsExit('data: {"exit_code": -1}\n\n'), true);
  assert.equal(shellChunkIsExit('data: {"stream": "stdout", "data": "x"}\n\n'), false);
  assert.equal(shellChunkIsExit(''), false);
  assert.equal(shellChunkIsExit(null), false);
});

test('the shell reader NEVER reconnects (no durable buffer to resume) — a dropped socket ends the reader', () => {
  // Unlike the chat reader, a post-open socket close must simply finish() — there
  // is no _open()/reconnect loop and no resume offset, because the shell stream is
  // ephemeral (a fresh subprocess bound to the connection). Assert the source has
  // no reconnect machinery.
  assert.ok(!/_reconnectTimer/.test(SRC), 'shell reader has no reconnect timer');
  assert.ok(!/CHAT_WS_MAX_RECONNECTS|MAX_RECONNECTS/.test(SRC), 'shell reader has no reconnect budget');
  assert.ok(!/setTimeout\([^)]*_open/.test(SRC), 'shell reader does not schedule a reconnect');
  const closeIdx = SRC.indexOf('_onSocketClose() {');
  assert.ok(closeIdx !== -1, '_onSocketClose is present');
  const closeBody = SRC.slice(closeIdx, closeIdx + 300);
  assert.ok(/this\._finish\(\)/.test(closeBody), 'a post-open close ends the reader');
});

test('the fallback POST is DEFERRED (makeSse) so the command runs on exactly one transport', () => {
  // openShellStreamReader must only call makeSse() when the WS did NOT win — on
  // no-WS-support, or in the catch after waitForOpen rejects. It must NOT fetch
  // /api/shell/stream eagerly, or a WS-served run would double-execute the command.
  assert.ok(!/fetch\(['"]\/api\/shell\/stream/.test(SRC), 'the transport never POSTs /api/shell/stream itself (the caller defers it via makeSse)');
  const openIdx = SRC.indexOf('async function openShellStreamReader');
  assert.ok(openIdx !== -1, 'openShellStreamReader is present');
  const openBody = SRC.slice(openIdx);
  // WS success path returns the reader WITHOUT calling makeSse.
  assert.ok(/await reader\.waitForOpen\([^)]*\);\s*[\s\S]*?return reader;/.test(openBody), 'a live WS returns the reader (no POST)');
  // makeSse is the fallback, reached only via no-support early return or the catch.
  assert.ok(/return makeSse\(\);/.test(openBody), 'the SSE fallback defers to makeSse()');
});
