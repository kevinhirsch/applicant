# Front-door performance budget (X-3)

Scope: the **white-labeled front-door** (`workspace/`) — the only public surface.
This is the engine-independent client budget: shell boot and surface-open
latency, plus the GPU cost of the glass/aurora look. Engine (`src/applicant/`)
latency is out of scope here.

The two latencies the X-3 DoD names:

- **login→interactive** — from navigation of the authenticated shell (`/`) until
  the 3-pane shell is *interactive*: the `#app-loader` splash has detached **and**
  the composer is enabled (the same "boot settled" signal the visual harness's
  `_waitBoot` waits on — sessions loaded, assistant session selected, glass tier
  applied).
- **surface-open** — the hash-routed / launcher-driven page open (the P0-3 "windows"
  were retired; a surface is now a hash route opened by `window.openApplicant*` +
  `hashRouter.js`). Measured from the nav click/launcher call to the surface being
  visible and settled one frame, for Today / Tracker / Results / Activity.

## How it's measured

`workspace/tests/perf/measure.js` **reuses the P0-6 visual harness's hermetic
app-boot** (`workspace/tests/visual/boot.js` — fresh SQLite, fixed admin, engine
pointed at an unreachable port) and its unlock fixture (`fixtures.js`), rather
than standing up a second app-boot path. It drives Chromium via Playwright and
takes all timings **browser-side** with `performance.now()` (relative to the
page's navigation start) and the Navigation Timing API, so Node scheduling
jitter never enters a number.

Unlike the visual harness it does **not** freeze animation or pin
`performance.now()`/`Date` — those pins exist for pixel determinism and would
destroy every timing. Each surface is opened on its own fresh interactive page
(one page per surface, mirroring the harness's per-state page model), so there is
no cross-surface DOM contamination.

Re-run:

```bash
cd workspace
# On this repo's env, point the harness Python at the root uv project (the
# vendored front-door deps live there): VISUAL_PY="uv run --project .. python"
VISUAL_PY="uv run --project .. python" node tests/perf/measure.js --iterations 6
# or reuse a already-running front-door:
node tests/perf/measure.js --base http://127.0.0.1:7000 --json
```

Results are written to `workspace/tests/perf/.out/results.json` (gitignored).

### Honest measurement caveats

- **This box, not modest hardware.** Numbers below were taken on the CI-class
  runner's Chromium at 1440×900, headless. A real user's modest laptop / older
  phone will be slower — treat the absolute numbers as a *fast-path floor* and the
  budgets as regression ceilings on **this** class of machine, not a promise about
  a Chromebook.
- **GPU-less.** Headless here runs with `--disable-gpu` and no GPU on the runner,
  so the measured cost is **layout + script + paint-setup**, not the
  compositor/GPU cost of the glass blur + aurora. The blur/aurora budget is
  therefore **analytical** (below), reasoned from the CSS, not measured — a
  GPU-less headless render cannot exercise the exact cost we care about there.
- **Warm vs cold.** Iteration 1 is the cold pass (browser process + glyph cache
  cold); iterations 2..N are warm ("returning user"). Both are reported.

## Measured baselines (CI-class runner, 1440×900, 6 iterations)

**login→interactive**

| metric | cold (iter 1) | warm median | warm max |
|---|---|---|---|
| login→interactive | 3496 ms | **2699 ms** | 2885 ms |
| DOMContentLoaded | — | 1163 ms | 1204 ms |
| domInteractive | — | 241 ms | 282 ms |
| First Contentful Paint | — | 212 ms | 244 ms |

FCP (~0.2 s) and domInteractive (~0.24 s) show the shell paints and is scriptable
fast; the ~2.7 s warm login→interactive is dominated by the post-DOMContentLoaded
critical path (`sessionModule.loadSessions()` → loader teardown) plus the
deliberate "assistant session selected + composer enabled" settle the interactive
signal waits on.

**surface-open** (click → visible + one settled frame)

| surface | warm median | warm max |
|---|---|---|
| Today (Portal home base) | 671 ms | 986 ms |
| Tracker | 630 ms | 769 ms |
| Results | 655 ms | 897 ms |
| Activity | 738 ms | 893 ms |

Each surface open is a DOM build + a handful of independent async proxy loads
(the Portal, e.g., fires digest + momentum + streak + health + pending in
parallel); the ~0.6–0.7 s is those settling against the (offline, fast-erroring)
engine in this hermetic run.

## Budgets (set thresholds)

Regression ceilings on the CI-class runner. A budget breach is a signal to
investigate, not an automatic fail — the measurement rig is a rig, not a per-PR
gate (it needs a browser + a booted front-door, like the visual/cross-browser
lanes). Numbers are chosen with headroom over the measured warm baseline so
normal run-to-run variance doesn't trip them.

| budget | threshold (this box) | measured warm | headroom |
|---|---|---|---|
| login→interactive, warm median | ≤ 3500 ms | 2699 ms | ~30% |
| login→interactive, cold | ≤ 4500 ms | 3496 ms | ~29% |
| First Contentful Paint | ≤ 600 ms | 212 ms | large |
| DOMContentLoaded | ≤ 1600 ms | 1163 ms | ~38% |
| surface-open, warm median (any) | ≤ 1000 ms | ≤ 738 ms | ~35% |
| surface-open, warm max (any) | ≤ 1500 ms | ≤ 986 ms | ~52% |

Rough field-scaling rule of thumb for **modest hardware**: assume ~2–3× the
CI-box numbers on an older laptop / mid-tier phone (slower CPU parse/execute +
a real, weaker GPU compositing the glass). That puts login→interactive in the
~5–8 s range and a surface open in the ~1.5–2 s range on a slow device — the
motivation for the cheap wins below and the reduced-motion / reduced-transparency
/ `@supports-not` escape hatches.

## Blur / aurora GPU cost — analytical budget

A headless GPU-less runner can't measure compositor cost, so this is reasoned
from the CSS (`workspace/static/style.css`, `workspace/static/css/meshGradient.css`,
`kit-themes.css`). The glass look is GPU-heavy in two ways:

1. **`backdrop-filter` blur passes.** Glass chrome frosts with `blur(22–24px)`
   (centralized in `--ow-glass-backdrop`); the modal scrim adds a `blur(2px)`
   over the shell behind an open surface. Every full-viewport `backdrop-filter`
   is a per-frame GPU sample of everything under it.
2. **The aurora mesh wallpaper** (`#__wp` / `.login-bg-gradient`): four
   `radial-gradient` blobs under a `blur(54px)` plus a `blur(30px)` diagonal ray.

**Budget / invariants (guarded — see Regression guards):**

- **Mesh blur is rasterized once, never per frame.** The mesh's heavy blur +
  gradients are *static*; only `transform`/`opacity` animate (`login-mesh-drift`,
  `login-ray-sweep`), which the compositor moves as an already-blurred bitmap
  with no repaint. Animating a repaint-forcing property here
  (`background-position`, `filter`, `width/height/top/left`) is a budget breach —
  it forces a full 54px gaussian re-blur every frame. (This was already fixed in
  a prior audit; X-3 re-guards it.)
- **Peripheral motion is opt-out.** `@media (prefers-reduced-motion: reduce)`
  freezes the mesh animation (belt-and-braces; the `.is-animated` class is also
  never added under reduced motion), and the 7 canvas wallpapers pause while the
  tab is hidden.
- **Glass is opt-out too.** `@media (prefers-reduced-transparency: reduce)` and
  `@supports not (backdrop-filter)` both solidify every glass surface to an opaque
  `--panel` (X-2) — the escape hatch for a machine that can't afford the blur.
- **Concurrent full-viewport blur layers stay ≤ 2** (the scrim + one panel). The
  design already de-stacks glass-on-glass in many places (modal headers, inner
  cards, per-chat-bubble blur removed, button blur removed inside glass); adding a
  new full-viewport `backdrop-filter` that stacks over an existing one is a budget
  breach — reuse the parent's frost instead.

## Cheap wins taken (X-3)

Front-door only, each safe + baseline-neutral (verified: the committed P0-6
Chromium glass/dark desktop + 390×844 mobile baselines are unchanged by the
visual harness after these edits).

1. **Dropped a standing `will-change` on every glass button**
   (`static/style.css`, the frosted glass-button morph rule). The selector matches
   *every* button inside every glass window / card / gadget + dock chip, so a
   permanent `will-change: transform` promoted each one to its own compositor
   layer **at rest** — GPU memory per button, all the time — purely to hint a
   ~140 ms press micro-morph that only fires on `:active`. The morph still animates
   via the existing `transition`; the compositor promotes the pressed button on
   demand and drops the layer after. `will-change` is a compositing hint only, so
   **zero rendered pixels change** — the glass baselines are untouched. The mesh
   wallpaper keeps its `will-change` (it animates continuously — correct use).
2. **Removed a duplicate boot-time memory fetch** (`static/app.js`). Boot fired
   `memoryModule.loadMemories()` and then, redundantly, a second
   `setTimeout(loadMemories, 1000)` that re-fetched `/api/memory` and re-rendered
   the same list on every page load. The memory pane is static in `index.html`, so
   the eager call already populates it; the delayed duplicate was a wasted network
   round-trip + re-render each boot. Behavior-neutral (the list still loads).

**Cheap wins already banked (pre-X-3, confirmed and now guarded):** lazy-loaded
rare surfaces (`lazyLaunch.js` — debug/gallery/compare import on first use, off the
~47-eager-module boot path); the deferred URL-route opener; the compositor-only
mesh drift with a static-rasterized blur; the shared visibility-paused rAF
scheduler + per-frame CSS-var cache for the 7 canvas wallpapers; and the backend's
fire-and-forget startup (MCP connect, tool-index warm, endpoint keepalive all
deferred off the request-accepting path in `workspace/app.py`).

## Candidates deferred (NOT taken — would breach a constraint)

- **De-stack the modal scrim `blur(2px)`.** Dropping the scrim's own blur (leaving
  only the panel's `blur(22–24px)`) would remove one full-viewport backdrop pass
  on every applicant surface open — a real GPU win. **Not taken:** the scrim blur
  is part of the committed P0-6 glass baseline (it blurs the shell visible behind
  an open surface), so removing it changes pinned pixels. Revisit only with a
  deliberate re-bless.
- **Defer the synchronous `MemoryVectorStore.rebuild()` at
  `workspace/src/app_initializer.py`** off the main startup path. Only bites when
  the vector store is cold/large (empty and instant in the hermetic harness), and
  reordering startup risks the front-door boot/ownership tests — out of scope for a
  surgical, baseline-neutral X-3 pass. Recorded for a focused follow-up.

## Regression guards

- **`workspace/tests/js/perfBudget.test.js`** (in `npm test`, no browser,
  deterministic): asserts the aurora mesh animation stays gated behind
  `prefers-reduced-motion`, the mesh drift/ray keyframes animate only
  compositor-cheap `transform`/`opacity` (never a repaint-forcing property), and
  the frosted glass-button morph rule carries **no** standing `will-change` (guards
  win #1 from re-introduction).
- **`workspace/tests/js/glassBackdropFallback.test.js`** (X-2, in `npm test`):
  the `@supports not (backdrop-filter)` solid-panel escape hatch exists and covers
  the golden-path glass surfaces.
- **`workspace/tests/test_applicant_backlog_perfanim.py`**: the mesh's
  transform-only drift + static blur, and the visibility-paused / cached canvas
  rAF loops.
- **The Chromium visual harness** (`workspace/tests/visual/run.js`): proves the
  cheap wins are pixel-neutral against the committed P0-6 baselines.
