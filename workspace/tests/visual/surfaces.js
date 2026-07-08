// workspace/tests/visual/surfaces.js
//
// THE MATRIX for the P0-6 visual regression harness: which states are
// walked, at which viewports, under which themes. Lifted from the §6a
// monkey/crawl surface table (scripts/playtest_crawl.py) and extended per the
// P0-6 DoD: login → Today → each nav section → Settings (each group) → theme
// picker → wizard steps, plus the P0-3 gadget-rail states (pinned / collapsed
// slim badge strip / notifications expanded).
//
// Every state is walked at BOTH viewports under BOTH themes. The engine is
// not required: with no engine the surfaces render their honest offline /
// gated / empty states, and those ARE the pinned baselines. The three rail-*
// states stub the rail's read-only proxy endpoints with fixed fixtures
// (fixtures.js) so the gadget stack / badge strip / waiting queue actually
// render — the engine's demo lane (dev_seed) needs a live Postgres engine,
// which this hermetic harness deliberately does not boot.

'use strict';

// ── Viewports (P0-6 DoD) ─────────────────────────────────────────────────────
const VIEWPORTS = [
  { tag: '1440x900', width: 1440, height: 900 },
  { tag: '1024x768', width: 1024, height: 768 },
];

// ── Themes (P0-6 DoD: white-glass + one dark theme) ─────────────────────────
// Stored exactly as theme.js's save() persists them (localStorage
// 'applicant-theme' = { name, colors }); colors mirror theme.js THEMES so the
// anti-FOUC head script and applyColors() reproduce the shipped look. `glass`
// is the vendored OOBE default ("white glass"); `dark` is the classic dark.
const THEMES = [
  {
    tag: 'glass',
    stored: {
      name: 'glass',
      colors: { bg: '#15171c', fg: '#eef1f4', panel: '#1d2026', border: '#3a3f47', red: '#9aa3af', glassTier: 'full', glass: true },
      // Tier pinned to 'frosted' (the same light Apple-glass material) rather
      // than the shipped 'full' default: 'full' additionally layers the
      // appkitGlass SVG refraction, whose feImage lens paints ASYNCHRONOUSLY —
      // whether it lands before the screenshot is a race no clock pin can fix.
      // Frosted keeps blur+saturate glass deterministic; the refraction lens
      // is the one shipped visual this harness deliberately does not pin.
      glassTier: 'frosted',
    },
  },
  {
    tag: 'dark',
    stored: {
      name: 'dark',
      colors: { bg: '#282c34', fg: '#9cdef2', panel: '#111111', border: '#355a66', red: '#e06c75' },
      // Same tier pin as glass (see above): the app-wide default is 'full',
      // whose SVG refraction lens paints asynchronously and cannot be pinned.
      glassTier: 'frosted',
    },
  },
];

// ── Shared helpers used by state `open` steps ───────────────────────────────

async function _waitBoot(page) {
  // The z-index:99999 app-loader splash covers everything until app.js boots.
  try { await page.waitForSelector('#app-loader', { state: 'detached', timeout: 20000 }); } catch (_) { /* slow boot — screenshot the truth */ }
  // The shell is BISTABLE right after boot: the chat-unification probe
  // asynchronously selects the assistant session (welcome screen → unified
  // "Job assistant" pane with its greeting bubble). Which side a screenshot
  // lands on is a race no fixed settle can pin — wait for the probe's steady
  // state (the greeting message in #chat-history) before any state opens.
  try { await page.waitForSelector('#chat-history .msg', { state: 'attached', timeout: 15000 }); } catch (_) { /* engine-less edge — capture the truth */ }
  // selectSession() re-enables (and on desktop focuses) the composer once the
  // session is fully selected — the disabled composer renders as a dimmer
  // translucent bar, so a shot racing that flip flakes. Wait for the enabled
  // steady state.
  try { await page.waitForSelector('#message:not([disabled])', { state: 'attached', timeout: 10000 }); } catch (_) { /* composer stays gated — capture the truth */ }
  // The glass tier (body.theme-frosted — both matrix themes pin 'frosted')
  // is applied by initThemeUI AFTER an async server prefs sync; the frosted
  // material landing mid-capture repaints the composer/rail/pill chrome.
  try { await page.waitForSelector('body.theme-frosted', { state: 'attached', timeout: 10000 }); } catch (_) { /* tier never applied — capture the truth */ }
  await page.waitForTimeout(600);
}

// Land on the bare shell: the post-login flow auto-opens the Portal home base
// (and the OOBE wizard when it takes precedence) — close/remove them so the
// state starts from the naked 3-pane shell. Mirrors playtest_crawl.py.
async function _clearLanding(page) {
  await page.evaluate(() => {
    const close = document.getElementById('applicant-portal-close');
    if (close) close.click();
    const wiz = document.querySelector('.modal.ow-window');
    if (wiz && wiz.parentNode) wiz.parentNode.removeChild(wiz);
  });
  await page.waitForTimeout(300);
}

async function _clickAndSettle(page, selector, rootSel) {
  const el = await page.$(selector);
  if (!el) throw new Error(`opener ${selector} not found`);
  await el.click({ timeout: 4000 });
  if (rootSel) {
    await page.waitForSelector(rootSel, { state: 'visible', timeout: 6000 });
  }
  await page.waitForTimeout(700);
}

async function _openSettingsTab(page, tab) {
  await _clickAndSettle(page, '#user-bar-settings', '#settings-modal');
  await _clickAndSettle(page, `[data-settings-tab="${tab}"]`);
  await page.waitForTimeout(400);
}

async function _openWizard(page, skips) {
  await page.evaluate(() => window.launchApplicantSetup && window.launchApplicantSetup());
  await page.waitForSelector('#applicant-onboarding-overlay', { state: 'visible', timeout: 8000 });
  await page.waitForTimeout(600);
  for (let i = 0; i < skips; i++) {
    await page.waitForSelector('#ao-skip', { state: 'visible', timeout: 6000 });
    await page.click('#ao-skip');
    await page.waitForTimeout(700);
  }
}

// ── States ───────────────────────────────────────────────────────────────────
//
// Fields:
//   name        stable id (baseline filename)
//   preAuth     runs before login (fresh, cookie-less)
//   path        goto target (default '/')
//   localStorage extra keys seeded before load (rail layout states)
//   fixtures    'rail' -> stub the rail proxy endpoints (fixtures.js)
//   open(page)  navigation steps from the booted shell to the state
const STATES = [
  // 1. Login (pre-auth).
  { name: 'login', preAuth: true, path: '/login', open: async (page) => { await page.waitForTimeout(800); } },

  // 2. The bare 3-pane shell.
  { name: 'home', open: async (page) => { await _clearLanding(page); } },

  // 3. Today — the Pending-Actions Portal home base (as the landing leaves it).
  {
    name: 'today',
    open: async (page) => {
      await page.evaluate(() => window.applicantPortalModule && window.applicantPortalModule.openApplicantPortal());
      await page.waitForSelector('#applicant-portal-modal', { state: 'visible', timeout: 8000 });
      await page.waitForTimeout(700);
    },
  },

  // 4. Each nav section (the applicantNav.js single-source NAV array).
  { name: 'nav-tracker', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-tracker-btn', '#applicant-tracker-modal'); } },
  { name: 'nav-results', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-results-btn', '#applicant-results-modal'); } },
  { name: 'nav-activity', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-activity-btn', '#applicant-activity-modal'); } },
  { name: 'nav-documents', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-library-btn'); await page.waitForTimeout(600); } },
  { name: 'nav-gallery', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-applicant-gallery-btn', '#applicant-gallery-modal'); } },
  { name: 'nav-profile', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-memory-btn'); await page.waitForTimeout(600); } },
  { name: 'nav-daily-updates', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-email-btn'); await page.waitForTimeout(600); } },
  { name: 'nav-calendar', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-calendar-btn'); await page.waitForTimeout(600); } },
  // Chat is UNIFIED into the native chat plane (applicantChat.js: "there is no
  // modal to hide") — no root selector; the click mutates the center pane. With
  // the engine offline its "assistant unavailable" toast is part of the state.
  { name: 'nav-chat', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-assistant-btn'); await page.waitForTimeout(600); } },
  { name: 'nav-compare', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-compare-btn', '#applicant-compare-modal'); } },
  { name: 'nav-runlog', fixtures: 'unlock', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-debug-btn', '#applicant-debug-modal'); } },

  // 5. Settings — the FIRST tab of each labelled sidebar group (AI & Models /
  // Applicant / Notifications / Appearance / Account / Admin).
  { name: 'settings-ai-models', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'services'); } },
  { name: 'settings-applicant', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'campaign'); } },
  { name: 'settings-notifications', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'integrations'); } },
  { name: 'settings-appearance', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'appearance'); } },
  { name: 'settings-account', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'account'); } },
  { name: 'settings-admin', open: async (page) => { await _clearLanding(page); await _openSettingsTab(page, 'tools'); } },

  // 6. The theme picker (its own nav destination since S1-6).
  { name: 'theme-picker', open: async (page) => { await _clearLanding(page); await _clickAndSettle(page, '#tool-theme-nav-btn', '#theme-modal'); } },

  // 7. Wizard steps: Welcome → Connect a model → Your profile.
  { name: 'wizard-welcome', open: async (page) => { await _clearLanding(page); await _openWizard(page, 0); } },
  { name: 'wizard-model', open: async (page) => { await _clearLanding(page); await _openWizard(page, 1); } },
  { name: 'wizard-profile', open: async (page) => { await _clearLanding(page); await _openWizard(page, 2); } },

  // 8. P0-3 gadget-rail states (fixture-fed so the gadgets/queue render).
  {
    name: 'rail-pinned',
    fixtures: 'rail',
    localStorage: { 'applicant-rail-pins': '["digest","health"]' },
    open: async (page) => {
      await _clearLanding(page);
      await page.waitForSelector('#applicant-rail-gadgets .applicant-rail-gadget', { state: 'visible', timeout: 8000 });
      await page.waitForTimeout(500);
    },
  },
  {
    name: 'rail-collapsed',
    fixtures: 'rail',
    localStorage: { 'applicant-rail-collapsed': '1' },
    open: async (page) => {
      await _clearLanding(page);
      await page.waitForSelector('#applicant-rail-badges .applicant-rail-badge', { state: 'visible', timeout: 8000 });
      await page.waitForTimeout(500);
    },
  },
  {
    name: 'rail-notifications',
    fixtures: 'rail',
    open: async (page) => {
      await _clearLanding(page);
      await page.waitForSelector('#applicant-rail-waiting.has-items', { state: 'visible', timeout: 8000 });
      await page.waitForTimeout(500);
    },
  },
];

module.exports = { VIEWPORTS, THEMES, STATES, _waitBoot };
