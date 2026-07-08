// workspace/tests/js/applicantRail.test.js
//
// Headless behavioral tests for the P0-3 gadget rail's PURE helpers
// (../../static/js/applicantRail.js): the pipeline roll-up, the pin ordering,
// the guardrails one-liner, the health chip verdict, and the streak counter.
//
// Like applicantPortal.test.js, this does NOT import the module: applicantRail
// statically imports applicantCore.js + applicantReachability.js, whose chain
// pulls ui.js and registers real timers/observers at module-eval time (the
// same headless-hang those files document). So these tests read the REAL
// source and extract just the pure functions (via a balanced-brace slicer, not
// a hand copy) and execute that exact text. Reverting a helper in the source
// changes the extracted text, so these assertions go red on revert and green
// on restore — the same guarantee an import() would give without a browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const RAIL_PATH = fileURLToPath(new URL('../../static/js/applicantRail.js', import.meta.url));
const SRC = readFileSync(RAIL_PATH, 'utf8');

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
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${RAIL_PATH}`);
}

// Finds `function NAME(` even when preceded by `export ` — indexOf lands on the
// `function` keyword, yielding a standalone executable function.
function extractFunction(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`function ${name} not found in applicantRail.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// Extract the `export const _PINNABLE_IDS = [...]` array literal as a plain const.
function extractPinnableIds(src) {
  const m = src.match(/const _PINNABLE_IDS = (\[[^\]]*\]);/);
  if (!m) throw new Error('_PINNABLE_IDS array not found in applicantRail.js');
  return `const _PINNABLE_IDS = ${m[1]};`;
}

// ── _pipelineCounts: tracker board roll-up ────────────────────────────────

test('_pipelineCounts buckets applications by coarse stage and never throws', () => {
  const _pipelineCounts = new Function(`${extractFunction(SRC, '_pipelineCounts')}\nreturn _pipelineCounts;`)();
  assert.equal(typeof _pipelineCounts, 'function');

  const apps = [
    { stage: 'interview_scheduled' },
    { status: 'Interviewing' },
    { bucket: 'offer' },
    { stage: 'submitted' },
    { status: 'applied' },
    { stage: 'discovered' },
    null,
    'not-an-object',
  ];
  const c = _pipelineCounts(apps);
  assert.equal(c.total, 6, 'six well-formed rows counted, malformed skipped');
  assert.equal(c.interview, 2, 'two interview-stage rows');
  assert.equal(c.offer, 1, 'one offer');
  assert.equal(c.submitted, 2, 'submitted + applied');
  assert.equal(c.active, 1, 'discovered falls through to active');

  const empty = _pipelineCounts(undefined);
  assert.equal(empty.total, 0, 'undefined input -> zeroed counts, no throw');
});

// ── _railOrderIds: pinned gadgets float to the top ────────────────────────

test('_railOrderIds floats pinned ids to the top and ignores unknown ids', () => {
  const body = [
    extractPinnableIds(SRC),
    extractFunction(SRC, '_railOrderIds'),
    'return { _railOrderIds, _PINNABLE_IDS };',
  ].join('\n');
  const { _railOrderIds, _PINNABLE_IDS } = new Function(body)();

  // No pins -> default order preserved.
  assert.deepEqual(_railOrderIds([]), _PINNABLE_IDS, 'empty pins -> default order');

  // Pinning 'health' + 'digest' floats them up (in their default relative order).
  const ordered = _railOrderIds(['health', 'digest']);
  assert.equal(ordered[0], 'digest', 'digest precedes health in the default order, so it stays first among pinned');
  assert.equal(ordered[1], 'health', 'health second among pinned');
  assert.deepEqual(new Set(ordered), new Set(_PINNABLE_IDS), 'order is a permutation — nothing dropped or duplicated');

  // Unknown ids never inject a phantom gadget.
  assert.deepEqual(_railOrderIds(['bogus']), _PINNABLE_IDS, 'unknown pin id ignored');
});

// ── _guardrailsLine: cost & pace one-liner ────────────────────────────────

test('_guardrailsLine speaks the "capped for safety" language, with cost only when reported', () => {
  const _guardrailsLine = new Function(`${extractFunction(SRC, '_guardrailsLine')}\nreturn _guardrailsLine;`)();

  const withCost = _guardrailsLine({
    applications_today: 3, daily_target: 20, hard_cap: 30,
    usage_reported: true, cost_today_usd_estimate: 1.2,
  });
  assert.ok(withCost.includes('3 applications'), 'plural noun');
  assert.ok(withCost.includes('~$1.20'), 'cost shown when usage_reported');
  assert.ok(withCost.includes('capped for safety'), 'uses the plain-language cap phrasing, not "hard cap"');
  assert.ok(!withCost.toLowerCase().includes('hard cap'), 'never leaks the internal term');

  const noCost = _guardrailsLine({ applications_today: 1, daily_target: 20, hard_cap: 30, usage_reported: false });
  assert.ok(noCost.includes('1 application'), 'singular noun');
  assert.ok(!noCost.includes('$'), 'no cost when usage not reported');

  assert.equal(_guardrailsLine(null), '', 'null -> empty string, no throw');
});

// ── _healthChip: mirror of the health-panel verdict ───────────────────────

test('_healthChip renders all-real / degraded / offline / gated verdicts', () => {
  const _healthChip = new Function(`${extractFunction(SRC, '_healthChip')}\nreturn _healthChip;`)();

  assert.equal(_healthChip({ engine_available: false }).tone, 'warn', 'offline -> warn');
  assert.equal(_healthChip({ gated: true }).tone, 'muted', 'gated -> muted');
  assert.equal(_healthChip({ all_real: true, capabilities: [{}, {}] }).label, 'All systems real', 'all real');
  const degraded = _healthChip({ all_real: false, capabilities: [{}, {}, {}], degraded: [{}] });
  assert.equal(degraded.label, '1 of 3 degraded', 'counts degraded of total');
  assert.equal(degraded.tone, 'warn');
  assert.equal(_healthChip({ capabilities: [] }).label, 'No report yet', 'no caps yet');
  assert.equal(_healthChip(null), null, 'null -> null (gadget hides)');
});

// ── _streakDays: consecutive-day counter ──────────────────────────────────

test('_streakDays counts back over consecutive local days and resets on a gap', () => {
  const _streakDays = new Function(`${extractFunction(SRC, '_streakDays')}\nreturn _streakDays;`)();
  const DAY = 86400000;
  const now = Date.parse('2026-07-08T12:00:00Z');
  const iso = (offsetDays) => ({ finished_at: new Date(now - offsetDays * DAY).toISOString() });

  assert.equal(_streakDays([iso(0), iso(1), iso(2)], now), 3, 'today + 2 prior days = 3');
  assert.equal(_streakDays([iso(1), iso(2)], now), 2, 'yesterday-anchored streak of 2');
  assert.equal(_streakDays([iso(0), iso(3)], now), 1, 'a gap breaks the streak at 1');
  assert.equal(_streakDays([], now), 0, 'empty -> 0');
  assert.equal(_streakDays([iso(5)], now), 0, 'a run 5 days ago with nothing since -> 0');
});
