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
