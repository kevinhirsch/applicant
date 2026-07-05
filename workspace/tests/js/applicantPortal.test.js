// workspace/tests/js/applicantPortal.test.js
//
// Behavioral regression tests for three lens-10 notification-center findings
// fixed in ../../static/js/applicantPortal.js:
//   #40 — notification rows now show a relative-time affordance ("5m ago").
//   #41 — the `digest` kind gets its own label/accent instead of collapsing
//         onto the generic `info` "Update" tag.
//   #44 — refreshBadge's catch keeps the last-painted badge count instead of
//         zeroing it on a transient fetch error.
//
// Why this file does NOT `import()` applicantPortal.js the way runner.js
// imports its eight modules: those eight were deliberately chosen because
// they are pure ES modules that touch no browser globals at import time.
// applicantPortal.js is not one of them — importing it (even under a fairly
// thorough hand-rolled DOM stub covering document/window/localStorage/
// MutationObserver/ResizeObserver/IntersectionObserver/requestAnimationFrame/
// HTMLInputElement/fetch) still transitively hangs the Node process, because
// its static import chain pulls in ui.js -> colorPicker.js/tileManager.js/
// modalSnap.js, which register real timers/observers against `document.body`
// at MODULE-EVAL time — unrelated machinery this fix doesn't touch. Building
// a full DOM (jsdom or similar) is out of scope (no new dependency to add,
// per this fix's constraints), so per the "add a focused assertion where
// feasible" fallback, these tests read the REAL source of the file and
// extract just the changed functions/consts (via a small balanced-brace
// slicer, not a hand copy) and execute that exact text with minimal
// dependency stubs. Reverting the fix in applicantPortal.js changes the
// extracted text itself, so these assertions go red on revert and green on
// restore — the same regression guarantee `import()` would give, without
// needing a browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const PORTAL_PATH = fileURLToPath(new URL('../../static/js/applicantPortal.js', import.meta.url));
const SRC = readFileSync(PORTAL_PATH, 'utf8');

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
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${PORTAL_PATH}`);
}

function extractFunction(src, name) {
  // Prefer the `async function NAME(` form so async functions (e.g.
  // refreshBadge) keep their `async` keyword — dropping it would leave a
  // plain function containing `await`, a SyntaxError.
  const asyncMarker = `async function ${name}(`;
  const plainMarker = `function ${name}(`;
  let start = src.indexOf(asyncMarker);
  if (start === -1) start = src.indexOf(plainMarker);
  if (start === -1) throw new Error(`function ${name} not found in applicantPortal.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

function extractConstObject(src, name) {
  const marker = `const ${name} = {`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`const ${name} not found in applicantPortal.js`);
  const braceOpen = start + marker.length - 1;
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen) + ';';
}

// Minimal, faithful-enough esc() for these tests only (mirrors applicantCore.js's
// esc() fallback branch — the real esc() just delegates to ui.js's, which is
// exactly the heavy import chain these tests avoid pulling in).
const ESC_STUB = `function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}`;

// ── #40: relative-time affordance on notification rows ────────────────────

test('_notifAgeText (finding #40) renders a short relative-time string from created_at', () => {
  const body = `${extractFunction(SRC, '_notifTs')}\n${extractFunction(SRC, '_notifAgeText')}\nreturn _notifAgeText;`;
  // eslint-disable-next-line no-new-func
  const _notifAgeText = new Function(body)();

  assert.equal(typeof _notifAgeText, 'function', '_notifAgeText should exist as a real function in the source');

  const now = Date.now();
  const iso = (ms) => new Date(now - ms).toISOString();

  assert.equal(_notifAgeText({ created_at: iso(5 * 60 * 1000) }), '5m ago', '5 minutes old');
  assert.equal(_notifAgeText({ created_at: iso(2 * 60 * 60 * 1000) }), '2h ago', '2 hours old');
  assert.equal(_notifAgeText({ created_at: iso(3 * 24 * 60 * 60 * 1000) }), '3d ago', '3 days old');
  assert.equal(_notifAgeText({ created_at: iso(10 * 1000) }), 'just now', 'under a minute old');
  assert.equal(_notifAgeText({ created_at: null }), '', 'no created_at -> no age string');
  assert.equal(_notifAgeText({}), '', 'missing field entirely -> no age string');
});

test('_renderNotifRow (finding #40) actually includes the age text in the rendered row', () => {
  const body = [
    ESC_STUB,
    extractFunction(SRC, '_notifTs'),
    extractFunction(SRC, '_notifAgeText'),
    extractConstObject(SRC, '_NOTIF_KIND_LABEL'),
    extractFunction(SRC, '_renderNotifRow'),
    'return { _renderNotifRow };',
  ].join('\n');
  // eslint-disable-next-line no-new-func
  const { _renderNotifRow } = new Function(body)();

  const html = _renderNotifRow({
    id: 'n1', kind: 'info', title: 'Digest ready', body: '',
    created_at: new Date(Date.now() - 42 * 60 * 1000).toISOString(),
  });
  assert.ok(html.includes('42m ago'), `expected the row HTML to include "42m ago", got: ${html}`);
});

// ── #41: `digest` no longer collapses onto generic `info` ─────────────────

test('_NOTIF_KIND_LABEL (finding #41) gives `digest` its own label, distinct from `info`', () => {
  const body = `${extractConstObject(SRC, '_NOTIF_KIND_LABEL')}\nreturn _NOTIF_KIND_LABEL;`;
  // eslint-disable-next-line no-new-func
  const labels = new Function(body)();

  assert.notEqual(labels.digest, labels.info, 'digest and info must render different plain-language tags');
  assert.equal(labels.info, 'Update', 'info keeps its existing "Update" tag');
  assert.ok(labels.digest && labels.digest !== 'Update', 'digest gets its own tag, not the generic "Update"');
});

test('_renderNotifRow (finding #41) renders visibly different output for `digest` vs `info`', () => {
  const body = [
    ESC_STUB,
    extractFunction(SRC, '_notifTs'),
    extractFunction(SRC, '_notifAgeText'),
    extractConstObject(SRC, '_NOTIF_KIND_LABEL'),
    extractFunction(SRC, '_renderNotifRow'),
    'return { _renderNotifRow };',
  ].join('\n');
  // eslint-disable-next-line no-new-func
  const { _renderNotifRow } = new Function(body)();

  const digestHtml = _renderNotifRow({ id: 'd1', kind: 'digest', title: '', body: '' });
  const infoHtml = _renderNotifRow({ id: 'i1', kind: 'info', title: '', body: '' });

  assert.notEqual(digestHtml, infoHtml, 'a digest row and an info row must not render identically');
  assert.ok(!digestHtml.includes('>Update<'), 'the digest row should not carry the generic "Update" tag text');
});

// ── #44: badge keeps the last-known count on a transient fetch error ──────

test('refreshBadge (finding #44) keeps the last-painted count instead of zeroing on a transient fetch error', async () => {
  const harness = `
    let _lastBadgeCount = 3; // simulates a prior successful "3 waiting" paint
    const API = '/api/applicant/portal';
    let _fetchImpl = null;
    async function _fetchJSON(url) { return _fetchImpl(url); }
    const _setBadgeCalls = [];
    function _setBadge(n) {
      _setBadgeCalls.push(n);
      _lastBadgeCount = Math.max(0, Number(n) || 0);
    }
    async function _loadNotifs() {
      throw new Error('_loadNotifs must not be reached when the pending/count fetch throws');
    }

    ${extractFunction(SRC, 'refreshBadge')}

    return {
      run: refreshBadge,
      setFetchImpl: (f) => { _fetchImpl = f; },
      getSetBadgeCalls: () => _setBadgeCalls.slice(),
    };
  `;
  // eslint-disable-next-line no-new-func
  const { run, setFetchImpl, getSetBadgeCalls } = new Function(harness)();

  setFetchImpl(() => { throw new Error('simulated transient network blip'); });
  await run();

  const calls = getSetBadgeCalls();
  assert.equal(calls.length, 1, 'refreshBadge should paint the badge exactly once on a transient error (via the catch), never via _loadNotifs');
  assert.equal(calls[0], 3, `expected the badge to keep the last-known count (3) on a transient error, but it was set to ${calls[0]}`);
});

test('refreshBadge (finding #44, regression guard) still zeroes the badge when the engine explicitly reports itself unreachable', async () => {
  // Distinguishes the real fix (don't zero on a THROWN/transient error) from
  // an over-correction that would also stop zeroing on a genuine, successfully
  // -fetched "engine_available: false" signal — that state is intentionally
  // still zeroed (the modal's own offline copy already covers it).
  const harness = `
    let _lastBadgeCount = 3;
    const API = '/api/applicant/portal';
    let _fetchImpl = null;
    async function _fetchJSON(url) { return _fetchImpl(url); }
    const _setBadgeCalls = [];
    function _setBadge(n) {
      _setBadgeCalls.push(n);
      _lastBadgeCount = Math.max(0, Number(n) || 0);
    }
    async function _loadNotifs() {
      throw new Error('_loadNotifs must not be reached when engine_available is false');
    }

    ${extractFunction(SRC, 'refreshBadge')}

    return {
      run: refreshBadge,
      setFetchImpl: (f) => { _fetchImpl = f; },
      getSetBadgeCalls: () => _setBadgeCalls.slice(),
    };
  `;
  // eslint-disable-next-line no-new-func
  const { run, setFetchImpl, getSetBadgeCalls } = new Function(harness)();

  setFetchImpl(async () => ({ engine_available: false }));
  await run();

  const calls = getSetBadgeCalls();
  assert.equal(calls.length, 1, 'refreshBadge should paint the badge exactly once');
  assert.equal(calls[0], 0, 'an explicit engine_available:false should still zero the badge (not a transient blip)');
});

// ── #39 / #45: action-required arrivals now toast; quiet hours gates both
// in-tab toasts and OS desktop notifications ─────────────────────────────
//
// Same "extract the real source, execute it headlessly" pattern as above.
// `_toastNew` pulls in a small tree of real helpers (`_isActionArrival`,
// `_notifSeenTs`/`_setNotifSeenTs`, and the new quiet-hours trio
// `_refreshQuietHoursCfg`/`_parseHHMM`/`_isQuietHoursNow`) — all extracted
// verbatim so a revert of the fix (in any of those functions) goes red here.
// The one deliberate override is `_minutesNowInTz`: it reads the real wall
// clock, which this suite cannot control, so a second `function
// _minutesNowInTz(...)` declaration is appended AFTER the extracted real one
// — function declarations in the same scope keep only the LAST binding, so
// this override wins while every other function stays the genuine source.

const NOTIF_SEEN_KEY_LITERAL = (SRC.match(/const NOTIF_SEEN_KEY = '([^']+)'/) || [])[1];
assert.ok(NOTIF_SEEN_KEY_LITERAL, 'could not find NOTIF_SEEN_KEY in applicantPortal.js — has it been renamed?');

function buildToastHarness() {
  const harness = `
    const NOTIF_SEEN_KEY = ${JSON.stringify(NOTIF_SEEN_KEY_LITERAL)};
    const _store = new Map();
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };

    let _fetchImpl = async () => ({ enabled: false });
    const _fetchCalls = [];
    async function _fetchJSON(url) { _fetchCalls.push(url); return _fetchImpl(url); }

    const _toastCalls = [];
    function _toast(msg) { _toastCalls.push(msg); }

    const _toastActionCalls = [];
    function _toastAction(msg, actionLabel, onAction) {
      _toastActionCalls.push({ msg, actionLabel, onAction });
    }

    let _openPortalCalls = 0;
    function openApplicantPortal() { _openPortalCalls += 1; }

    ${extractFunction(SRC, '_notifTs')}
    ${extractFunction(SRC, '_notifSeenTs')}
    ${extractFunction(SRC, '_setNotifSeenTs')}
    ${extractFunction(SRC, '_isInformational')}
    ${extractFunction(SRC, '_isActionArrival')}
    ${extractFunction(SRC, '_refreshQuietHoursCfg')}
    ${extractFunction(SRC, '_parseHHMM')}
    ${extractFunction(SRC, '_minutesNowInTz')}
    // Test override (see file-header comment): last declaration wins.
    let _fixedNowMinutes = 12 * 60;
    function _minutesNowInTz() { return _fixedNowMinutes; }
    ${extractFunction(SRC, '_isQuietHoursNow')}
    let _quietHoursCfg = null;
    let _quietHoursFetchedAt = 0;
    const QUIET_HOURS_TTL_MS = 5 * 60 * 1000;

    // Real _maybeDesktopNotify, minus the actual browser Notification API
    // (undefined in Node) — its OWN quiet-hours gate is exercised for real
    // (the \`if (_isQuietHoursNow(_quietHoursCfg)) return;\` line at the top),
    // we just record whether it got far enough to attempt a notification.
    const _desktopAttempts = [];
    ${extractFunction(SRC, '_maybeDesktopNotify').replace(
      "if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;",
      "_desktopAttempts.push(n); return; // stop before touching the real Notification API",
    )}

    ${extractFunction(SRC, '_toastNew')}

    return {
      run: _toastNew,
      seedSeenTs: (ts) => { _store.set(NOTIF_SEEN_KEY, String(ts)); },
      setFetchImpl: (f) => { _fetchImpl = f; },
      setNowMinutes: (m) => { _fixedNowMinutes = m; },
      getFetchCalls: () => _fetchCalls.slice(),
      getToastCalls: () => _toastCalls.slice(),
      getToastActionCalls: () => _toastActionCalls.slice(),
      getDesktopAttempts: () => _desktopAttempts.slice(),
      getOpenPortalCalls: () => _openPortalCalls,
      getSeenTs: () => _store.get(NOTIF_SEEN_KEY),
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

test('_toastNew (finding #39) toasts a newly-arrived action-required item with an "Open Pending" action, alongside a normal informational toast', async () => {
  const h = buildToastHarness();
  h.seedSeenTs(1000); // not a first-ever load
  h.setFetchImpl(async () => ({ enabled: false })); // quiet hours off
  h.setNowMinutes(12 * 60);

  const actionItem = {
    id: 'a1', kind: 'action', title: 'A 2FA prompt needs you', created_at: new Date(3000).toISOString(),
  };
  const infoItem = {
    id: 'i1', kind: 'info', title: 'Digest ready', created_at: new Date(2000).toISOString(),
  };

  await h.run([actionItem, infoItem]);

  const actionCalls = h.getToastActionCalls();
  assert.equal(actionCalls.length, 1, 'exactly one action-style toast should fire for the new action-required arrival');
  assert.equal(actionCalls[0].msg, 'A 2FA prompt needs you');
  assert.equal(actionCalls[0].actionLabel, 'Open Pending', 'the action toast should offer an "Open Pending" affordance');

  const plainCalls = h.getToastCalls();
  assert.ok(plainCalls.includes('Digest ready'), 'the informational arrival must still toast as before');

  // The action toast's action must actually open the Portal (reusing the
  // existing _toastAction seam), not just carry inert label text.
  actionCalls[0].onAction();
  assert.equal(h.getOpenPortalCalls(), 1, 'clicking "Open Pending" should open the Portal');

  assert.equal(Number(h.getSeenTs()), Date.parse(actionItem.created_at), 'the seen-marker should advance to the newest arrival across BOTH kinds');
});

test('_toastNew (finding #39, regression guard) never double-toasts the same action item on a later poll', async () => {
  const h = buildToastHarness();
  h.seedSeenTs(1000);
  h.setFetchImpl(async () => ({ enabled: false }));

  const actionItem = { id: 'a1', kind: 'action', title: 'A 2FA prompt needs you', created_at: new Date(3000).toISOString() };

  await h.run([actionItem]);
  assert.equal(h.getToastActionCalls().length, 1, 'first poll toasts the new action item once');

  // Simulate the next 60s poll re-delivering the SAME (still-open) action row.
  await h.run([actionItem]);
  assert.equal(h.getToastActionCalls().length, 1, 'a second poll carrying the same item must not toast it again');
});

test('_toastNew (finding #45) suppresses both the toast and the desktop-notification attempt during the configured quiet-hours window', async () => {
  const h = buildToastHarness();
  h.seedSeenTs(1000);
  // Overnight window 22:00-07:00; "now" forced to 23:30 (inside the window).
  h.setFetchImpl(async () => ({ enabled: true, start: '22:00', end: '07:00', tz: '' }));
  h.setNowMinutes(23 * 60 + 30);

  const actionItem = { id: 'a1', kind: 'action', title: 'A 2FA prompt needs you', created_at: new Date(3000).toISOString() };
  const infoItem = { id: 'i1', kind: 'info', title: 'Digest ready', created_at: new Date(2000).toISOString() };

  await h.run([actionItem, infoItem]);

  assert.equal(h.getToastActionCalls().length, 0, 'quiet hours must suppress the action-required toast');
  assert.equal(h.getToastCalls().length, 0, 'quiet hours must suppress the informational toast');
  assert.equal(h.getDesktopAttempts().length, 0, 'quiet hours must suppress the desktop-notification attempt too');

  // The marker still advances so nothing re-toasts in a burst once quiet
  // hours ends.
  assert.equal(Number(h.getSeenTs()), Date.parse(actionItem.created_at), 'the seen-marker must still advance during quiet hours');
});

test('_toastNew (finding #45) toasts normally once "now" is outside the configured quiet-hours window', async () => {
  const h = buildToastHarness();
  h.seedSeenTs(1000);
  h.setFetchImpl(async () => ({ enabled: true, start: '22:00', end: '07:00', tz: '' }));
  h.setNowMinutes(12 * 60); // noon — outside the 22:00-07:00 window

  const infoItem = { id: 'i1', kind: 'info', title: 'Digest ready', created_at: new Date(2000).toISOString() };
  await h.run([infoItem]);

  assert.ok(h.getToastCalls().includes('Digest ready'), 'outside the quiet-hours window, toasting proceeds as normal');
  assert.equal(h.getDesktopAttempts().length, 1, 'outside quiet hours, a desktop-notification attempt should be made');
});

test('_refreshQuietHoursCfg (finding #45) reads the EXISTING quiet-hours setup proxy — no new engine endpoint', async () => {
  const h = buildToastHarness();
  h.seedSeenTs(1000);
  h.setFetchImpl(async () => ({ enabled: false }));

  await h.run([{ id: 'i1', kind: 'info', title: 'Digest ready', created_at: new Date(2000).toISOString() }]);

  assert.ok(
    h.getFetchCalls().includes('/api/applicant/setup/channels/quiet-hours'),
    'the quiet-hours gate must reuse the already-existing Settings quiet-hours proxy endpoint, not a new one',
  );
});

test('_isQuietHoursNow (finding #45) handles the overnight wrap, the disabled flag, and a zero-length window', () => {
  const body = `
    ${extractFunction(SRC, '_parseHHMM')}
    let _fixedNowMinutes = 0;
    function _minutesNowInTz() { return _fixedNowMinutes; }
    ${extractFunction(SRC, '_isQuietHoursNow')}
    return { isQuiet: _isQuietHoursNow, setNow: (m) => { _fixedNowMinutes = m; } };
  `;
  // eslint-disable-next-line no-new-func
  const { isQuiet, setNow } = new Function(body)();

  const overnight = { enabled: true, start: '22:00', end: '07:00', tz: '' };
  setNow(23 * 60); // 23:00 — inside
  assert.equal(isQuiet(overnight), true, '23:00 is inside a 22:00-07:00 window');
  setNow(3 * 60); // 03:00 — inside (past midnight)
  assert.equal(isQuiet(overnight), true, '03:00 is inside a 22:00-07:00 window (wraps past midnight)');
  setNow(12 * 60); // noon — outside
  assert.equal(isQuiet(overnight), false, 'noon is outside a 22:00-07:00 window');

  setNow(23 * 60);
  assert.equal(isQuiet({ enabled: false, start: '22:00', end: '07:00', tz: '' }), false, 'enabled:false is never quiet hours, regardless of the window');

  assert.equal(isQuiet({ enabled: true, start: '09:00', end: '09:00', tz: '' }), false, 'a zero-length window (start === end) is inert, mirroring the engine side');
  assert.equal(isQuiet(null), false, 'no config at all (fetch never resolved) must not suppress toasts forever');
});
