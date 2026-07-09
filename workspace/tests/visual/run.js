#!/usr/bin/env node
// workspace/tests/visual/run.js — the P0-6 visual regression harness.
//
// Walks the front-door surface matrix (surfaces.js: login → Today → each nav
// section → Settings groups → theme picker → wizard steps → the P0-3 rail
// states) at 1440×900 and 1024×768 under the white-glass and dark themes,
// screenshots each state, and pixel-compares against the committed baselines
// in workspace/tests/visual/baselines/. On every state it ALSO runs the
// off-screen element detector and the horizontal-overflow assert
// (detector.js) — a layout escape fails the run even when pixels match a
// stale baseline.
//
// Determinism (two consecutive runs produce a ZERO pixel diff):
//   - fresh hermetic boot per run (boot.js: new SQLite, fixed admin, engine
//     offline on purpose) — no accumulated server state;
//   - the clock is pinned (Date + performance.now), Math.random is seeded,
//     timezone/locale are fixed (UTC / en-US);
//   - animation is frozen: prefers-reduced-motion + a global
//     animation/transition/caret kill switch injected per page;
//   - service workers are blocked (no cache-dependent rendering);
//   - localStorage/sessionStorage are cleared and re-seeded per page.
//
// Usage:
//   node workspace/tests/visual/run.js                  # compare against baselines (CI mode)
//   node workspace/tests/visual/run.js --bless          # accept current rendering as baseline
//   node workspace/tests/visual/run.js --only 'rail-.*' # subset (regex on state name)
//   node workspace/tests/visual/run.js --base http://127.0.0.1:7000  # reuse a running front-door
//   node workspace/tests/visual/run.js --engine firefox # X-2 cross-browser smoke (firefox|webkit)
//   node workspace/tests/visual/run.js --engine webkit  # WebKit golden-path smoke
//
// Exit 0 = green. Exit 1 = visual diff / layout violation / missing baseline;
// diff images land in workspace/tests/visual/.out/diff/. `--bless` is the
// ONLY way to accept a visual change.
//
// ── Engines (X-2) ────────────────────────────────────────────────────────────
// --engine chromium (DEFAULT) is the pixel-pinned Visual Lane: it compares the
// posterized screenshot of every state against the committed baselines/ AND
// runs the layout detectors. Unchanged by X-2.
// --engine firefox | webkit is a cross-browser SMOKE: it walks the SAME matrix
// and enforces the SAME layout/error contract (no page errors, no off-screen
// escapes, no horizontal overflow), but does NOT pixel-compare against the
// Chromium baselines — cross-engine glyph raster + compositing legitimately
// differ, so a cross-engine pixel diff is noise. Screenshots still land in
// .out/current for eyeballing; an optional per-engine baselines-<engine>/ dir
// can be blessed but never gates. The golden path "passes in FF+WebKit" when
// this smoke is green.
//
// Requires the `playwright` npm package (resolved locally or from the global
// npm root) and the engine binary: Chromium from PLAYWRIGHT_BROWSERS_PATH or a
// chromium-* dir under /opt/pw-browsers; Firefox/WebKit resolved by Playwright
// from PLAYWRIGHT_BROWSERS_PATH (install with `npx playwright install --with-deps
// firefox webkit` — WebKit-on-Linux needs extra system libs; see
// docs/integration-runner-setup.md).

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');

const { VIEWPORTS, THEMES, STATES, _waitBoot } = require('./surfaces');
const { installRailFixtures, installUnlockFixture } = require('./fixtures');
const { OFFSCREEN_ALLOWLIST, findOffscreenElements, checkHorizontalOverflow } = require('./detector');
const { decodePNG, encodePNG, comparePNG, posterize } = require('./png');
const { bootFrontDoor } = require('./boot');

const HERE = __dirname;
const OUT_DIR = path.join(HERE, '.out');

// The pinned wall clock every page sees: 2026-07-01 14:30 UTC (a Wednesday).
const FIXED_TS = Date.UTC(2026, 6, 1, 14, 30, 0);

// ── CLI ──────────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const ENGINES = ['chromium', 'firefox', 'webkit'];
const flags = {
  bless: argv.includes('--bless'),
  only: (() => { const i = argv.indexOf('--only'); return i >= 0 ? new RegExp(argv[i + 1]) : null; })(),
  base: (() => { const i = argv.indexOf('--base'); return i >= 0 ? argv[i + 1] : null; })(),
  port: (() => { const i = argv.indexOf('--port'); return i >= 0 ? Number(argv[i + 1]) : 7311; })(),
  // X-2 cross-browser smoke: which Playwright engine drives the walk. Default
  // chromium keeps the per-PR / pre-push Visual Lane byte-identical — nothing
  // about the default path changes. firefox|webkit run the SAME surface matrix
  // as a functional/layout SMOKE (errors + off-screen + horizontal-overflow
  // asserts), but do NOT pixel-compare against the Chromium baselines: cross-
  // engine glyph rasterization + compositing differ, so a cross-engine pixel
  // diff is noise, not signal. The golden-path pass/fail for FF/WebKit is the
  // layout/error contract, exactly the machine-independent half of the harness.
  engine: (() => { const i = argv.indexOf('--engine'); return i >= 0 ? String(argv[i + 1]) : 'chromium'; })(),
};
if (!ENGINES.includes(flags.engine)) {
  console.error(`--engine must be one of ${ENGINES.join('|')} (got '${flags.engine}')`);
  process.exit(2);
}
const ENGINE = flags.engine;
const IS_CHROMIUM = ENGINE === 'chromium';
// Chromium keeps the committed baseline dir; other engines get their OWN dir so
// an optional cross-engine bless never touches the P0-6 Chromium baselines.
const BASELINE_DIR = path.join(HERE, IS_CHROMIUM ? 'baselines' : `baselines-${ENGINE}`);

// ── Playwright resolution (no local node_modules needed) ─────────────────────
function requirePlaywright() {
  try { return require('playwright'); } catch (_) { /* fall through */ }
  try {
    const root = execSync('npm root -g', { encoding: 'utf8' }).trim();
    return require(path.join(root, 'playwright'));
  } catch (e) {
    throw new Error('cannot resolve the playwright package (npm i -g playwright, or npm i playwright here)');
  }
}

// Resolve a browser executable out of PLAYWRIGHT_BROWSERS_PATH / /opt/pw-browsers.
// Chromium is pinned by explicit path (the Visual Lane's determinism contract
// relies on the exact binary); Firefox/WebKit return null so Playwright resolves
// its own bundled build from PLAYWRIGHT_BROWSERS_PATH — those engines are the
// on-demand smoke, not the pixel-pinned lane, so an explicit path isn't needed.
function browserExecutable(engine) {
  if (engine !== 'chromium') return null; // let Playwright resolve FF/WebKit itself
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

// ── Determinism init script (runs before every page's own scripts) ───────────
function initScript(themeStored, extraLS) {
  return `(() => {
    // Pinned wall clock — every render sees the same "now".
    const FIXED = ${FIXED_TS};
    const RealDate = Date;
    class PinnedDate extends RealDate {
      constructor(...a) { if (a.length === 0) { super(FIXED); } else { super(...a); } }
      static now() { return FIXED; }
    }
    PinnedDate.parse = RealDate.parse.bind(RealDate);
    PinnedDate.UTC = RealDate.UTC.bind(RealDate);
    window.Date = PinnedDate;
    try { performance.now = () => 42000; } catch (_) {}
    // Seeded PRNG (mulberry32) — particle seeds, jitter, ids all reproduce.
    let s = 0x9e3779b9;
    Math.random = () => {
      s |= 0; s = (s + 0x6d2b79f5) | 0;
      let t = Math.imul(s ^ (s >>> 15), 1 | s);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    // Clean, explicit client state per page.
    try {
      localStorage.clear();
      sessionStorage.clear();
      localStorage.setItem('applicant-theme', ${JSON.stringify(JSON.stringify(themeStored))});
      // First-open tour hints (tourHints.js) pop over whatever surface opens
      // first — mark them seen so every state shoots its OWN chrome, not the
      // hint card. (The hint gets its own pinned state instead if ever needed.)
      localStorage.setItem('applicant-hint-drag-to-snap-seen', '1');
      const extra = ${JSON.stringify(extraLS || {})};
      for (const k of Object.keys(extra)) localStorage.setItem(k, extra[k]);
    } catch (_) {}
  })();`;
}

const FREEZE_CSS = `
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
  }
  html { scroll-behavior: auto !important; }
  /* Decorative particle canvases (login rain/particles, the theme bg-effect
     canvases) advance per FRAME, not per clock — the pinned Date cannot make
     their draw order reproducible across runs. They are pure decoration, so
     the harness excludes them from pinning; the CSS gradient behind them
     still ships in every baseline. */
  canvas.login-bg-particles,
  #synapse-canvas, #rain-canvas, #constellations-canvas, #perlin-flow-canvas,
  #petals-canvas, #sparkles-canvas, #embers-canvas {
    visibility: hidden !important;
  }
  /* The aurora MESH wallpaper (#__wp / .login-bg-gradient) is the other
     decorative layer whose paint is not run-reproducible: every translucent
     surface above it (frosted rail cards, composer, pills) re-rasterizes its
     text against that backdrop, so mesh variance flakes text antialiasing
     app-wide. Hide the mesh child; #__wp keeps the preset's solid base color
     (mirrored onto it by theme.js), so glass surfaces still composite over
     the theme's real base tone. */
  #__wp .login-bg-gradient, .login-bg-gradient {
    visibility: hidden !important;
  }
  /* The gadget rail's translucent cards re-rasterize their text at a
     run-variable subpixel phase (layer-promotion dependent, even with LCD
     text off). Pin the card MATERIAL to the theme's opaque panel color in
     the harness so the rail's layout/content/text stay pixel-pinned; the
     frosted material itself is still exercised by every other surface. */
  .applicant-gadget-rail .admin-card {
    background: var(--panel) !important;
    backdrop-filter: none !important;
  }
  /* ...and the rail CONTAINER itself ships translucent (color-mix ... 92%,
     transparent), so even over a pinned card the text still composites
     through a second translucent layer whose promotion is run-variable —
     card text AA kept flaking a few dozen px per run. Pin the rail opaque
     in the harness; every other surface still exercises the translucency. */
  .applicant-gadget-rail {
    background: var(--bg) !important;
  }
  /* The rail's small text ships with FRACTIONAL metrics (11.5px font,
     line-height 1.4 ⇒ 16.1px line boxes), and Chromium rounds a fractional
     line box to either side of the pixel boundary depending on per-LAUNCH
     glyph-cache state (verified: renders within one launch are byte-identical;
     separate launches disagree by exactly one text row, ±1px). Pin the rail's
     text to integer metrics in the harness so the rounding has nothing to
     flip on; the shipped fractional metrics still render everywhere else. */
  .applicant-gadget-rail, .applicant-gadget-rail * {
    font-size: 12px !important;
    line-height: 16px !important;
    letter-spacing: 0 !important;
  }
`;

// ── Masks: residual dynamic regions (per the P0-6 DoR) ───────────────────────
// Each masked element is painted over with a solid magenta box before the
// screenshot — identically at bless and at compare — so a region whose pixels
// are sub-perceptually nondeterministic cannot flake the run. Keep entries
// PRECISE and reasoned; a mask hides real UI from the diff.
const MASKS = [
  // The sidebar user chip (avatar + name): its text/avatar rasterization
  // shows sub-pixel antialiasing jitter across otherwise identical runs
  // (~40px of sub-perceptual noise over the frosted sidebar material).
  { selector: '#user-bar-profile', reason: 'avatar+name AA jitter over the frosted sidebar' },
  // The chat composer bar: its chrome settles through several independent
  // async flips (session-select re-enable, desktop autofocus + modal-close
  // focus restore, model-chip fetch, frost tier application) — after pinning
  // focus/tier/AA the band still lands on either side of a race, and its
  // exact height jitters a few px with it. The bar is identical vendored
  // chrome on every shell state; masking it (down to the viewport bottom —
  // it is the bottommost element) keeps the whole surface pinned without
  // gating on its internal races.
  // DESKTOP-ONLY (X-1): the race sources are desktop-specific — the composer
  // autofocuses only at desktop widths, and the modal-close focus-restore
  // races it there. At mobile widths the composer does NOT autofocus, so it
  // settles deterministically (verified by the two-run zero-diff bless), and
  // `toBottom` here would paint magenta over the bottom of every mobile
  // BOTTOM SHEET — exactly where the sheet's primary actions live (Save job,
  // the wizard's Continue, etc.). Skipping it on mobile keeps those visible in
  // the baseline; the sheet's own chrome is what the mobile cell is there to pin.
  { selector: '.chat-input-bar', reason: 'composer chrome settles through unpinnable async flips (enable/focus/model-chip)', toBottom: true, desktopOnly: true },
  // The gadget rail's two text stacks: their glyph raster varies per BROWSER
  // LAUNCH (in-place, ±1 row of AA per text line; runs within one launch are
  // byte-identical). Five pinning mechanisms failed to remove it (opaque
  // card+rail background, --disable-lcd-text/-font-subpixel-positioning/
  // --font-render-hinting=none, warm-up capture, integer font metrics,
  // pixel-grid snap of the rail column), so the TEXT pixels are masked; the
  // rail's geometry/chrome around the masks stays pixel-pinned, and the
  // stacks' CONTENT and ORDER are pinned by the headless composition tests
  // (workspace/tests/js + test_applicant_* rail suites), not by raster.
  { selector: '#applicant-rail-waiting', reason: 'per-launch glyph raster variance; content pinned by composition tests' },
  { selector: '#applicant-rail-gadgets', reason: 'per-launch glyph raster variance; content/order pinned by composition tests' },
];

// Masks snap OUTWARD to a coarse grid (with padding) so a few pixels of
// run-to-run geometry jitter in the masked element cannot move the mask's own
// boundary — the box lands on the same grid cell either way, and the halo/
// shadow around the element falls inside the padding.
const MASK_PAD = 24;
const MASK_GRID = 96;

async function applyMasks(page) {
  // Desktop-only masks (the composer bar) are skipped at mobile widths — they
  // exist for desktop-specific races and would otherwise paint over mobile
  // bottom-sheet content (see the `.chat-input-bar` mask note above).
  const vp = page.viewportSize();
  const isMobile = !!vp && vp.width < 768;
  const active = MASKS.filter((m) => !(m.desktopOnly && isMobile));
  await page.evaluate((masks) => {
    const PAD = masks.pad, GRID = masks.grid;
    for (const spec of masks.entries) {
      document.querySelectorAll(spec.selector).forEach((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return;
        const x0 = Math.max(0, Math.floor((r.left - PAD) / GRID) * GRID);
        const y0 = Math.max(0, Math.floor((r.top - PAD) / GRID) * GRID);
        const x1 = Math.ceil((r.right + PAD) / GRID) * GRID;
        const y1 = spec.toBottom
          ? document.documentElement.clientHeight
          : Math.ceil((r.bottom + PAD) / GRID) * GRID;
        const m = document.createElement('div');
        m.setAttribute('data-visual-mask', '1');
        m.style.cssText = 'position:fixed;left:' + x0 + 'px;top:' + y0 +
          'px;width:' + (x1 - x0) + 'px;height:' + (y1 - y0) +
          'px;background:#b6006c;z-index:2147483647;pointer-events:none;';
        document.body.appendChild(m);
      });
    }
  }, { entries: active, pad: MASK_PAD, grid: MASK_GRID }).catch(() => {});
}

// ── Capture one state ────────────────────────────────────────────────────────
async function captureState(context, state, base) {
  const page = await context.newPage();
  const record = { errors: [], offscreen: [], overflow: null, shot: null };
  try {
    if (state.fixtures === 'rail') await installRailFixtures(page);
    if (state.fixtures === 'unlock') await installUnlockFixture(page);
    await page.goto(base + (state.path || '/'), { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.addStyleTag({ content: FREEZE_CSS });
    if (!state.preAuth) await _waitBoot(page);
    await state.open(page);
    // Fonts must be in before pixels are pinned.
    await page.evaluate(() => (document.fonts && document.fonts.ready) || true).catch(() => {});
    await page.waitForTimeout(300);

    // Focus is not pinnable: modal closes restore focus asynchronously, and
    // the composer autofocuses on desktop widths — whether the focus ring /
    // expanded-composer chrome is up at shot time is a race. Blur to the one
    // steady no-focus state on every capture.
    await page.evaluate(() => {
      if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    }).catch(() => {});
    await page.waitForTimeout(150);

    // Layout assertions — every state, every viewport, every theme. Run AFTER
    // the blur/settle above: chrome that is still mid-flip (the composer bar's
    // async height settles) would otherwise flag transient geometry as an
    // off-screen escape.
    const off = await findOffscreenElements(page, OFFSCREEN_ALLOWLIST);
    record.offscreen = off.offenders;
    const flow = await checkHorizontalOverflow(page);
    if (!flow.ok) record.overflow = flow;
    // The rail's flex column can land at a FRACTIONAL x (its left neighbors
    // have fractional widths), which puts every glyph in it at a subpixel
    // phase — and Chromium's per-process glyph cache rounds that phase
    // differently across launches (verified: renders within one launch are
    // byte-identical; separate launches disagree in-place on rail text only,
    // the one surface at fractional x). Snap it to the pixel grid before the
    // shot so its text rasters at integer phase like every other surface.
    await page.evaluate(() => {
      const rail = document.getElementById('applicant-gadget-rail');
      if (!rail) return;
      const r = rail.getBoundingClientRect();
      const dx = Math.round(r.left) - r.left;
      const dy = Math.round(r.top) - r.top;
      if (dx || dy) rail.style.transform = `translate(${dx}px, ${dy}px)`;
    }).catch(() => {});
    await applyMasks(page);
    record.shot = await page.screenshot({ fullPage: false });
  } catch (e) {
    record.errors.push(String(e && e.message || e).split('\n')[0].slice(0, 300));
  } finally {
    await page.close().catch(() => {});
  }
  return record;
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  const playwright = requirePlaywright();
  fs.rmSync(OUT_DIR, { recursive: true, force: true });
  fs.mkdirSync(path.join(OUT_DIR, 'current'), { recursive: true });
  fs.mkdirSync(path.join(OUT_DIR, 'diff'), { recursive: true });

  let server = null;
  let base = flags.base;
  let creds = { user: process.env.ADMIN_USER || 'admin', password: process.env.ADMIN_PASSWORD || '' };
  if (!base) {
    server = await bootFrontDoor(flags.port);
    base = server.base;
    creds = { user: server.user, password: server.password };
  }

  // Raster-determinism flags: text over composited/translucent surfaces
  // otherwise flips between LCD-subpixel and grayscale antialiasing depending
  // on run-variable layer promotion — --disable-lcd-text pins one AA mode;
  // partial-raster/low-res-tiling produce frame-dependent tile seams. These are
  // CHROMIUM-ONLY Chrome switches: Firefox/WebKit reject unknown --flags at
  // launch, and they run in SMOKE mode (no pixel gate) where raster determinism
  // is not load-bearing, so their launch is a plain headless one.
  const launch = IS_CHROMIUM
    ? {
      headless: true,
      args: [
        '--no-sandbox', '--disable-gpu', '--force-color-profile=srgb', '--hide-scrollbars',
        '--disable-lcd-text', '--disable-partial-raster', '--disable-skia-runtime-opts',
        '--disable-low-res-tiling',
        // Text raster determinism: hinting + fractional glyph positions vary
        // with run-to-run layer promotion — the last few dozen px of AA jitter
        // on small rail-card text came from exactly this pair.
        '--font-render-hinting=none', '--disable-font-subpixel-positioning',
      ],
    }
    : { headless: true };
  const exe = browserExecutable(ENGINE);
  if (exe) launch.executablePath = exe;

  const results = [];
  let captured = 0;
  const failures = [];
  // Launch inside the try: a launch failure must still stop the uvicorn the
  // harness just booted, or it lingers holding the port for every later run.
  let browser = null;

  try {
    browser = await playwright[ENGINE].launch(launch);
    // WARM-UP (determinism): the very first render in a fresh browser process
    // rasterizes text measurably differently from every later one (font/glyph
    // cache warm-up — verified: shot 1 of N differs by a few hundred px, shots
    // 2..N are byte-identical). One throwaway capture absorbs the cold pass so
    // every MEASURED capture below is a warm render.
    {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const p = await ctx.newPage();
      await p.goto(base + '/login', { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      await p.waitForTimeout(500);
      await p.screenshot().catch(() => {});
      await ctx.close();
    }

    for (const theme of THEMES) {
      for (const vp of VIEWPORTS) {
        // Fresh context per theme×viewport cell; login once per context.
        let loggedIn = false;
        for (const state of STATES) {
          const id = `${theme.tag}/${vp.tag}/${state.name}`;
          if (flags.only && !flags.only.test(state.name)) continue;
          // Desktop-only states (the P0-3 gadget rail) do not exist below the
          // 768px breakpoint — skip them on the mobile cell rather than shoot an
          // absent surface (see surfaces.js `desktopOnly`).
          if (state.desktopOnly && vp.width < 768) continue;

          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
            reducedMotion: 'reduce',
            serviceWorkers: 'block',
            timezoneId: 'UTC',
            locale: 'en-US',
            deviceScaleFactor: 1,
          });
          await context.addInitScript(initScript(theme.stored, state.localStorage));
          if (!state.preAuth) {
            const resp = await context.request.post(`${base}/api/auth/login`, {
              data: { username: creds.user, password: creds.password },
              headers: { Origin: base, Referer: `${base}/login` },
            });
            if (!resp.ok()) throw new Error(`login failed (${resp.status()}) — cannot walk authenticated states`);
            loggedIn = true;
          }

          const rec = await captureState(context, state, base);
          await context.close();
          captured++;

          const entry = { id, theme: theme.tag, viewport: vp.tag, state: state.name, status: 'ok', notes: [] };
          if (rec.errors.length) {
            entry.status = 'error';
            entry.notes.push(...rec.errors);
            failures.push(`[error]      ${id}: ${rec.errors[0]}`);
            results.push(entry);
            console.log(`  ERROR   ${id}  ${rec.errors[0]}`);
            continue;
          }
          if (rec.offscreen.length) {
            entry.status = 'offscreen';
            entry.offenders = rec.offscreen;
            failures.push(`[offscreen]  ${id}: ${rec.offscreen.length} element(s), first ${rec.offscreen[0].sel}`);
          }
          if (rec.overflow) {
            entry.status = entry.status === 'ok' ? 'overflow' : entry.status;
            entry.overflow = rec.overflow;
            failures.push(`[overflow]   ${id}: scrollWidth ${rec.overflow.scrollWidth} > clientWidth ${rec.overflow.clientWidth}`);
          }

          // Re-encode for small committed baselines: RGB, max deflate, and a
          // 5-bit color posterize applied identically on bless AND compare
          // (see png.js posterize — zero-diff semantics are unchanged).
          const dec = decodePNG(rec.shot);
          const pngOut = encodePNG(dec.width, dec.height, posterize(dec.data));
          const rel = path.join(theme.tag, vp.tag, `${state.name}.png`);
          const currentPath = path.join(OUT_DIR, 'current', rel);
          fs.mkdirSync(path.dirname(currentPath), { recursive: true });
          fs.writeFileSync(currentPath, pngOut);

          // Cross-engine SMOKE (firefox|webkit): the pass/fail is the layout +
          // error contract asserted above, NOT pixels. A per-engine baseline is
          // OPTIONAL — compared when present (a human blessed one), but its
          // absence is informational, never a failure. This is why the default
          // Chromium lane is unchanged while FF/WebKit can run green on a runner
          // that has never blessed them.
          const baselinePath = path.join(BASELINE_DIR, rel);
          if (flags.bless) {
            fs.mkdirSync(path.dirname(baselinePath), { recursive: true });
            fs.writeFileSync(baselinePath, pngOut);
            entry.blessed = true;
            console.log(`  BLESS   ${id}`);
          } else if (!fs.existsSync(baselinePath)) {
            if (IS_CHROMIUM) {
              entry.status = 'missing-baseline';
              failures.push(`[missing]    ${id}: no baseline — run with --bless to create it`);
              console.log(`  MISSING ${id}`);
            } else {
              entry.status = entry.status === 'ok' ? 'smoke' : entry.status;
              console.log(`  ${entry.status === 'smoke' ? 'smoke  ' : 'LAYOUT '} ${id}  (${ENGINE}, no pixel gate)`);
            }
          } else {
            const cmp = comparePNG(fs.readFileSync(baselinePath), pngOut);
            if (!cmp.equal) {
              entry.diff = { diffCount: cmp.diffCount, total: cmp.total, note: cmp.note };
              const diffPath = path.join(OUT_DIR, 'diff', rel);
              fs.mkdirSync(path.dirname(diffPath), { recursive: true });
              if (cmp.diffImage) fs.writeFileSync(diffPath, cmp.diffImage);
              // A pixel diff gates ONLY the Chromium lane. For FF/WebKit a diff
              // against a per-engine baseline is a determinism note, not a
              // regression — the golden-path pass/fail is the layout contract.
              if (IS_CHROMIUM) {
                entry.status = 'diff';
                failures.push(`[diff]       ${id}: ${cmp.note} -> ${path.relative(process.cwd(), diffPath)}`);
                console.log(`  DIFF    ${id}  ${cmp.note}`);
              } else {
                if (entry.status === 'ok') entry.status = 'smoke-diff';
                console.log(`  diff*   ${id}  ${cmp.note} (${ENGINE}, non-gating)`);
              }
            } else if (entry.status === 'ok') {
              console.log(`  ok      ${id}`);
            } else {
              console.log(`  LAYOUT  ${id}  (${entry.status})`);
            }
          }
          results.push(entry);
        }
        if (!loggedIn && !flags.only) { /* only pre-auth states ran — fine */ }
      }
    }
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) await server.stop();
  }

  const report = {
    when: new Date().toISOString(),
    engine: ENGINE,
    mode: IS_CHROMIUM ? 'pixel-baseline' : 'cross-browser-smoke',
    matrix: { themes: THEMES.map((t) => t.tag), viewports: VIEWPORTS.map((v) => v.tag), states: STATES.map((s) => s.name) },
    captured,
    bless: flags.bless,
    failures,
    results,
  };
  fs.writeFileSync(path.join(OUT_DIR, 'report.json'), JSON.stringify(report, null, 2));

  console.log(`\n[${ENGINE}] ${captured} states captured (${THEMES.length} themes x ${VIEWPORTS.length} viewports x ${flags.only ? 'subset' : STATES.length + ' states'})`);
  if (failures.length) {
    console.log(`\nFAIL — ${failures.length} issue(s):`);
    for (const f of failures) console.log('  ' + f);
    console.log(`\nDiff images: ${path.join(OUT_DIR, 'diff')}`);
    console.log('If a change is intended, re-run with --bless to accept it as the new baseline.');
    return 1;
  }
  if (flags.bless) { console.log(`\n[${ENGINE}] Baselines blessed.`); }
  else if (IS_CHROMIUM) { console.log('\nGREEN — zero pixel diff, no layout violations.'); }
  else { console.log(`\nGREEN — [${ENGINE}] cross-browser smoke passed (no errors, no off-screen escapes, no horizontal overflow).`); }
  return 0;
}

main().then((code) => process.exit(code), (e) => { console.error(e); process.exit(2); });
