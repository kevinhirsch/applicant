// workspace/tests/js/applicantOnboarding.test.js
//
// Behavioral regression coverage for ledger #27 (the OOBE wizard reopening on
// every page load/login even after the user finished it) in
// ../../static/js/applicantOnboarding.js.
//
// Same "extract the real source, execute it headlessly" pattern as
// applicantPortal.test.js: applicantOnboarding.js does top-level module-scope
// work and statically imports fileHandler.js / applicantCore.js (which pulls
// in ui.js's heavier chain), so a plain `import()` would drag in the same
// browser-globals problem documented there. These tests instead extract the
// exact function bodies under test — `maybeLaunchOnboarding`, `_refreshStatus`
// and the #27 dismissed-flag helpers — and execute that verbatim text against
// minimal stand-ins for everything else `maybeLaunchOnboarding` touches once it
// decides NOT to bail out early (`_buildOverlay`/`_ensureCampaign`/`_renderStep`
// /etc.). Reverting the #27 fix changes the extracted text itself, so these
// assertions go red on revert and green on restore.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ONBOARDING_PATH = fileURLToPath(new URL('../../static/js/applicantOnboarding.js', import.meta.url));
const SRC = readFileSync(ONBOARDING_PATH, 'utf8');

// ── tiny source-slicer (brace-balanced, not a naive regex) — same helper as
//    applicantPortal.test.js ────────────────────────────────────────────────

function extractBalanced(src, openIdx) {
  let depth = 0;
  for (let i = openIdx; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(openIdx, i + 1);
    }
  }
  throw new Error(`unbalanced braces starting at index ${openIdx} in ${ONBOARDING_PATH}`);
}

function extractFunction(src, name) {
  // Prefer the `async function NAME(` form (also matches an `export async
  // function NAME(` declaration, since indexOf finds the substring regardless
  // of what precedes it) so async functions keep their `await` legal.
  const asyncMarker = `async function ${name}(`;
  const plainMarker = `function ${name}(`;
  let start = src.indexOf(asyncMarker);
  if (start === -1) start = src.indexOf(plainMarker);
  if (start === -1) throw new Error(`function ${name} not found in applicantOnboarding.js`);
  const braceOpen = src.indexOf('{', start);
  return src.slice(start, braceOpen) + extractBalanced(src, braceOpen);
}

// Extracts a single-line `const NAME = '...'` string literal verbatim (so a
// rename of the underlying prefix is reflected here rather than silently
// diverging from the real source).
function extractConstString(src, name) {
  const m = src.match(new RegExp(`const ${name} = (['"\`])((?:\\\\.|(?!\\1).)*)\\1`));
  if (!m) throw new Error(`const ${name} (string literal) not found in applicantOnboarding.js`);
  return `const ${name} = ${JSON.stringify(m[2])};`;
}

// Builds a headless harness exposing the REAL `maybeLaunchOnboarding` (plus the
// real #27 dismissed-flag helpers it calls) wired to minimal stand-ins for
// everything else it touches. `opts.statusPayload` is what the stubbed
// `_fetchJSON`/`_refreshStatus` resolves to; `opts.dismissedSeed` pre-seeds the
// fake localStorage's dismissed key exactly as `_markDismissedLocally()` would
// have left it from a prior visit.
function buildLaunchGateHarness({ statusPayload, dismissedSeed } = {}) {
  const harness = `
    // ── module-scope state maybeLaunchOnboarding reads/writes ─────────────
    let _overlay = null;
    let _overlayA11yCleanup = null;
    let _status = null;
    let _stepIndex = 0;

    // ── stand-ins for everything maybeLaunchOnboarding touches AFTER an
    //    early return — call-tracked so a test can assert they were (or
    //    weren't) reached ─────────────────────────────────────────────────
    const calls = [];
    function _buildOverlay() { calls.push('_buildOverlay'); return { fakeOverlay: true }; }
    function _maybeDismiss() { calls.push('_maybeDismiss'); }
    function _firstIncompleteStep() { calls.push('_firstIncompleteStep'); return 0; }
    function _startNavBusyWatch() { calls.push('_startNavBusyWatch'); }
    async function _ensureCampaign() { calls.push('_ensureCampaign'); return 'camp-1'; }
    async function _renderStep() { calls.push('_renderStep'); }

    const appendedOverlays = [];
    const document = { body: {
      dataset: { user: ${JSON.stringify(dismissedSeed && dismissedSeed.user != null ? dismissedSeed.user : '')} },
      appendChild: (el) => { appendedOverlays.push(el); },
    } };
    const window = { uiModule: null };

    const _store = new Map(${dismissedSeed && dismissedSeed.key ? `[[${JSON.stringify(dismissedSeed.key)}, '1']]` : '[]'});
    const localStorage = {
      getItem: (k) => (_store.has(k) ? _store.get(k) : null),
      setItem: (k, v) => { _store.set(k, String(v)); },
      removeItem: (k) => { _store.delete(k); },
    };

    const SETUP = '/api/applicant/setup';
    const _statusPayload = ${JSON.stringify(statusPayload)};
    let _fetchThrows = ${statusPayload === undefined ? 'true' : 'false'};
    async function _fetchJSON(url) {
      if (_fetchThrows) throw new Error('engine unreachable');
      return _statusPayload;
    }

    ${extractFunction(SRC, '_refreshStatus')}
    ${extractConstString(SRC, '_DISMISSED_KEY_PREFIX')}
    ${extractFunction(SRC, '_dismissedStorageKey')}
    ${extractFunction(SRC, '_isDismissedLocally')}
    ${extractFunction(SRC, '_markDismissedLocally')}
    ${extractFunction(SRC, '_clearDismissedLocally')}
    ${extractFunction(SRC, 'maybeLaunchOnboarding')}

    return {
      run: maybeLaunchOnboarding,
      getCalls: () => calls.slice(),
      getOverlayCount: () => appendedOverlays.length,
    };
  `;
  // eslint-disable-next-line no-new-func
  return new Function(harness)();
}

// ── #27: the wizard must not auto-launch once the engine reports setup fully
//    complete (the pre-existing server-truth check must survive the fix) ────

test('maybeLaunchOnboarding (#27) does not launch when the engine reports onboarding fully complete', async () => {
  const h = buildLaunchGateHarness({
    statusPayload: { llm_configured: true, onboarding_complete: true },
  });
  const launched = await h.run();
  assert.equal(launched, false, 'expected maybeLaunchOnboarding to report "not launched"');
  assert.deepEqual(
    h.getCalls(), [],
    `expected no overlay machinery to run once setup is complete; ran: ${h.getCalls().join(', ')}`,
  );
  assert.equal(h.getOverlayCount(), 0, 'no overlay should have been appended to the document');
});

// ── #27: the actual regression — a user who reached "You're all set" and
//    dismissed must not be re-prompted on every subsequent visit just because
//    the OPTIONAL profile essentials (apply-readiness) never strictly filled
//    in server-side ───────────────────────────────────────────────────────

test('maybeLaunchOnboarding (#27) does not re-launch once the user locally dismissed a completed setup, even when the server-side profile gate is still incomplete', async () => {
  const key = 'applicant_onboarding_dismissed:';
  const h = buildLaunchGateHarness({
    statusPayload: { llm_configured: true, onboarding_complete: false },
    dismissedSeed: { user: '', key },
  });
  const launched = await h.run();
  assert.equal(launched, false, 'a locally-dismissed completion must suppress relaunch even though onboarding_complete is false');
  assert.deepEqual(
    h.getCalls(), [],
    `expected no overlay machinery to run once locally dismissed; ran: ${h.getCalls().join(', ')}`,
  );
});

// ── regression guard: the fix must not over-suppress — an incomplete,
//    never-dismissed setup still launches normally ─────────────────────────

test('maybeLaunchOnboarding (#27, regression guard) still launches for a genuinely incomplete, never-dismissed setup', async () => {
  const h = buildLaunchGateHarness({
    statusPayload: { llm_configured: false, onboarding_complete: false },
  });
  const launched = await h.run();
  assert.equal(launched, true, 'expected the wizard to actually launch for a fresh, incomplete setup');
  assert.ok(h.getCalls().includes('_buildOverlay'), 'expected _buildOverlay to run when nothing suppresses launch');
  assert.equal(h.getOverlayCount(), 1, 'expected exactly one overlay to be appended');
});

// ── parse-verify ("double-check") surfacing — _parseVerifyHTML ──────────────
//
// P1-1a reachability: the engine's verify block (verified / reason /
// corrections / restored_from_draft) must render honestly in the wizard.
// Same extract-and-execute pattern: the REAL helper bodies run against a
// real-behaving esc() stub, so copy drift or a dropped honesty guard goes red.

function buildVerifyHarness() {
  const objStart = SRC.indexOf('const _VERIFY_REASON_COPY = {');
  if (objStart === -1) throw new Error('_VERIFY_REASON_COPY not found in applicantOnboarding.js');
  const copyMap = 'const _VERIFY_REASON_COPY = '
    + extractBalanced(SRC, SRC.indexOf('{', objStart)) + ';';
  const areasStart = SRC.indexOf('const _CONF_AREAS = [');
  if (areasStart === -1) throw new Error('_CONF_AREAS not found in applicantOnboarding.js');
  const areas = SRC.slice(areasStart, SRC.indexOf('];', areasStart) + 2);
  const src = [
    // Real-behaving escape stub (the module's esc comes from an import).
    'const esc = (s) => String(s)'
    + '.replace(/&/g, "&amp;").replace(/</g, "&lt;")'
    + '.replace(/>/g, "&gt;").replace(/"/g, "&quot;");',
    copyMap,
    areas,
    extractFunction(SRC, '_confidenceSummary'),
    extractFunction(SRC, '_friendlyVerifyItem'),
    extractFunction(SRC, '_verifyListHTML'),
    extractFunction(SRC, '_parseVerifyHTML'),
    'return _parseVerifyHTML;',
  ].join('\n');
  return new Function(src)();
}

test('_parseVerifyHTML: a verified parse gets the green confirmation plus corrections and kept items', () => {
  const html = buildVerifyHarness()({
    verify: {
      verified: true,
      corrections: ['split title|company', 'recovered second role'],
      restored_from_draft: ['role:Data Engineer @ Hooli', 'skill:SQL', 'contact:phone 555'],
    },
  });
  assert.ok(html.includes('admin-success'), 'verified must render the success style');
  assert.ok(html.includes('Double-checked'), 'verified must say it was double-checked');
  assert.ok(html.includes('split title|company'), 'corrections must be listed');
  assert.ok(html.includes('Job: Data Engineer @ Hooli'), 'restored role renders with a friendly label');
  assert.ok(html.includes('Skill: SQL'), 'restored skill renders with a friendly label');
  assert.ok(html.includes('Contact: phone 555'), 'restored contact renders with a friendly label');
});

test('_parseVerifyHTML: long lists cap at 5 with an honest "and N more"', () => {
  const corrections = Array.from({ length: 8 }, (_, i) => `fix number ${i}`);
  const html = buildVerifyHarness()({ verify: { verified: true, corrections } });
  assert.ok(html.includes('fix number 4'), 'the first five corrections render');
  assert.ok(!html.includes('fix number 5'), 'the sixth is folded into the count');
  assert.ok(html.includes('and 3 more'), 'the fold is announced, never silent');
});

test('_parseVerifyHTML: an unverified parse says WHY and never shows success styling', () => {
  const render = buildVerifyHarness();
  const html = render({ verify: { verified: false, reason: 'model_error' } });
  assert.ok(html.includes('Not double-checked'), 'unverified must say so');
  assert.ok(html.includes('reach your model'), 'the reason copy renders');
  assert.ok(!html.includes('admin-success'), 'no success styling on an unchecked parse');
  const unknown = render({ verify: { verified: false, reason: 'something_new' } });
  assert.ok(unknown.includes('could not be run'), 'unknown reasons fall back honestly');
});

test('_parseVerifyHTML: an older engine with no verify block renders silence, not a guess', () => {
  const render = buildVerifyHarness();
  assert.equal(render({}), '');
  assert.equal(render(null), '');
});

test('_parseVerifyHTML: correction text is HTML-escaped', () => {
  const html = buildVerifyHarness()({
    verify: { verified: true, corrections: ['<script>alert(1)</script>'] },
  });
  assert.ok(!html.includes('<script>'), 'raw markup must not pass through');
  assert.ok(html.includes('&lt;script&gt;'), 'markup renders escaped');
});

test('_parseVerifyHTML: per-area confidence renders with friendly labels, grouped by stem', () => {
  const objStart = SRC.indexOf('const _CONF_AREAS = [');
  assert.ok(objStart !== -1, '_CONF_AREAS must exist');
  const src = [
    'const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");',
    SRC.slice(objStart, SRC.indexOf('];', objStart) + 2),
    extractFunction(SRC, '_confidenceSummary'),
    'return _confidenceSummary;',
  ].join('\n');
  const summary = new Function(src)();
  // The renamed live-model key shapes group under their friendly stems, and each
  // area reports its LOWEST matching score (the conservative read).
  const html = summary({
    work_history_titles_companies: 0.99,
    work_history_achievements: 0.98,
    education_certifications: 0.97,
    skills_extraction: 0.98,
  });
  assert.ok(html.includes('work history 98%'), 'work areas group to the lowest score');
  assert.ok(html.includes('education 97%'));
  assert.ok(html.includes('skills 98%'));
  assert.ok(!html.includes('work_history_titles_companies'), 'raw keys never render');
  assert.equal(summary({}), '', 'no scores, no claim');
  assert.equal(summary(null), '', 'missing confidence renders silence');
});
