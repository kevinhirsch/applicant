// workspace/tests/js/applicantRealtime.test.js
//
// Headless behavioral tests for the realtime WS client's PURE helpers
// (../../static/js/applicantRealtime.js): backoff, resume-param building, the
// URL builder, per-channel dedupe on replay, and the plain-language labels.
//
// Like applicantBell.test.js, this does NOT import the module (its self-boot
// touches WebSocket/document at eval time). It reads the REAL source and extracts
// just the pure functions via a balanced-brace slicer, then executes that exact
// text — so reverting a helper flips these assertions red.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC_PATH = fileURLToPath(new URL('../../static/js/applicantRealtime.js', import.meta.url));
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
  if (start === -1) throw new Error(`function ${name} not found in applicantRealtime.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// eslint-disable-next-line no-new-func
function load(...names) {
  const body = names.map((n) => extractFunction(SRC, n)).join('\n');
  return new Function(`${body}\nreturn { ${names.join(', ')} };`)();
}

test('nextBackoffMs grows exponentially and caps at 30s', () => {
  const { nextBackoffMs } = load('nextBackoffMs');
  assert.equal(nextBackoffMs(0), 500);
  assert.equal(nextBackoffMs(1), 1000);
  assert.equal(nextBackoffMs(2), 2000);
  assert.equal(nextBackoffMs(20), 30000); // capped
});

test('buildResumeParam encodes only channels with a real seq', () => {
  const { buildResumeParam } = load('buildResumeParam');
  assert.equal(buildResumeParam({ presence: 3, notif: 0 }), 'presence:3,notif:0');
  assert.equal(buildResumeParam({ presence: -1 }), ''); // nothing seen yet
  assert.equal(buildResumeParam({}), '');
  assert.equal(buildResumeParam(null), '');
});

test('realtimeWsUrl picks wss for https and carries tab + resume', () => {
  const { realtimeWsUrl } = load('realtimeWsUrl', 'buildResumeParam');
  const secure = realtimeWsUrl({ protocol: 'https:', host: 'x.io' }, { presence: 2 }, 't1');
  assert.ok(secure.startsWith('wss://x.io/api/applicant/realtime/ws'));
  assert.ok(secure.includes('tab=t1'));
  assert.ok(secure.includes('resume=presence%3A2'));
  const plain = realtimeWsUrl({ protocol: 'http:', host: 'y:7000' }, {}, '');
  assert.equal(plain, 'ws://y:7000/api/applicant/realtime/ws');
});

test('applyIncoming dedups feature frames by per-channel seq', () => {
  const { applyIncoming } = load('applyIncoming');
  let last = {};
  let r = applyIncoming({ chan: 'presence', type: 'state', seq: 0 }, last);
  assert.equal(r.accept, true);
  last = r.lastSeq;
  // a replayed frame the client already has is dropped (exactly-once)
  r = applyIncoming({ chan: 'presence', type: 'state', seq: 0 }, last);
  assert.equal(r.accept, false);
  // the next live seq is accepted, no gap
  r = applyIncoming({ chan: 'presence', type: 'state', seq: 1 }, last);
  assert.equal(r.accept, true);
  assert.equal(r.lastSeq.presence, 1);
});

test('applyIncoming always accepts sys control frames without tracking seq', () => {
  const { applyIncoming } = load('applyIncoming');
  const r = applyIncoming({ chan: 'sys', type: 'hello', seq: -1 }, { presence: 5 });
  assert.equal(r.accept, true);
  assert.equal(r.lastSeq.presence, 5); // untouched
});

test('presenceLabel is plain-language and white-label', () => {
  const { presenceLabel } = load('presenceLabel');
  assert.equal(presenceLabel(1), 'Just you');
  assert.equal(presenceLabel(0), 'Just you');
  assert.equal(presenceLabel(3), '3 devices connected');
});

test('connectionStateLabel names every state in plain language', () => {
  const { connectionStateLabel } = load('connectionStateLabel');
  assert.equal(connectionStateLabel('open'), 'Live updates on');
  assert.equal(connectionStateLabel('reconnecting'), 'Reconnecting…');
  assert.match(connectionStateLabel('fallback'), /periodic refresh/);
});

test('realtimeLiveDetail is live ONLY when the socket is fully open', () => {
  const { realtimeLiveDetail } = load('realtimeLiveDetail');
  assert.deepEqual(realtimeLiveDetail('open'), { live: true });
  for (const s of ['connecting', 'reconnecting', 'fallback', 'idle']) {
    assert.deepEqual(realtimeLiveDetail(s), { live: false });
  }
});

test('_setState persists the current live flag on window (Greptile #804) so a late-registering Portal can reconcile a socket that opened before its listener existed', () => {
  // The dispatched `applicant:realtime` event is one-shot per edge; persisting the
  // level on `window.__applicantRealtimeLive` is what lets the Portal reconcile on
  // boot instead of staying stuck polling until the next transition.
  const idx = SRC.indexOf('_setState(state)');
  assert.ok(idx !== -1, '_setState is present');
  const body = SRC.slice(idx, idx + 1200);
  assert.ok(
    /window\.__applicantRealtimeLive\s*=\s*!!detail\.live/.test(body),
    '_setState records the current live flag on window before dispatching the edge event',
  );
  // The persisted flag must be set BEFORE the edge event is dispatched.
  assert.ok(
    body.indexOf('window.__applicantRealtimeLive') < body.indexOf("new CustomEvent('applicant:realtime'"),
    'the window flag is persisted before the one-shot event is dispatched',
  );
});

test('notifRefresh drives the existing poll path via Portal refreshBadge', () => {
  const { notifRefresh } = load('notifRefresh');
  let calls = 0;
  global.window = { applicantPortalModule: { refreshBadge: () => { calls += 1; } } };
  try {
    // A notif frame reuses the Portal's refreshBadge (badge + notifs + toasts +
    // the applicant:pending-changed fan-out) — it does NOT rebuild any of them.
    assert.equal(notifRefresh(), true);
    assert.equal(calls, 1);
  } finally {
    delete global.window;
  }
});

test('notifRefresh falls back to the pending-changed contract when Portal is absent', () => {
  const { notifRefresh } = load('notifRefresh');
  const events = [];
  global.window = {}; // no applicantPortalModule mounted on this surface
  global.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
  global.document = { dispatchEvent: (e) => { events.push(e); } };
  try {
    assert.equal(notifRefresh(), false);
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'applicant:pending-changed');
  } finally {
    delete global.window;
    delete global.document;
    delete global.CustomEvent;
  }
});

// ── Phase 3 agent co-steer helpers ───────────────────────────────────────────

test('agentEventSummary prefers the run intent and falls back to a plain line', () => {
  const { agentEventSummary } = load('agentEventSummary');
  assert.equal(agentEventSummary({ data: { intent: 'Tailoring your resume.' } }), 'Tailoring your resume.');
  assert.equal(agentEventSummary({ data: {} }), 'Working on your job search');
  assert.equal(agentEventSummary(null), 'Working on your job search');
});

test('buildAgentPauseFrame shapes an agent/pause envelope carrying the campaign', () => {
  const { buildAgentPauseFrame } = load('buildAgentPauseFrame');
  assert.deepEqual(buildAgentPauseFrame('c-1'), {
    chan: 'agent', type: 'pause', seq: 0, data: { campaign_id: 'c-1' },
  });
});

test('buildAgentRedirectFrame carries only the provided run-config fields, never approve', () => {
  const { buildAgentRedirectFrame } = load('buildAgentRedirectFrame');
  const full = buildAgentRedirectFrame('c-1', { run_mode: 'until_n_viable', throughput_target: 7, schedule: { target_viable: 5 } });
  assert.deepEqual(full, {
    chan: 'agent',
    type: 'redirect',
    seq: 0,
    data: { campaign_id: 'c-1', run_mode: 'until_n_viable', throughput_target: 7, schedule: { target_viable: 5 } },
  });
  // Absent fields are omitted (a bare redirect only names the campaign).
  assert.deepEqual(buildAgentRedirectFrame('c-2', {}), {
    chan: 'agent', type: 'redirect', seq: 0, data: { campaign_id: 'c-2' },
  });
  // A REDIRECT envelope is never an approve/submit — that verb isn't buildable here.
  assert.notEqual(full.type, 'approve');
});

test('buildAgentApproveFrame shapes an agent/approve envelope carrying the document id', () => {
  const { buildAgentApproveFrame } = load('buildAgentApproveFrame');
  // PURE TRANSPORT: it only names the document to approve. The engine authorizes it
  // against the SAME owner-gated review-before-submit gate the HTTP approve uses.
  assert.deepEqual(buildAgentApproveFrame('d-1'), {
    chan: 'agent', type: 'approve', seq: 0, data: { document_id: 'd-1' },
  });
  // Defensive coercion: a missing id becomes an empty string (engine refuses it), never a throw.
  assert.deepEqual(buildAgentApproveFrame(), {
    chan: 'agent', type: 'approve', seq: 0, data: { document_id: '' },
  });
});

test('agentRefresh live-renders through the existing Activity strip (refreshStatus) + a DOM event', () => {
  const { agentRefresh, agentEventSummary } = load('agentRefresh', 'agentEventSummary');
  let refreshed = 0;
  const events = [];
  global.window = { applicantActivityModule: { refreshStatus: () => { refreshed += 1; } } };
  global.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
  global.document = { dispatchEvent: (e) => { events.push(e); } };
  try {
    assert.equal(agentRefresh({ data: { intent: 'Reviewing 3 roles.' } }), true);
    assert.equal(refreshed, 1); // reused the existing strip's refresh, not a rebuild
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'applicant:agent-event');
    assert.equal(events[0].detail.summary, 'Reviewing 3 roles.');
  } finally {
    delete global.window;
    delete global.document;
    delete global.CustomEvent;
  }
});
