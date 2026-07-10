// workspace/tests/js/applicantActivity.test.js
//
// Headless behavioral tests for the always-visible ACTIVITY STATUS STRIP's
// realtime ⇄ poll coordination (../../static/js/applicantActivity.js): the
// STATUS_POLL_MS status poll is now a WS-DOWN FALLBACK only.
//
// Like applicantBell.test.js, this does NOT import the module: applicantActivity
// statically imports applicantCore.js/ui.js, whose chain registers real timers +
// observers at module-eval time (the documented headless hang) and self-boots. So
// these tests read the REAL source and extract just the coordination helpers (via
// a balanced-brace slicer, not a hand copy) and execute that exact text against
// stubbed module state (pollVisible / refreshStatus). Reverting a helper in the
// source changes the extracted text, so these assertions go red on revert and
// green on restore — the same guarantee an import() would give without a browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ACTIVITY_PATH = fileURLToPath(new URL('../../static/js/applicantActivity.js', import.meta.url));
const SRC = readFileSync(ACTIVITY_PATH, 'utf8');

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
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${ACTIVITY_PATH}`);
}

function extractFunction(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in applicantActivity.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// Build a headless harness that runs the REAL sliced coordination helpers against
// stubbed module state. `pollVisible` counts starts (and fires the immediate seed,
// as the real one does) and returns a stop handle; `refreshStatus` counts calls.
function buildHarness() {
  const startSrc = extractFunction(SRC, '_startStatusPollIfNeeded');
  const applySrc = extractFunction(SRC, '_applyRealtimeLive');
  const factory = new Function(`
    let _realtimeLive = false;
    let _statusPollStop = null;
    let pollStarts = 0;
    let pollStops = 0;
    let refreshCalls = 0;
    const STATUS_POLL_MS = 45000;
    // Stub of applicantCore's pollVisible: fires the callback once immediately (its
    // seed) and returns a stop handle — matches the real contract the caller relies on.
    function pollVisible(fn, ms) {
      pollStarts += 1;
      try { fn(); } catch (e) { /* no-op */ }
      return function stop() { pollStops += 1; };
    }
    function refreshStatus() { refreshCalls += 1; }
    ${startSrc}
    ${applySrc}
    return {
      _startStatusPollIfNeeded,
      _applyRealtimeLive,
      state: () => ({ realtimeLive: _realtimeLive, polling: _statusPollStop != null }),
      counts: () => ({ pollStarts, pollStops, refreshCalls }),
    };
  `);
  return factory();
}

// ── (b) realtime DOWN ⇒ the status poll runs (the fallback is never dead) ──

test('realtime down: the STATUS_POLL_MS status poll runs (WS-down fallback stays alive)', () => {
  const h = buildHarness();
  // Boot-equivalent: not live → start the fallback poll.
  h._startStatusPollIfNeeded();
  assert.equal(h.state().polling, true, 'poll is running while the WS is down');
  assert.equal(h.counts().pollStarts, 1, 'exactly one pollVisible poll armed');
  assert.equal(h.counts().refreshCalls, 1, "pollVisible's immediate fire seeds the strip once");
});

// ── (a) realtime LIVE ⇒ no status poll (retired; pushes drive the strip) ──

test('realtime live: the status poll is retired (no redundant poll while pushing)', () => {
  const h = buildHarness();
  // Start down (poll running), then the push channel goes live.
  h._startStatusPollIfNeeded();
  assert.equal(h.state().polling, true, 'poll running before going live');
  h._applyRealtimeLive(true);
  assert.equal(h.state().realtimeLive, true, 'flag flips to live');
  assert.equal(h.state().polling, false, 'poll is retired the moment the WS is live');
  assert.equal(h.counts().pollStops, 1, 'the running poll was torn down (stop handle called)');
  // And a subsequent start request is a no-op while live — no poll sneaks back.
  h._startStatusPollIfNeeded();
  assert.equal(h.state().polling, false, 'no status poll starts while the push channel is live');
  assert.equal(h.counts().pollStarts, 1, 'still only the original poll was ever armed');
});

// ── WS loss RESTORES the fallback poll (never a silent dead UI) ──

test('realtime lost: the fallback poll is restored on WS loss', () => {
  const h = buildHarness();
  h._applyRealtimeLive(true);           // live: no poll
  assert.equal(h.state().polling, false, 'no poll while live');
  h._applyRealtimeLive(false);          // WS lost
  assert.equal(h.state().realtimeLive, false, 'flag flips back to not-live');
  assert.equal(h.state().polling, true, 'the fallback poll is restored so the strip never goes stale');
});
