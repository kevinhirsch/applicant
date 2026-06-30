// workspace/tests/js/front_door.test.js
//
// node:test entrypoint for the front-door JS behavioral suite.
//
// The real assertions live in ./runner.js — a zero-dependency harness that
// dynamically import()s the front-door ES modules and asserts genuine, stable
// facts about their exports and pure helpers (no `assert(true)` filler). This
// thin wrapper exposes that same suite to Node's built-in test runner so it is
// discoverable by `node --test` (and therefore by `npm test`), while keeping
// runner.js as the single source of truth that also runs in the browser.
//
// Run: `node --test` (from workspace/) or `npm test`.

import test from 'node:test';
import assert from 'node:assert/strict';
import { run } from './runner.js';

test('front-door JS modules pass their behavioral assertions', async () => {
  const res = await run();
  // Surface each failing assertion in the node:test output before the gate.
  for (const f of res.failures) {
    // eslint-disable-next-line no-console
    console.error('  FAIL  ' + f);
  }
  assert.equal(res.failed, 0, `${res.failed} front-door JS assertion(s) failed`);
  // Guard against a vacuous green: the suite must actually run real assertions.
  assert.ok(res.passed > 0, 'expected at least one passing behavioral assertion');
});
