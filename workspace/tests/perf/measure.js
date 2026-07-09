#!/usr/bin/env node
// workspace/tests/perf/measure.js — the X-3 performance-budget measurement rig.
//
// Records two latencies the X-3 DoD calls for, reusing the P0-6 visual
// harness's hermetic app-boot (../visual/boot.js) and its unlock fixture
// (../visual/fixtures.js) rather than standing up a second app-boot path:
//
//   login->interactive  — navigation of the authenticated shell (/) until the
//                         3-pane shell is interactive: the #app-loader splash
//                         has detached AND the composer is enabled (the same
//                         "boot settled" signal surfaces.js `_waitBoot` waits
//                         on). Measured browser-side via performance.now(),
//                         which is relative to the page's navigation start.
//   surface-open        — the hash-routed / launcher-driven page open (P0-3
//                         retired windows): time from the nav click to the
//                         target surface being visible + settled, for
//                         Today / Tracker / Results / Activity.
//
// UNLIKE the visual harness this rig does NOT freeze animation or pin
// performance.now()/Date — those pins exist for pixel determinism and would
// destroy every timing. It boots the SAME hermetic front-door (fresh SQLite,
// engine offline) so the numbers are reproducible and comparable run to run.
//
// HONEST CAVEAT (read docs/performance-budget.md): this runs headless with
// --disable-gpu on a GPU-less runner, so it measures LAYOUT + SCRIPT + PAINT
// setup cost on THIS box's Chromium, NOT the compositor/GPU cost of the glass
// blur + aurora on real modest hardware. The blur/aurora budget is therefore
// analytical, not measured here; the numbers below are the JS/layout envelope.
//
// Usage:
//   node workspace/tests/perf/measure.js               # boot + measure, print summary
//   node workspace/tests/perf/measure.js --iterations 6
//   node workspace/tests/perf/measure.js --base http://127.0.0.1:7000  # reuse a running front-door
//   node workspace/tests/perf/measure.js --json        # print machine-readable JSON only
//
// Writes workspace/tests/perf/.out/results.json (gitignored). Exit 0 on a
// clean measurement run; exit 1 if boot/login/navigation failed outright.

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');

const { bootFrontDoor } = require('../visual/boot');
const { installUnlockFixture } = require('../visual/fixtures');

const HERE = __dirname;
const OUT_DIR = path.join(HERE, '.out');

// ── CLI ──────────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const flags = {
  iterations: (() => { const i = argv.indexOf('--iterations'); return i >= 0 ? Number(argv[i + 1]) : 6; })(),
  base: (() => { const i = argv.indexOf('--base'); return i >= 0 ? argv[i + 1] : null; })(),
  port: (() => { const i = argv.indexOf('--port'); return i >= 0 ? Number(argv[i + 1]) : 7331; })(),
  json: argv.includes('--json'),
};

// ── Playwright resolution (mirrors ../visual/run.js) ─────────────────────────
function requirePlaywright() {
  try { return require('playwright'); } catch (_) { /* fall through */ }
  try {
    const root = execSync('npm root -g', { encoding: 'utf8' }).trim();
    return require(path.join(root, 'playwright'));
  } catch (e) {
    throw new Error('cannot resolve the playwright package (npm i -g playwright, or npm i playwright here)');
  }
}

function chromiumExecutable() {
  if (process.env.VISUAL_CHROMIUM) return process.env.VISUAL_CHROMIUM;
  const roots = [process.env.PLAYWRIGHT_BROWSERS_PATH, '/opt/pw-browsers'].filter(Boolean);
  for (const root of roots) {
    let entries = [];
    try { entries = fs.readdirSync(root).filter((d) => d.startsWith('chromium') && !d.includes('headless')).sort().reverse(); } catch (_) { continue; }
    for (const dir of entries) {
      const cand = path.join(root, dir, 'chrome-linux', 'chrome');
      if (fs.existsSync(cand)) return cand;
    }
  }
  return null;
}

// The surfaces to time. Each opens via the SAME click-path/launcher a user
// drives (P0-3 hash-routed page open), and settles on its modal root.
const SURFACES = [
  {
    name: 'today', label: 'Today (Portal home base)',
    open: async (page) => { await page.evaluate(() => window.applicantPortalModule && window.applicantPortalModule.openApplicantPortal()); },
    root: '#applicant-portal-modal',
  },
  {
    name: 'tracker', label: 'Tracker',
    open: async (page) => { await page.click('#tool-tracker-btn'); },
    root: '#applicant-tracker-modal',
  },
  {
    name: 'results', label: 'Results',
    open: async (page) => { await page.click('#tool-results-btn'); },
    root: '#applicant-results-modal',
  },
  {
    name: 'activity', label: 'Activity',
    open: async (page) => { await page.click('#tool-activity-btn'); },
    root: '#applicant-activity-modal',
  },
];

// Land on the bare 3-pane shell: the post-login flow auto-opens the Portal
// home base (and the OOBE wizard when setup is incomplete) — dismiss them the
// way a user would so the next surface opens from a clean shell. Mirrors
// surfaces.js `_clearLanding`; crucially it does NOT delete the portal's own
// cached modal node (openApplicant*() reuses it), only the wizard overlay.
async function clearLanding(page) {
  await page.evaluate(() => {
    // Close the auto-opened Portal via its button — this HIDES it (keeps the
    // cached node attached) so openApplicantPortal() can re-show it. The Portal
    // modal is itself `.modal.ow-window`, so we must NOT blanket-remove that
    // class; only the OOBE wizard overlay (its own id) is torn down.
    const close = document.getElementById('applicant-portal-close');
    if (close) close.click();
    const wiz = document.getElementById('applicant-onboarding-overlay');
    if (wiz && wiz.parentNode) wiz.parentNode.removeChild(wiz);
  }).catch(() => {});
  await page.waitForTimeout(250);
}

// Wait for the shell to be interactive: splash detached + composer enabled.
// The same "boot settled" signal surfaces.js `_waitBoot` waits on.
async function waitInteractive(page) {
  // The z-index:99999 app-loader splash covers everything until app.js boots.
  await page.waitForSelector('#app-loader', { state: 'detached', timeout: 30000 }).catch(() => {});
  // Composer re-enables once the assistant session is fully selected — the
  // steady interactive state of the shell.
  await page.waitForSelector('#message:not([disabled])', { state: 'attached', timeout: 20000 }).catch(() => {});
}

// Boot the authenticated shell to interactive on a fresh page and return the
// browser-side performance.now() at that instant (≈ ms from the page's
// navigation start), plus the Navigation Timing landmarks.
async function loginToInteractive(context, base) {
  const page = await context.newPage();
  await installUnlockFixture(page);
  await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await waitInteractive(page);
  const timing = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const fcp = performance.getEntriesByType('paint').find((e) => e.name === 'first-contentful-paint');
    return {
      interactiveMs: performance.now(),
      domContentLoaded: nav.domContentLoadedEventEnd || null,
      domInteractive: nav.domInteractive || null,
      loadEventEnd: nav.loadEventEnd || null,
      firstContentfulPaint: fcp ? fcp.startTime : null,
    };
  });
  return { page, timing };
}

// Measure one surface open on a FRESH interactive page (one page per surface,
// matching the visual harness's per-state page model — no cross-surface DOM
// contamination, no stale cached-node reuse). Uses browser-side
// performance.now() around the click→visible→settle so Node scheduling jitter
// never enters the number.
async function measureSurface(context, base, surface) {
  const page = await context.newPage();
  try {
    await installUnlockFixture(page);
    await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await waitInteractive(page);
    await clearLanding(page);
    const t0 = await page.evaluate(() => performance.now());
    await surface.open(page);
    await page.waitForSelector(surface.root, { state: 'visible', timeout: 15000 });
    // One rAF-settled frame after the root is visible = "surface is up and
    // painted", the interactive moment a user perceives.
    const t1 = await page.evaluate(() => new Promise((res) => {
      requestAnimationFrame(() => requestAnimationFrame(() => res(performance.now())));
    }));
    return t1 - t0;
  } finally {
    await page.close().catch(() => {});
  }
}

function stats(xs) {
  if (!xs.length) return { n: 0 };
  const s = [...xs].sort((a, b) => a - b);
  const median = s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
  return {
    n: s.length,
    min: Math.round(s[0]),
    median: Math.round(median),
    max: Math.round(s[s.length - 1]),
    p95: Math.round(s[Math.min(s.length - 1, Math.ceil(0.95 * s.length) - 1)]),
  };
}

async function main() {
  const playwright = requirePlaywright();
  fs.mkdirSync(OUT_DIR, { recursive: true });

  let server = null;
  let base = flags.base;
  let creds = { user: process.env.ADMIN_USER || 'admin', password: process.env.ADMIN_PASSWORD || '' };
  if (!base) {
    server = await bootFrontDoor(flags.port);
    base = server.base;
    creds = { user: server.user, password: server.password };
  }

  // Headless, GPU-less (this runner has no GPU) — see the caveat at the top and
  // in docs/performance-budget.md. --disable-gpu is why blur/aurora COMPOSITOR
  // cost is analytical, not measured here.
  const launch = {
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--force-color-profile=srgb'],
  };
  const exe = chromiumExecutable();
  if (exe) launch.executablePath = exe;

  const loginSamples = [];
  const navTiming = { domContentLoaded: [], domInteractive: [], firstContentfulPaint: [], loadEventEnd: [] };
  const surfaceSamples = Object.fromEntries(SURFACES.map((s) => [s.name, []]));
  let browser = null;

  try {
    browser = await playwright.chromium.launch(launch);
    for (let i = 0; i < flags.iterations; i++) {
      // Fresh cookie-authenticated context per iteration — a clean cold-ish
      // shell boot each time (the browser process/glyph cache stays warm after
      // iter 0, which is the honest "returning user" envelope).
      const context = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        serviceWorkers: 'block',
        timezoneId: 'UTC',
        locale: 'en-US',
        deviceScaleFactor: 1,
      });
      const resp = await context.request.post(`${base}/api/auth/login`, {
        data: { username: creds.user, password: creds.password },
        headers: { Origin: base, Referer: `${base}/login` },
      });
      if (!resp.ok()) throw new Error(`login failed (${resp.status()})`);

      const { page, timing } = await loginToInteractive(context, base);
      loginSamples.push(timing.interactiveMs);
      if (timing.domContentLoaded) navTiming.domContentLoaded.push(timing.domContentLoaded);
      if (timing.domInteractive) navTiming.domInteractive.push(timing.domInteractive);
      if (timing.firstContentfulPaint) navTiming.firstContentfulPaint.push(timing.firstContentfulPaint);
      if (timing.loadEventEnd) navTiming.loadEventEnd.push(timing.loadEventEnd);

      await page.close().catch(() => {});
      for (const surface of SURFACES) {
        try { surfaceSamples[surface.name].push(await measureSurface(context, base, surface)); }
        catch (e) { console.error(`  surface ${surface.name} iter ${i}: ${String(e.message).split('\n')[0]}`); }
      }
      await context.close();
      if (!flags.json) console.error(`  iter ${i + 1}/${flags.iterations}: login->interactive ${Math.round(timing.interactiveMs)}ms`);
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) await server.stop();
  }

  // Warm = drop the first (cold) iteration; report both.
  const warm = (xs) => xs.slice(1);
  const report = {
    when: new Date().toISOString(),
    iterations: flags.iterations,
    env: { headless: true, gpu: false, note: 'GPU-less headless Chromium on the CI-class runner; blur/aurora compositor cost is analytical, not measured here.' },
    loginToInteractive: { all: stats(loginSamples), cold: Math.round(loginSamples[0] || 0), warm: stats(warm(loginSamples)) },
    navTiming: Object.fromEntries(Object.entries(navTiming).map(([k, v]) => [k, stats(v)])),
    surfaceOpen: Object.fromEntries(SURFACES.map((s) => [s.name, { label: s.label, all: stats(surfaceSamples[s.name]), warm: stats(warm(surfaceSamples[s.name])) }])),
  };
  fs.writeFileSync(path.join(OUT_DIR, 'results.json'), JSON.stringify(report, null, 2));

  if (flags.json) { console.log(JSON.stringify(report, null, 2)); return 0; }

  console.log('\n=== X-3 performance measurement (headless Chromium, GPU-less) ===');
  console.log(`iterations: ${flags.iterations} (warm = iterations 2..${flags.iterations}, cold = iteration 1)\n`);
  console.log('login->interactive (ms, from navigation start to shell interactive):');
  console.log(`  cold ${report.loginToInteractive.cold}   warm median ${report.loginToInteractive.warm.median}   warm p95 ${report.loginToInteractive.warm.p95}   (all: median ${report.loginToInteractive.all.median}, min ${report.loginToInteractive.all.min}, max ${report.loginToInteractive.all.max})`);
  console.log(`  DOMContentLoaded median ${report.navTiming.domContentLoaded.median}   FCP median ${report.navTiming.firstContentfulPaint.median || 'n/a'}\n`);
  console.log('surface-open (ms, click -> surface visible + one settled frame):');
  for (const s of SURFACES) {
    const st = report.surfaceOpen[s.name].warm;
    console.log(`  ${s.label.padEnd(26)} warm median ${st.median}   warm max ${st.max}   (all median ${report.surfaceOpen[s.name].all.median})`);
  }
  console.log(`\nWrote ${path.relative(process.cwd(), path.join(OUT_DIR, 'results.json'))}`);
  return 0;
}

main().then((code) => process.exit(code), (e) => { console.error(e); process.exit(1); });
