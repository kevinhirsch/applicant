// workspace/tests/js/emailInbox.test.js
//
// Headless behavioral tests for the email inbox's IMAP-IDLE relay gate — the
// PURE helpers in ../../static/js/emailInbox.js that decide whether the 60s
// unread poll runs. Like applicantRealtime.test.js, this does NOT import the
// module (its top-level imports touch other modules); it reads the REAL source
// and extracts just the pure functions via a balanced-brace slicer, then runs
// that exact text — so reverting the honesty gate flips these assertions red.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC_PATH = fileURLToPath(new URL('../../static/js/emailInbox.js', import.meta.url));
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
  if (start === -1) throw new Error(`function ${name} not found in emailInbox.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// eslint-disable-next-line no-new-func
function load(...names) {
  const body = names.map((n) => extractFunction(SRC, n)).join('\n');
  return new Function(`${body}\nreturn { ${names.join(', ')} };`)();
}

test('shouldPollUnread: the poll runs whenever the relay is NOT live (honesty gate)', () => {
  const { shouldPollUnread } = load('shouldPollUnread');
  // Live push ⇒ suppress the poll.
  assert.equal(shouldPollUnread(true), false);
  // Every non-live state keeps the poll running (no silent dead inbox).
  assert.equal(shouldPollUnread(false), true);
  assert.equal(shouldPollUnread(undefined), true);
  assert.equal(shouldPollUnread(null), true);
});

test('emailRelayAction classifies each relay frame', () => {
  const { emailRelayAction } = load('emailRelayAction');
  assert.equal(emailRelayAction({ type: 'email:unread-changed' }), 'refresh');
  assert.equal(emailRelayAction({ type: 'live' }), 'suppress-poll');
  assert.equal(emailRelayAction({ type: 'down' }), 'resume-poll');
  assert.equal(emailRelayAction({ type: 'hello' }), 'none');
  assert.equal(emailRelayAction(null), 'none');
});

test('applyEmailRelayAction: a LIVE push suppresses the poll', () => {
  const { applyEmailRelayAction, emailRelayAction } = load('applyEmailRelayAction', 'emailRelayAction');
  const calls = { start: 0, stop: 0, refresh: 0 };
  const hooks = {
    startPoll: () => { calls.start += 1; },
    stopPoll: () => { calls.stop += 1; },
    refresh: () => { calls.refresh += 1; },
  };
  const acted = applyEmailRelayAction(emailRelayAction({ type: 'live' }), hooks);
  assert.equal(acted, 'suppress-poll');
  assert.equal(calls.stop, 1);   // poll stopped
  assert.equal(calls.start, 0);  // never started
});

test('applyEmailRelayAction: a DOWN frame resumes the poll (and refreshes once)', () => {
  const { applyEmailRelayAction, emailRelayAction } = load('applyEmailRelayAction', 'emailRelayAction');
  const calls = { start: 0, stop: 0, refresh: 0 };
  const hooks = {
    startPoll: () => { calls.start += 1; },
    stopPoll: () => { calls.stop += 1; },
    refresh: () => { calls.refresh += 1; },
  };
  const acted = applyEmailRelayAction(emailRelayAction({ type: 'down' }), hooks);
  assert.equal(acted, 'resume-poll');
  assert.equal(calls.start, 1);   // poll resumed — the fallback is honest
  assert.equal(calls.refresh, 1); // refreshed so the count is fresh on fallback
  assert.equal(calls.stop, 0);
});

test('applyEmailRelayAction: a new-mail nudge refreshes without touching the poll', () => {
  const { applyEmailRelayAction, emailRelayAction } = load('applyEmailRelayAction', 'emailRelayAction');
  const calls = { start: 0, stop: 0, refresh: 0 };
  const hooks = {
    startPoll: () => { calls.start += 1; },
    stopPoll: () => { calls.stop += 1; },
    refresh: () => { calls.refresh += 1; },
  };
  const acted = applyEmailRelayAction(emailRelayAction({ type: 'email:unread-changed' }), hooks);
  assert.equal(acted, 'refresh');
  assert.equal(calls.refresh, 1);
  assert.equal(calls.start, 0);
  assert.equal(calls.stop, 0);
});

// Build a hermetic scope for the STATEFUL _connectEmailRelay: inject a fake
// WebSocket + captured timers so the reconnect/backoff and the staleness
// watchdog can be driven deterministically. Slices the real function bodies
// (with emailRelayAction/applyEmailRelayAction) so a regression flips this red.
function loadRelayScope() {
  const body = ['emailRelayAction', 'applyEmailRelayAction', '_connectEmailRelay']
    .map((n) => extractFunction(SRC, n)).join('\n');
  const preamble = `
    const timers = [];
    let _emailRelay = null;
    let _emailRelayStaleTimer = null;
    const calls = { start: 0, stop: 0, refresh: 0, close: 0, wsNew: 0 };
    function _startUnreadPoll() { calls.start += 1; }
    function _stopUnreadPoll() { calls.stop += 1; }
    function _refreshUnreadCount() { calls.refresh += 1; }
    function setTimeout(fn, ms) { timers.push({ fn, ms }); return timers.length; }
    function clearTimeout(_id) { /* no-op for the test clock */ }
    const window = { location: { protocol: 'http:', host: 'inbox.test' } };
    class WebSocket {
      constructor(url) { calls.wsNew += 1; this.url = url; _emailRelay = this;
        this.onopen = null; this.onmessage = null; this.onclose = null; this.onerror = null; }
      close() { calls.close += 1; if (this.onclose) this.onclose(); }
    }
  `;
  const tail = `
    return {
      calls, timers,
      connect: _connectEmailRelay,
      socket: () => _emailRelay,
      // Fire the most-recently-scheduled timer (the pending stale watchdog, then
      // after it force-closes, the pending reconnect). Each call site has exactly
      // one relevant pending timer, so "latest" is unambiguous.
      driveLatest: () => {
        if (!timers.length) throw new Error('no pending timer to drive');
        timers[timers.length - 1].fn();
      },
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(`${preamble}\n${body}\n${tail}`)();
}

test('_connectEmailRelay: a stale live socket is force-closed AND a reconnect is scheduled', () => {
  const scope = loadRelayScope();
  scope.connect();
  assert.equal(scope.calls.wsNew, 1, 'a relay socket is opened on connect');
  const ws = scope.socket();

  // A `live` frame doubles as a heartbeat and arms the staleness watchdog.
  ws.onmessage({ data: JSON.stringify({ type: 'live' }) });
  assert.equal(scope.timers.length >= 1, true, 'the stale watchdog is armed on a live frame');

  // Fire the stale watchdog (heartbeats went silent though the socket never closed).
  const startBefore = scope.calls.start;
  scope.driveLatest();
  // The honest fallback poll starts...
  assert.equal(scope.calls.start > startBefore, true, 'stale ⇒ fallback poll starts');
  // ...AND the half-dead socket is force-closed so onclose drives the reconnect.
  assert.equal(scope.calls.close >= 1, true, 'stale ⇒ socket force-closed');

  // onclose scheduled a reconnect; firing it opens a fresh socket (self-heal).
  scope.driveLatest();
  assert.equal(scope.calls.wsNew, 2, 'onclose ⇒ reconnect opens a new socket');
});
