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
  // Anchor on LOCAL noon (not a UTC instant): _streakDays keys days off local
  // date components, so a UTC-anchored fixture could cross a day boundary on a
  // runner far from UTC. Local noon ± whole days stays inside the same local
  // day even across a DST shift.
  const now = new Date(2026, 6, 8, 12, 0, 0).getTime();
  const iso = (offsetDays) => ({ finished_at: new Date(now - offsetDays * DAY).toISOString() });

  assert.equal(_streakDays([iso(0), iso(1), iso(2)], now), 3, 'today + 2 prior days = 3');
  assert.equal(_streakDays([iso(1), iso(2)], now), 2, 'yesterday-anchored streak of 2');
  assert.equal(_streakDays([iso(0), iso(3)], now), 1, 'a gap breaks the streak at 1');
  assert.equal(_streakDays([], now), 0, 'empty -> 0');
  assert.equal(_streakDays([iso(5)], now), 0, 'a run 5 days ago with nothing since -> 0');
});

// ── mountApplicantRail: the WS-down fallback poll ─────────────────────────────
//
// The rail's independent data poll is now a WS-DOWN FALLBACK: while the realtime
// push channel is live the rail refreshes off `applicant:pending-changed` +
// `applicant:data-changed`, so the `setInterval` timer is RETIRED; on WS loss the
// visibility-aware poll is RESTORED (the honesty invariant: no silent dead UI).
//
// Like the pure-helper tests above this does NOT import the module (its self-boot
// touches document/timers at eval time). It slices the REAL `mountApplicantRail`
// body and runs it against fabricated document/window/timer stubs — so reverting the
// `!_realtimeLive` gate or the realtime wiring flips these assertions red.
function runMount({ windowLive = false, visibility = 'visible' } = {}) {
  const mountSrc = extractFunction(SRC, 'mountApplicantRail');
  const prelude = `
    let _mounted = false;
    let _pollStop = null;
    let _realtimeLive = false;
    const POLL_MS = 45000;
    const state = { intervals: 0, refreshes: 0, active: new Set(), timerFn: null, listeners: {} };
    let _seq = 1;
    function setInterval(fn, ms) { state.intervals += 1; state.lastMs = ms; state.timerFn = fn; const id = _seq++; state.active.add(id); return id; }
    function clearInterval(id) { state.active.delete(id); }
    function _refresh() { state.refreshes += 1; }
    const rail = { classList: { toggle() {}, contains() { return false; } }, setAttribute() {}, querySelector() { return null; }, innerHTML: '' };
    function _railEl() { return rail; }
    function _ensureScaffold() { return rail; }
    const window = { __applicantRealtimeLive: ${windowLive ? 'true' : 'false'} };
    const document = {
      visibilityState: '${visibility}',
      addEventListener(type, fn) { (state.listeners[type] = state.listeners[type] || []).push(fn); },
      removeEventListener() {},
    };
    // Fire a realtime liveness edge into the listeners the mount registered.
    state.emitRealtime = (live) => { for (const fn of (state.listeners['applicant:realtime'] || [])) fn({ detail: { live } }); };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(`${prelude}\n${mountSrc}\nmountApplicantRail();\nreturn state;`)();
}

test('mountApplicantRail runs NO independent interval poll while the realtime WS is live', () => {
  // Socket already open before mount (window.__applicantRealtimeLive) — the reconcile
  // retires any armed timer, so there is no live fallback interval.
  const st = runMount({ windowLive: true });
  assert.equal(st.active.size, 0, 'push is live -> the fallback interval is retired (no timer running)');
  // It still painted immediately (the seed tick + the retire catch-up ran through _refresh).
  assert.ok(st.refreshes >= 1, 'the rail still seed-paints even with the poll retired');
});

test('mountApplicantRail RESTORES the visibility-aware poll when the realtime WS is down (no silent dead UI)', () => {
  // No live socket at mount: the fallback poll must be armed so the rail keeps updating.
  const st = runMount({ windowLive: false });
  assert.equal(st.active.size, 1, 'WS down -> exactly one fallback interval is running');
  assert.equal(st.lastMs, 45000, 'the fallback polls at the slow 45s cadence');
  // The armed timer really refreshes the rail when it fires.
  const before = st.refreshes;
  st.timerFn();
  assert.equal(st.refreshes, before + 1, 'the fallback interval refreshes the rail when it fires');
});

test('mountApplicantRail retires then restores the poll as the realtime WS flips live/down', () => {
  // Start WS-down: the fallback poll is running.
  const st = runMount({ windowLive: false });
  assert.equal(st.active.size, 1, 'starts on the fallback poll while WS is down');
  // WS comes up: retire the poll (push drives refreshes now).
  st.emitRealtime(true);
  assert.equal(st.active.size, 0, 'realtime live -> the fallback poll is retired');
  // WS drops again: restore the poll so the rail never silently goes stale.
  st.emitRealtime(false);
  assert.equal(st.active.size, 1, 'realtime down -> the fallback poll is restored');
});
