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
