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
      seedSeenRaw: (raw) => { _store.set(NOTIF_SEEN_KEY, raw); },
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

// ── #46: "Deliver now" reachable from the Portal notification center ──────
//
// The engine endpoint and the workspace proxy already existed; the only gap
// was that the release control lived exclusively on the Settings quiet-hours
// card (`applicantOnboarding.js`'s `ao-qh-deliver`). These tests assert (a)
// the SAME endpoint the Settings button calls is wired into the Portal's
// notification-center header, and (b) the extracted click handler actually
// drives that call, toasts, and refreshes on success/failure — so reverting
// the fix (removing the button/handler from applicantPortal.js) fails these,
// and restoring it turns them green again.

test('_renderList (finding #46) source wires a "Deliver now" control into the notification-center header, over the SAME endpoint the Settings button uses', () => {
  // The endpoint string, verbatim, as used by applicantOnboarding.js's
  // ao-qh-deliver handler (`${PORTAL}/notifications/deliver-now`) — the
  // Portal must call the identical path via its own `${API}` base.
  assert.ok(
    SRC.includes('${API}/notifications/deliver-now'),
    'the Portal must call the SAME deliver-now path the Settings button uses, not a new endpoint',
  );
  assert.ok(
    SRC.includes('id="applicant-portal-deliver-now"'),
    'a "Deliver now" control must be rendered into the notification center',
  );
  assert.ok(
    /class="cal-btn applicant-portal-deliver-now"/.test(SRC),
    'the control must reuse the workspace design system (.cal-btn), not a hand-rolled button',
  );
  assert.ok(
    SRC.includes('_wireDeliverNow(body)'),
    '_renderList must wire the deliver-now control on every render',
  );
});

function buildDeliverNowHarness() {
  const harness = `
    const API = '/api/applicant/portal';
    let _items = [];
    let _postCalls = [];
    let _toastCalls = [];
    let _loadNotifsCalls = 0;
    let _setBadgeCalls = [];
    let _renderListCalls = [];
    let _postResult = null;
    let _postShouldReject = false;

    async function _post(url, body) {
      _postCalls.push({ url, body });
      if (_postShouldReject) throw new Error('deliver failed');
      return _postResult;
    }
    function _toast(msg) { _toastCalls.push(msg); }
    async function _loadNotifs() { _loadNotifsCalls += 1; }
    function _setBadge(n) { _setBadgeCalls.push(n); }
    function _infoNotifs() { return []; }
    function _renderList(host) { _renderListCalls.push(host); }
    // Minimal stand-in for applicantCore.js's real errText(err) (copy/voice
    // lens-02 fix): the deliver-now handler now routes its failure toast
    // through it instead of a raw \`e.message\`. For a plain Error with no
    // \`.kind\` (exactly what \`_postShouldReject\` throws above) the real
    // implementation falls through to \`err.message\`, so this stub mirrors
    // that one branch rather than re-implementing the whole helper.
    function errText(err) {
      return (err && err.message) ? err.message : 'Something went wrong.';
    }

    ${extractFunction(SRC, '_wireDeliverNow')}

    function makeHost(btn, msg) {
      return {
        querySelector: (sel) => {
          if (sel === '#applicant-portal-deliver-now') return btn;
          if (sel === '#applicant-portal-deliver-msg') return msg;
          return null;
        },
      };
    }

    return {
      wire: _wireDeliverNow,
      makeHost,
      setPostResult: (r) => { _postResult = r; },
      setPostReject: (v) => { _postShouldReject = v; },
      getPostCalls: () => _postCalls.slice(),
      getToastCalls: () => _toastCalls.slice(),
      getLoadNotifsCalls: () => _loadNotifsCalls,
      getSetBadgeCalls: () => _setBadgeCalls.slice(),
      getRenderListCalls: () => _renderListCalls.length,
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

function makeButtonStub() {
  return { disabled: false, _handler: null, addEventListener(evt, fn) { this._handler = fn; } };
}
function makeMsgStub() {
  return { textContent: '', className: '' };
}

test('_wireDeliverNow (finding #46) calls the deliver-now endpoint, toasts the released count, and refreshes the center on success', async () => {
  const h = buildDeliverNowHarness();
  h.setPostResult({ flushed: ['discord', 'email'], count: 2 });
  const btn = makeButtonStub();
  const msg = makeMsgStub();
  const host = h.makeHost(btn, msg);

  h.wire(host);
  assert.equal(typeof btn._handler, 'function', 'the button must get a click handler');

  await btn._handler();

  const calls = h.getPostCalls();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/applicant/portal/notifications/deliver-now', 'must hit the same proxy path the Settings button uses');

  assert.ok(h.getToastCalls().includes('Released 2 held notifications.'), 'success toasts the released count');
  assert.equal(h.getLoadNotifsCalls(), 1, 'the notifications feed is reloaded after a successful release');
  assert.equal(h.getRenderListCalls(), 1, 'the center is re-rendered so released items appear immediately');
});

test('_wireDeliverNow (finding #46) reports "nothing held" in plain language when the count is zero', async () => {
  const h = buildDeliverNowHarness();
  h.setPostResult({ flushed: [], count: 0 });
  const btn = makeButtonStub();
  const msg = makeMsgStub();
  h.wire(h.makeHost(btn, msg));

  await btn._handler();

  assert.ok(h.getToastCalls().includes('Nothing was being held back by quiet hours.'));
});

test('_wireDeliverNow (finding #46) re-enables the button and toasts an error message if the release fails', async () => {
  const h = buildDeliverNowHarness();
  h.setPostReject(true);
  const btn = makeButtonStub();
  const msg = makeMsgStub();
  h.wire(h.makeHost(btn, msg));

  btn.disabled = false;
  await btn._handler();

  assert.equal(btn.disabled, false, 'a failed release must leave the button clickable again');
  assert.ok(h.getToastCalls().some((m) => m.includes('deliver failed')), 'the failure reason should surface in a toast');
  assert.equal(h.getRenderListCalls(), 0, 'the center should not be re-rendered on a failed release');
});

// ── Lens-04 audit findings #49/#50/#62/#63/#65/#66 ─────────────────────────
//
// Re-render/poll/clock resilience hardening. Same "extract the real source,
// execute it headlessly" pattern as every test above.

// ── #49: in-flight input (an answer draft, a missing-detail name/value)
// must survive a re-render of the pending list ─────────────────────────────

function makeFakeInput(value) { return { value }; }
function makeFakeDraftRow(id, children) {
  return {
    getAttribute: (name) => (name === 'data-action-id' ? id : null),
    querySelector: (sel) => children[sel] || null,
  };
}
function makeFakeDraftBody(rows) {
  return { querySelectorAll: (sel) => (sel === '.applicant-portal-row' ? rows : []) };
}

function buildDraftHarness() {
  const body = [
    extractFunction(SRC, '_captureDraftInputs'),
    extractFunction(SRC, '_restoreDraftInputs'),
    'return { _captureDraftInputs, _restoreDraftInputs };',
  ].join('\n');
  // eslint-disable-next-line no-new-func
  return new Function(body)();
}

test('_captureDraftInputs/_restoreDraftInputs (finding #49) round-trip an in-flight answer across a re-render', () => {
  const { _captureDraftInputs, _restoreDraftInputs } = buildDraftHarness();

  const answerInput = makeFakeInput('a partial answer the user was mid-typing');
  const oldRow = makeFakeDraftRow('q1', { '.applicant-portal-answer': answerInput });
  const drafts = _captureDraftInputs(makeFakeDraftBody([oldRow]));
  assert.deepEqual(drafts, { q1: { answer: 'a partial answer the user was mid-typing' } });

  // Simulate the re-render: a BRAND NEW (empty) input for the SAME action id.
  const freshAnswerInput = makeFakeInput('');
  const freshRow = makeFakeDraftRow('q1', { '.applicant-portal-answer': freshAnswerInput });
  _restoreDraftInputs(makeFakeDraftBody([freshRow]), drafts);

  assert.equal(freshAnswerInput.value, 'a partial answer the user was mid-typing', 'the draft must survive onto the freshly-rendered row');
});

test('_captureDraftInputs/_restoreDraftInputs (finding #49) round-trip a missing-detail name/value pair too', () => {
  const { _captureDraftInputs, _restoreDraftInputs } = buildDraftHarness();

  const nameInput = makeFakeInput('LinkedIn URL');
  const valueInput = makeFakeInput('https://linkedin.com/in/example');
  const oldRow = makeFakeDraftRow('m1', {
    '.applicant-portal-missing-name': nameInput,
    '.applicant-portal-missing-value': valueInput,
  });
  const drafts = _captureDraftInputs(makeFakeDraftBody([oldRow]));

  const freshName = makeFakeInput('LinkedIn URL');
  const freshValue = makeFakeInput('');
  const freshRow = makeFakeDraftRow('m1', {
    '.applicant-portal-missing-name': freshName,
    '.applicant-portal-missing-value': freshValue,
  });
  _restoreDraftInputs(makeFakeDraftBody([freshRow]), drafts);

  assert.equal(freshValue.value, 'https://linkedin.com/in/example', 'the missing-detail value draft must survive the re-render');
});

test('_captureDraftInputs (finding #49) captures nothing for an untouched/empty row', () => {
  const { _captureDraftInputs } = buildDraftHarness();
  const emptyRow = makeFakeDraftRow('q2', { '.applicant-portal-answer': makeFakeInput('') });
  const drafts = _captureDraftInputs(makeFakeDraftBody([emptyRow]));
  assert.deepEqual(drafts, {}, 'an empty/untouched input is not a draft worth preserving');
});

test('_renderList (finding #49) captures drafts BEFORE rebuilding the DOM and restores them AFTER', () => {
  const fnSrc = extractFunction(SRC, '_renderList');
  const captureIdx = fnSrc.indexOf('_captureDraftInputs(body)');
  const innerHtmlIdx = fnSrc.indexOf('body.innerHTML =');
  const restoreIdx = fnSrc.indexOf('_restoreDraftInputs(body, drafts)');
  assert.ok(captureIdx !== -1, '_renderList must call _captureDraftInputs');
  assert.ok(restoreIdx !== -1, '_renderList must call _restoreDraftInputs');
  assert.ok(captureIdx < innerHtmlIdx, 'drafts must be captured BEFORE the DOM is overwritten, or there is nothing left to capture');
  assert.ok(restoreIdx > innerHtmlIdx, 'drafts must be restored AFTER the DOM is rebuilt, or there is nothing left to restore them into');
});

// ── #50: resolving an action that's already handled gets an honest state,
// not a silent/confusing result (pairs with engine #27) ────────────────────

function buildDoResolveHarness(openIds) {
  const harness = `
    const API = '/api/applicant/portal';
    let _items = ${JSON.stringify((openIds || []).map((id) => ({ id })))};
    const _postCalls = [];
    let _postDelayed = false;
    const _pendingPostResolvers = [];
    async function _post(url, body) {
      _postCalls.push({ url, body });
      if (_postDelayed) {
        return new Promise((resolve) => { _pendingPostResolvers.push(resolve); });
      }
      return {};
    }

    ${extractFunction(SRC, '_isActionOpen')}
    const _resolvingActionIds = new Set();
    ${extractFunction(SRC, '_doResolve')}

    return {
      doResolve: _doResolve,
      getPostCalls: () => _postCalls.slice(),
      setDelayed: (v) => { _postDelayed = v; },
      resolveNextPost: () => { const fn = _pendingPostResolvers.shift(); if (fn) fn({}); },
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

test('_doResolve (finding #50) throws an "already handled" error (no network call) when the action is no longer open', async () => {
  const h = buildDoResolveHarness(['a1']);
  await assert.rejects(
    () => h.doResolve('gone'),
    (err) => {
      assert.equal(err.alreadyHandled, true, 'the error must be flagged so the UI can show a calm "already handled" state');
      return true;
    },
  );
  assert.equal(h.getPostCalls().length, 0, 'no network call should be made resolving an action already known to be gone');
});

test('_doResolve (finding #50, regression guard) still resolves normally over the network when the action is genuinely open', async () => {
  const h = buildDoResolveHarness(['a1']);
  await h.doResolve('a1');
  const calls = h.getPostCalls();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/applicant/portal/actions/a1/resolve');
});

test('_doResolve (finding #50) rejects a second concurrent resolve of the SAME action while the first is still in flight', async () => {
  const h = buildDoResolveHarness(['a1']);
  h.setDelayed(true);
  const p1 = h.doResolve('a1'); // in flight — _post hasn't settled yet
  await assert.rejects(
    () => h.doResolve('a1'),
    (err) => { assert.equal(err.alreadyHandled, true); return true; },
    'a second resolve attempt on the same in-flight action must be rejected as already-handled, not double-POSTed',
  );
  h.resolveNextPost();
  await p1;
  assert.equal(h.getPostCalls().length, 1, 'only ONE network resolve call should ever be made for the two overlapping attempts');
});

test('_wireRows (finding #50) shows a calm "already handled" state instead of the generic failure toast when _doResolve reports it', () => {
  assert.ok(
    SRC.includes('if (e && e.alreadyHandled)'),
    'the Done-button handler must specifically recognize the already-handled error',
  );
  assert.ok(
    SRC.includes("_toast('This was already handled')"),
    'an already-resolved action must get its own honest message, not the generic failure toast',
  );
});

// ── #62: the seen-marker claim must be atomic w.r.t. toasting ─────────────

test('_toastNew (finding #62) claims/advances the seen-marker BEFORE the quiet-hours await, closing the staleness window', () => {
  const fnSrc = extractFunction(SRC, '_toastNew');
  const claimIdx = fnSrc.indexOf('_setNotifSeenTs(newest)');
  const awaitIdx = fnSrc.indexOf('await _refreshQuietHoursCfg()');
  assert.ok(claimIdx !== -1, 'the marker-claim call must still exist in _toastNew');
  assert.ok(awaitIdx !== -1, 'the quiet-hours await must still exist in _toastNew');
  assert.ok(
    claimIdx < awaitIdx,
    'the seen-marker must be read and advanced BEFORE the quiet-hours await (a real network round trip) — ' +
    'claiming it only afterward reopens a window where an overlapping call (another poll, or another tab ' +
    'sharing this same localStorage key) can read the same stale marker and toast the same arrivals twice',
  );
});

// ── #65: a corrupt/blank seen-marker must not re-toast the whole backlog ──

test('_notifSeenTs (finding #65) treats a missing/corrupt/non-positive marker as "no marker" (null), never as epoch zero', () => {
  const harness = `
    const NOTIF_SEEN_KEY = ${JSON.stringify(NOTIF_SEEN_KEY_LITERAL)};
    const _store = new Map();
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };
    ${extractFunction(SRC, '_notifSeenTs')}
    return {
      _notifSeenTs,
      setRaw: (v) => { if (v === null) _store.delete(NOTIF_SEEN_KEY); else _store.set(NOTIF_SEEN_KEY, v); },
    };
  `;
  // eslint-disable-next-line no-new-func
  const { _notifSeenTs, setRaw } = new Function(harness)();

  setRaw(null);
  assert.equal(_notifSeenTs(), null, 'a missing key -> null');
  setRaw('');
  assert.equal(_notifSeenTs(), null, 'an empty string -> null, not epoch zero (Number(\'\') === 0 in JS)');
  setRaw('   ');
  assert.equal(_notifSeenTs(), null, 'a whitespace-only string -> null (Number(\'   \') === 0 in JS too)');
  setRaw('not-a-timestamp');
  assert.equal(_notifSeenTs(), null, 'non-numeric garbage -> null');
  setRaw('0');
  assert.equal(_notifSeenTs(), null, 'a literal "0" is not a usable cutoff either');
  setRaw('-5');
  assert.equal(_notifSeenTs(), null, 'a negative marker is not usable');
  setRaw('1700000000000');
  assert.equal(_notifSeenTs(), 1700000000000, 'a real positive timestamp still round-trips correctly');
});

test('_toastNew (finding #65) treats a corrupted marker as "no marker yet" instead of re-toasting the whole backlog', async () => {
  const h = buildToastHarness();
  h.seedSeenRaw(''); // corrupted: an empty string sitting in localStorage, not a missing key
  h.setFetchImpl(async () => ({ enabled: false }));

  const backlog = [
    { id: 'a1', kind: 'action', title: 'Old item 1', created_at: new Date(1000).toISOString() },
    { id: 'a2', kind: 'info', title: 'Old item 2', created_at: new Date(2000).toISOString() },
  ];
  await h.run(backlog);

  assert.equal(h.getToastActionCalls().length, 0, 'a corrupt marker must not re-toast the backlog as if it were all brand new');
  assert.equal(h.getToastCalls().length, 0, 'a corrupt marker must not re-toast informational backlog items either');
  assert.ok(Number(h.getSeenTs()) > 0, 'the marker should be repaired to a real value after this run');
});

// ── #63/#66: the recap cursor must be read-modify-write safe across tabs,
// and anchored to the server's own timeline rather than the client clock ───

const RECAP_SEEN_KEY_LITERAL = (SRC.match(/const RECAP_SEEN_KEY = '([^']+)'/) || [])[1];
assert.ok(RECAP_SEEN_KEY_LITERAL, 'could not find RECAP_SEEN_KEY in applicantPortal.js — has it been renamed?');

function buildRecapAnchorHarness() {
  const harness = `
    const RECAP_SEEN_KEY = ${JSON.stringify(RECAP_SEEN_KEY_LITERAL)};
    const _store = new Map();
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };
    ${extractFunction(SRC, '_runTs')}
    ${extractFunction(SRC, '_reanchorRecapMarker')}
    return {
      reanchor: _reanchorRecapMarker,
      setStored: (v) => { _store.set(RECAP_SEEN_KEY, String(v)); },
      getStored: () => _store.get(RECAP_SEEN_KEY),
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

test('_reanchorRecapMarker (findings #63/#66) advances the stored cursor to the newest server-observed run timestamp', () => {
  const h = buildRecapAnchorHarness();
  h.setStored(1000); // an earlier client-clock claim already sitting there
  h.reanchor([
    { created_at: new Date(5000).toISOString() },
    { created_at: new Date(3000).toISOString() },
  ]);
  assert.equal(Number(h.getStored()), 5000, 'the cursor should move forward to the newest server-provided run timestamp');
});

test('_reanchorRecapMarker (findings #63/#66) never moves the cursor BACKWARD past what is already stored', () => {
  const h = buildRecapAnchorHarness();
  h.setStored(9000); // another tab/context already advanced it further
  h.reanchor([{ created_at: new Date(2000).toISOString() }]);
  assert.equal(Number(h.getStored()), 9000, 'a re-anchor must not roll the cursor back and reopen a window another context already consumed');
});

test('_reanchorRecapMarker (findings #63/#66) is a no-op when there is no server timestamp available to anchor to', () => {
  const h = buildRecapAnchorHarness();
  h.setStored(1234);
  h.reanchor([]);
  h.reanchor([{ no_created_at_here: true }]);
  assert.equal(Number(h.getStored()), 1234, 'nothing to anchor to -> leave the existing marker untouched');
});

test('_captureRecapSince (finding #63) goes through the Web Locks API for cross-tab mutual exclusion when the browser supports it', async () => {
  const harness = `
    const RECAP_SEEN_KEY = ${JSON.stringify(RECAP_SEEN_KEY_LITERAL)};
    let _recapSinceReady = false;
    let _recapSince = null;
    const _store = new Map();
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };
    const _lockCalls = [];
    const navigator = {
      locks: { request: (name, cb) => { _lockCalls.push(name); return Promise.resolve(cb()); } },
    };
    ${extractFunction(SRC, '_captureRecapSinceUnlocked')}
    ${extractFunction(SRC, '_captureRecapSince')}
    return { capture: _captureRecapSince, getLockCalls: () => _lockCalls.slice() };
  `;
  // eslint-disable-next-line no-new-func
  const { capture, getLockCalls } = new Function(harness)();
  await capture();
  const calls = getLockCalls();
  assert.equal(calls.length, 1, 'capturing the recap cursor must go through exactly one Web Locks request');
  assert.ok(String(calls[0]).includes(RECAP_SEEN_KEY_LITERAL), 'the lock name should be scoped to the recap cursor key');
});

test('_captureRecapSince (finding #63, regression guard) still works correctly with no Web Locks support in the browser', async () => {
  const harness = `
    const RECAP_SEEN_KEY = ${JSON.stringify(RECAP_SEEN_KEY_LITERAL)};
    let _recapSinceReady = false;
    let _recapSince = null;
    const _store = new Map();
    _store.set(RECAP_SEEN_KEY, '5000');
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };
    ${extractFunction(SRC, '_captureRecapSinceUnlocked')}
    ${extractFunction(SRC, '_captureRecapSince')}
    return { capture: _captureRecapSince, getRecapSince: () => _recapSince, getStored: () => _store.get(RECAP_SEEN_KEY) };
  `;
  // eslint-disable-next-line no-new-func
  const { capture, getRecapSince, getStored } = new Function(harness)();
  await capture();
  assert.equal(getRecapSince(), 5000, 'the prior marker must still be captured correctly without Web Locks');
  assert.ok(Number(getStored()) > 5000, 'the marker should still be advanced afterward');
});

test('_captureRecapSinceUnlocked (finding #63, consistency with #65) treats a corrupt/blank stored cursor as "no prior visit", not epoch zero', async () => {
  const harness = `
    const RECAP_SEEN_KEY = ${JSON.stringify(RECAP_SEEN_KEY_LITERAL)};
    let _recapSince = 'unset';
    const _store = new Map();
    _store.set(RECAP_SEEN_KEY, '');
    const window = {
      localStorage: {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => { _store.set(k, String(v)); },
      },
    };
    ${extractFunction(SRC, '_captureRecapSinceUnlocked')}
    _captureRecapSinceUnlocked();
    return { recapSince: _recapSince };
  `;
  // eslint-disable-next-line no-new-func
  const { recapSince } = new Function(harness)();
  assert.equal(recapSince, null, 'a blank/corrupt stored value must read back as null (no prior visit), never as an epoch-zero cutoff');
});

// ── #66 (remaining client-clock anchors): notification age text and the
// supportive streak ─────────────────────────────────────────────────────────

test('_notifAgeText (finding #66) clamps a client clock running slightly behind the server to "just now" instead of hiding the age', () => {
  const body = `${extractFunction(SRC, '_notifTs')}\n${extractFunction(SRC, '_notifAgeText')}\nreturn _notifAgeText;`;
  // eslint-disable-next-line no-new-func
  const _notifAgeText = new Function(body)();
  const futureIso = new Date(Date.now() + 30 * 1000).toISOString();
  assert.equal(_notifAgeText({ created_at: futureIso }), 'just now', 'a small negative skew should read as "just now", not disappear entirely');
});

function buildStreakHarness() {
  const harness = `
    const _ONE_DAY_MS = 24 * 60 * 60 * 1000;
    ${extractFunction(SRC, '_runTs')}
    ${extractFunction(SRC, '_dayKey')}
    ${extractFunction(SRC, '_computeStreakDays')}
    return {
      run: (items, fakeNow) => {
        const origNow = Date.now;
        Date.now = () => fakeNow;
        try { return _computeStreakDays(items); } finally { Date.now = origNow; }
      },
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

test('_computeStreakDays (finding #66) credits "today" from a server-observed run even when the client clock reports an earlier calendar day', () => {
  const h = buildStreakHarness();
  // All local-time constructions, so this is TZ-independent: _dayKey reads the
  // same local calendar the test builds these instants from.
  const serverRunTs = new Date(2024, 0, 15, 1, 0, 0).getTime(); // "today" per the server
  const clientNow = new Date(2024, 0, 14, 20, 0, 0).getTime(); // the client clock itself still reads yesterday evening
  const yesterdayRunTs = new Date(2024, 0, 14, 9, 0, 0).getTime();

  const runs = [
    { created_at: new Date(serverRunTs).toISOString() },
    { created_at: new Date(yesterdayRunTs).toISOString() },
  ];

  assert.equal(
    h.run(runs, clientNow),
    2,
    'the server-observed run for "today" must be credited toward the streak even though the client clock itself still reads yesterday',
  );
});
