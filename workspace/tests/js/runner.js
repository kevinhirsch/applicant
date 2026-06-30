// workspace/tests/js/runner.js
//
// A tiny zero-dependency test runner for the white-labeled front-door's
// browser ES modules (workspace/static/js/*.js).
//
// It dynamically import()s REAL front-door modules and asserts genuine,
// stable facts about them: that documented exports exist with the right
// type, and that pure helpers return the expected value for known inputs.
// There is no `assert(true)` filler — every assertion below exercises a
// real exported symbol or the result of a real pure function call.
//
// Path note: from this file the modules live at ../../static/js/<mod>.js
//   workspace/tests/js/runner.js  ->  workspace/static/js/<mod>.js
// The same relative specifier works in the browser (test_harness.html is
// served from the repo root and loads this file as a module, so the
// browser resolves ../../static/js/* to /workspace/static/js/*) and in
// Node (import() resolves relative to this module's URL). The modules
// chosen here are pure ES modules that touch no browser globals at import
// time, so the suite runs headlessly under Node too — see README.md.

const MOD = (name) => `../../static/js/${name}`;

// ── assertion helpers ──────────────────────────────────────────────────
let _passed = 0;
let _failed = 0;
const _failures = [];
let _current = '(top level)';

function _record(ok, message) {
  if (ok) {
    _passed += 1;
  } else {
    _failed += 1;
    _failures.push(`${_current}: ${message}`);
  }
  return ok;
}

export function assertDefined(value, label) {
  return _record(value !== undefined && value !== null, `${label} should be defined (got ${String(value)})`);
}

export function assertType(value, type, label) {
  return _record(typeof value === type, `${label} should be typeof ${type} (got ${typeof value})`);
}

export function assertEqual(actual, expected, label) {
  const a = typeof actual === 'object' ? JSON.stringify(actual) : String(actual);
  const e = typeof expected === 'object' ? JSON.stringify(expected) : String(expected);
  return _record(a === e, `${label}: expected ${e} but got ${a}`);
}

export function assertThrows(fn, label) {
  let threw = false;
  try {
    fn();
  } catch (_) {
    threw = true;
  }
  return _record(threw, `${label} should throw`);
}

// ── micro describe/it (sequential, async-aware) ────────────────────────
const _suites = [];

export function describe(name, fn) {
  _suites.push({ name, fn });
}

export function it(name, fn) {
  // `it` runs immediately inside the active describe body; we just label
  // assertions with the current test name for readable failure output.
  const prev = _current;
  _current = name;
  const restore = () => { _current = prev; };
  let out;
  try {
    out = fn();
  } catch (e) {
    _record(false, `${name} threw: ${e && e.message ? e.message : e}`);
    restore();
    return;
  }
  if (out && typeof out.then === 'function') {
    return out.then(restore, (e) => {
      _record(false, `${name} threw: ${e && e.message ? e.message : e}`);
      restore();
    });
  }
  restore();
}

// ── the suites: real modules, real assertions ──────────────────────────
async function loadSuites() {
  const [
    modelSort,
    langIcons,
    providers,
    storage,
    platform,
    updateView,
    presets,
    modalSnap,
  ] = await Promise.all([
    import(MOD('modelSort.js')),
    import(MOD('langIcons.js')),
    import(MOD('providers.js')),
    import(MOD('storage.js')),
    import(MOD('platform.js')),
    import(MOD('applicantUpdateView.js')),
    import(MOD('presets.js')),
    import(MOD('modalSnap.js')),
  ]);

  describe('modelSort.js', () => {
    it('exports the three sort helpers', () => {
      assertType(modelSort.sortModelIds, 'function', 'sortModelIds');
      assertType(modelSort.sortModelObjects, 'function', 'sortModelObjects');
      assertType(modelSort.compareModelObjects, 'function', 'compareModelObjects');
    });
    it('sortModelIds orders by the part after the last slash, case-insensitively', () => {
      assertEqual(modelSort.sortModelIds(['b/z', 'a/y', 'a/x']), ['a/x', 'a/y', 'b/z'], 'sorted ids');
      assertEqual(modelSort.sortModelIds([]), [], 'empty input -> empty');
      assertEqual(modelSort.sortModelIds(null), [], 'null input -> empty (defensive)');
    });
    it('compareModelObjects returns a negative number for a-before-b', () => {
      assertEqual(modelSort.compareModelObjects({ name: 'apple' }, { name: 'banana' }) < 0, true, 'apple < banana');
      assertEqual(modelSort.compareModelObjects({ name: 'banana' }, { name: 'apple' }) > 0, true, 'banana > apple');
    });
    it('sortModelObjects sorts on display/name and is non-mutating', () => {
      const input = [{ name: 'zeta' }, { name: 'alpha' }];
      const out = modelSort.sortModelObjects(input);
      assertEqual(out[0].name, 'alpha', 'first after sort');
      assertEqual(input[0].name, 'zeta', 'original array untouched');
    });
  });

  describe('langIcons.js', () => {
    it('exports langIcon', () => {
      assertType(langIcons.langIcon, 'function', 'langIcon');
    });
    it('returns an inline <svg> for a known language and "" otherwise', () => {
      assertEqual(langIcons.langIcon('markdown').startsWith('<svg'), true, 'markdown -> svg');
      assertEqual(langIcons.langIcon('zzz-not-a-real-lang'), '', 'unknown lang -> ""');
      assertEqual(langIcons.langIcon(''), '', 'empty lang -> ""');
    });
    it('honors the size argument in the rendered svg', () => {
      assertEqual(langIcons.langIcon('markdown', 32).includes('width="32"'), true, 'size 32 width');
    });
  });

  describe('providers.js', () => {
    it('exports providerLogo', () => {
      assertType(providers.providerLogo, 'function', 'providerLogo');
    });
    it('matches known provider model ids to an svg, else null', () => {
      assertEqual(providers.providerLogo('gpt-4').includes('<svg'), true, 'gpt-4 -> svg');
      assertEqual(providers.providerLogo('claude-3-opus').includes('<svg'), true, 'claude -> svg');
      assertEqual(providers.providerLogo('some-unbranded-model-xyz'), null, 'unknown -> null');
      assertEqual(providers.providerLogo(''), null, 'empty -> null');
    });
  });

  describe('storage.js', () => {
    it('exports the KEYS table and JSON helpers', () => {
      assertDefined(storage.KEYS, 'KEYS');
      assertEqual(storage.KEYS.THEME, 'applicant-theme', 'KEYS.THEME constant');
      assertType(storage.getJSON, 'function', 'getJSON');
      assertType(storage.setJSON, 'function', 'setJSON');
    });
    it('getJSON returns the fallback when localStorage is unavailable or key missing', () => {
      // In a headless/Node context localStorage is undefined; getJSON swallows
      // the error and returns the fallback. In a browser the key is absent so
      // the same fallback path is taken. Either way the contract holds.
      assertEqual(storage.getJSON('__definitely_missing_key__', 'fallback-value'), 'fallback-value', 'missing-key fallback');
    });
  });

  describe('platform.js', () => {
    it('exports IS_MAC plus the width + AltGr helpers', () => {
      assertType(platform.IS_MAC, 'boolean', 'IS_MAC');
      assertType(platform.isNarrow, 'function', 'isNarrow');
      assertType(platform.isBelowMedium, 'function', 'isBelowMedium');
      assertType(platform.isAltGrEvent, 'function', 'isAltGrEvent');
    });
    it('isAltGrEvent fires only for non-mac Ctrl+Alt with AltGraph set', () => {
      const altGr = { ctrlKey: true, altKey: true, getModifierState: () => true };
      assertEqual(platform.isAltGrEvent(altGr, false), true, 'non-mac AltGr -> true');
      assertEqual(platform.isAltGrEvent(altGr, true), false, 'mac never AltGr');
      assertEqual(platform.isAltGrEvent({ ctrlKey: true, altKey: true, getModifierState: () => false }, false), false, 'plain Ctrl+Alt -> false');
    });
  });

  describe('applicantUpdateView.js', () => {
    it('exports formatLogTail', () => {
      assertType(updateView.formatLogTail, 'function', 'formatLogTail');
    });
    it('joins log lines, trims trailing whitespace, and handles empty input', () => {
      assertEqual(updateView.formatLogTail(['a  ', 'b']), 'a\nb', 'trim + join');
      assertEqual(updateView.formatLogTail([]), '', 'empty array -> ""');
      assertEqual(updateView.formatLogTail(null), '', 'non-array -> ""');
    });
  });

  describe('presets.js', () => {
    it('exports the PROMPT_TEMPLATES table and getCharacterName', () => {
      assertEqual(Array.isArray(presets.PROMPT_TEMPLATES), true, 'PROMPT_TEMPLATES is array');
      assertEqual(presets.PROMPT_TEMPLATES.length > 0, true, 'has at least one template');
      assertType(presets.getCharacterName, 'function', 'getCharacterName');
    });
    it('every template carries the fields the UI relies on', () => {
      const ok = presets.PROMPT_TEMPLATES.every((t) => typeof t.id === 'string' && typeof t.name === 'string' && typeof t.prompt === 'string');
      assertEqual(ok, true, 'each template has id/name/prompt strings');
    });
    it('getCharacterName returns "" before any custom preset is selected', () => {
      assertEqual(presets.getCharacterName(), '', 'default character name');
    });
  });

  describe('modalSnap.js', () => {
    it('exports its dock controllers as functions', () => {
      assertType(modalSnap.makeRightDockController, 'function', 'makeRightDockController');
      assertType(modalSnap.makeEdgeDockController, 'function', 'makeEdgeDockController');
      assertType(modalSnap.applyRightDock, 'function', 'applyRightDock');
      assertType(modalSnap.clearDockSide, 'function', 'clearDockSide');
    });
  });
}

// ── run ────────────────────────────────────────────────────────────────
export async function run() {
  _passed = 0;
  _failed = 0;
  _failures.length = 0;
  _suites.length = 0;
  await loadSuites();
  for (const suite of _suites) {
    _current = suite.name;
    await suite.fn();
  }
  return { passed: _passed, failed: _failed, failures: _failures.slice() };
}

// Auto-run + print when executed directly under Node
// (import.meta.url === the invoked script's file URL).
const _isNodeMain = typeof process !== 'undefined' && process.argv && process.argv[1]
  && import.meta.url === new URL(`file://${process.argv[1]}`).href;

if (_isNodeMain) {
  run().then((res) => {
    for (const f of res.failures) console.log('  FAIL  ' + f);
    console.log(`\n${res.passed} passed, ${res.failed} failed`);
    process.exit(res.failed === 0 ? 0 : 1);
  }).catch((e) => {
    console.error('runner crashed:', e);
    process.exit(2);
  });
}
