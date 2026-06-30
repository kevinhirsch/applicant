// ============================================================
// runner.js — Front-Door JS Test Runner
//
// Checks that each core module loads and exports what it should.
// Each "suite" is a group of related assertions.
// Suites are async so modules that do work at import time can
// settle before assertions run.
// ============================================================

/**
 * @typedef {{ name: string, status: 'pass'|'fail'|'skip', error?: string }} TestResult
 * @typedef {{ name: string, tests: TestResult[] }} SuiteResult
 * @typedef {{ total: number, passed: number, suites: SuiteResult[] }} RunResult
 */

// ── helpers ──────────────────────────────────────────────────

function pass(name) {
  return { name, status: 'pass' };
}

function fail(name, error) {
  const msg = error instanceof Error ? `${error.message}\n${error.stack}` : String(error);
  return { name, status: 'fail', error: msg };
}

function skip(name, reason) {
  return { name, status: 'skip', error: reason };
}

function assert(condition, name, detail) {
  if (condition) return pass(name);
  return fail(name, detail || `Assertion failed: ${name}`);
}

function assertType(val, expectedType, name) {
  const actual = typeof val;
  if (actual === expectedType) return pass(name);
  return fail(name, `Expected type "${expectedType}", got "${actual}"`);
}

function assertDefined(val, name) {
  if (val !== undefined && val !== null) return pass(name);
  return fail(name, `Expected value to be defined, got ${String(val)}`);
}

// ── suite runner ────────────────────────────────────────────

/**
 * Run a single test suite.
 * @param {string} name
 * @param {() => (TestResult|Promise<TestResult>)[]} fn
 * @returns {Promise<SuiteResult>}
 */
async function runSuite(name, fn) {
  const log = window.__testLog || (() => {});
  log(`Suite: ${name}`);
  let results;
  try {
    results = await fn();
  } catch (err) {
    log(`Suite error: ${err.message}`);
    return {
      name,
      tests: [fail('suite threw', err)],
    };
  }
  const tests = Array.isArray(results) ? results : [results];
  // flatten nested arrays
  const flat = tests.flat();
  return { name, tests: flat };
}

// ── suites ──────────────────────────────────────────────────

async function suiteStorage() {
  const mod = await import('../../frontend/static/js/storage.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.default, 'object', 'default export is an object'),
    assertType(mod.get, 'function', 'exports .get'),
    assertType(mod.set, 'function', 'exports .set'),
    assertType(mod.remove, 'function', 'exports .remove'),
    assertDefined(mod.KEYS, 'exports .KEYS'),
  ];
}

async function suiteUI() {
  const mod = await import('../../frontend/static/js/ui.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.el, 'function', 'exports .el'),
    assertType(mod.showToast, 'function', 'exports .showToast'),
    assertType(mod.showError, 'function', 'exports .showError'),
    assertType(mod.debounce, 'function', 'exports .debounce'),
    assertType(mod.esc, 'function', 'exports .esc'),
    assertType(mod.scrollHistory, 'function', 'exports .scrollHistory'),
  ];
}

async function suiteMarkdown() {
  const mod = await import('../../frontend/static/js/markdown.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.mdToHtml, 'function', 'exports .mdToHtml'),
    assertType(mod.renderContent, 'function', 'exports .renderContent'),
    assertType(mod.squashOutsideCode, 'function', 'exports .squashOutsideCode'),
    assertType(mod.extractThinkingBlocks, 'function', 'exports .extractThinkingBlocks'),
  ];
}

async function suiteSessions() {
  const mod = await import('../../frontend/static/js/sessions.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.loadSessions, 'function', 'exports .loadSessions'),
    assertType(mod.selectSession, 'function', 'exports .selectSession'),
    assertType(mod.getSessions, 'function', 'exports .getSessions'),
    assertType(mod.getCurrentSessionId, 'function', 'exports .getCurrentSessionId'),
    assertType(mod.createDirectChat, 'function', 'exports .createDirectChat'),
  ];
}

async function suiteModels() {
  const mod = await import('../../frontend/static/js/models.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.refreshModels, 'function', 'exports .refreshModels'),
    assertType(mod.getCachedItems, 'function', 'exports .getCachedItems'),
  ];
}

async function suiteSpinner() {
  const mod = await import('../../frontend/static/js/spinner.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.create, 'function', 'exports .create'),
    assertType(mod.createWhirlpool, 'function', 'exports .createWhirlpool'),
    assertType(mod.createLoadingRow, 'function', 'exports .createLoadingRow'),
    assertDefined(mod.Spinner, 'exports .Spinner (class)'),
  ];
}

async function suiteTheme() {
  const mod = await import('../../frontend/static/js/theme.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertDefined(mod.THEMES, 'exports .THEMES'),
    assertType(mod.applyColors, 'function', 'exports .applyColors'),
    assertType(mod.getSaved, 'function', 'exports .getSaved'),
  ];
}

async function suiteFileHandler() {
  const mod = await import('../../frontend/static/js/fileHandler.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.addFiles, 'function', 'exports .addFiles'),
    assertType(mod.openPicker, 'function', 'exports .openPicker'),
    assertType(mod.renderAttachStrip, 'function', 'exports .renderAttachStrip'),
  ];
}

async function suiteChatRenderer() {
  const mod = await import('../../frontend/static/js/chatRenderer.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.addMessage, 'function', 'exports .addMessage'),
    assertType(mod.hideWelcomeScreen, 'function', 'exports .hideWelcomeScreen'),
    assertType(mod.showWelcomeScreen, 'function', 'exports .showWelcomeScreen'),
  ];
}

async function suiteCensor() {
  const mod = await import('../../frontend/static/js/censor.js');
  return [
    assertDefined(mod.default, 'default export exists'),
    assertType(mod.init, 'function', 'exports .init'),
    assertType(mod.isEnabled, 'function', 'exports .isEnabled'),
    assertType(mod.setEnabled, 'function', 'exports .setEnabled'),
  ];
}

// ── main entry point ────────────────────────────────────────

/**
 * Run all test suites and return aggregated results.
 * @returns {Promise<RunResult>}
 */
export async function runAllSuites() {
  const suites = [
    ['storage', suiteStorage],
    ['ui', suiteUI],
    ['markdown', suiteMarkdown],
    ['sessions', suiteSessions],
    ['models', suiteModels],
    ['spinner', suiteSpinner],
    ['theme', suiteTheme],
    ['fileHandler', suiteFileHandler],
    ['chatRenderer', suiteChatRenderer],
    ['censor', suiteCensor],
  ];

  let total = 0;
  let passed = 0;
  const suiteResults = [];

  for (const [name, fn] of suites) {
    const result = await runSuite(name, fn);
    suiteResults.push(result);
    for (const t of result.tests) {
      total++;
      if (t.status === 'pass') passed++;
    }
  }

  return { total, passed, suites: suiteResults };
}
