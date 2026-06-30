# Front-Door Playtest Report — Automated UI Crawl/Audit (§6a monkey/crawl)

**Date:** 2026-06-30
**Scope:** `docs/playtest-protocol.md` §6a automated Playwright UI monkey/crawl of the
white-labeled `workspace/` front-door, run against a **hermetic in-memory engine**
(no Docker / no Postgres available in this environment).
**Branch:** `claude/playtest-audit`
**Artifacts:** crawl script `scripts/playtest_crawl.py`; screenshots `playtest-screens/`
(+ machine-readable `playtest-screens/crawl-results.json`).

> Environment reality: the full Compose stack can't run here (no Docker daemon, no
> Postgres). The engine was booted in its hermetic in-memory lane and the front-door
> against SQLite. This is sufficient for a real UI / reachability / claims audit;
> anything that genuinely needs a connected model or live job data is flagged
> **needs-live-data**, not counted as a UI defect.

---

## 1. Boot status

| Component | Command (exact) | Status |
|---|---|---|
| **Engine** (`:8000`, hermetic) | `DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' uv run uvicorn applicant.app.main:app --host 127.0.0.1 --port 8000` | **UP** — `GET /healthz` → `{"status":"ok","version":"0.1.0", database:"in-memory", postgres:"NOT REACHABLE (using in-memory storage)"}` (expected fallback). |
| **Front-door** (`:7000`) | `python setup.py` (SQLite + admin), then `DATABASE_URL="sqlite:///.../data/app.db" ENGINE_URL=http://127.0.0.1:8000 uv run uvicorn app:app --host 127.0.0.1 --port 7000` | **UP** — `GET /api/health` → `{"status":"healthy"}`, `/login` → 200. **Did NOT boot until two source defects were fixed (see Top Issues #1, #2).** |
| **Crawler** | `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python scripts/playtest_crawl.py` | Headless Chromium at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`. |

**Deps:** `uv pip install -r workspace/requirements.txt` (OK) + `playwright` (already
present in the root `uv` env). Workspace deps live in the **root `uv` env**, so
`setup.py` / `uvicorn` must be run via `uv run --project <repo>` (a bare `python` has no
deps — `setup.py` then silently skips admin creation; first symptom seen and worked
around).

**Login:** `POST /api/auth/login` is CSRF-guarded (same-origin Origin/Referer check in
`workspace/core/middleware.py`), so the crawler sends `Origin: http://127.0.0.1:7000`.

---

## 2. Headline result

The front-door **could not boot or render at all** in its as-shipped state — three
source defects had to be fixed before any surface was reachable:

1. A **SyntaxError** in `workspace/services/search/content.py` (import lines corrupted)
   → the whole app failed to import.
2. **Two broken imports** in the same file (`.analytics`/`.cache` instead of
   `src.search.*`) → `ModuleNotFoundError` after the syntax fix.
3. A **`focusLibrary is not defined`** ReferenceError on every page (dangling export).
4. **`/api/applicant/features` returned 401 for every browser session** — and the app
   shell redirects to `/login` on any 401, so that 401 **aborted the entire boot**
   (loader stuck forever, no nav, no modules). This is the most severe finding: it
   makes the front-door a **dead white screen for the real, logged-in operator**.

After the fixes, the crawl went from **24/24 surfaces failing → 1/24** (the single
remainder is a known harness limitation on mobile, not a product defect). Every
front-door surface then rendered, matched its claimed purpose, and responded to clicks
with **zero** console errors, page errors, or 5xx.

---

## 3. Per-surface table (post-fix, desktop 1440×900 unless noted)

Verdict legend: OK · broken-render · dead-control · console-error · claim-mismatch ·
needs-live-data.

| Surface | Renders? | Matches claim? | Controls respond? | Console/page errors? | Verdict |
|---|---|---|---|---|---|
| **home** (workspace shell) | Yes | Yes — white-labeled "Applicant" shell, nav rail | Yes (16 controls clicked) | None | **OK** |
| **Portal** (pending-actions home base) | Yes | Yes — "Pending" feed, honest empty state *"Not connected yet — Connect a model in Settings…"* | Yes (Refresh) | None | **OK / needs-live-data** (no pending items until a model is connected) |
| **Chat** (Job Assistant) | Yes | Yes — *"The Job Assistant isn't connected yet…"* honest empty state | Yes | None | **OK / needs-live-data** |
| **Documents / Library** (`/library`) | Yes | Yes — résumé/cover library shell | Yes | None | **OK / needs-live-data** |
| **Profile / Mind** (what the assistant remembers) | Yes | Yes — memory/playbooks panel | Yes | None | **OK / needs-live-data** |
| **Email / Digest** (`/email`) | Yes | Yes | Yes | None | **OK / needs-live-data** |
| **Activity** (now/next/recent) | Yes | Yes | Yes (16) | None | **OK / needs-live-data** |
| **Live remote / takeover** | Yes | Yes — session view scaffold | Yes | None | **OK / needs-live-data** |
| **Vault** (saved sign-ins) | Yes | Yes — list + empty state | Yes | None | **OK / needs-live-data** |
| **Compare** | Yes | Yes — side-by-side scaffold (lights up once a model is connected) | Yes (16) | None | **OK / needs-live-data** |
| **Gallery** | Yes | Yes | Yes (16) | None | **OK** |
| **Activity/Debug** | Yes | Yes — observability tabs + run controls + Update | Yes (16) | None | **OK / needs-live-data** |
| **OOBE wizard** | Yes | Yes — *Welcome → Connect a model → Your profile*; reuses the Local/Remote endpoint manager (lift-and-shift confirmed) | Yes | None | **OK** |
| **Settings** (`#user-bar-settings`) | Yes | Yes — full tab set: Add Models, AI Defaults, Campaign, Search, Fonts, Automation, Update, Integrations, Email, Reminders, Notifications, Appearance, Shortcuts, Account + Admin (Agent Tools, Users, System) | Yes (tabs switch) | None | **OK** (one minor observation — see §5) |
| **Routed:** `/memory` `/calendar` `/notes` `/tasks` `/gallery` `/email` `/library` | Yes (all HTTP 200) | Yes (vendored workspace pages) | n/a (passive capture) | None | **OK** |
| **Mobile (375×812):** portal, chat, vault, onboarding | Yes | Yes (full-screen sheets) | Yes | None | **OK** |
| **Mobile: settings** | n/a | n/a | — | None | **harness-limitation** — `#user-bar-settings` is hidden behind `#hamburger-btn` on mobile; the crawler doesn't open the drawer first (documented in protocol §3). Not a product defect (settings opens fine on desktop). |

**Crawl tally (final run):** 24 surface records, **1 flagged** (mobile-settings harness
gap). 0 page errors, 0 console errors, 0 5xx across every rendered surface. The only
4xx seen were **409 gates** on engine-backed endpoints (`/email/campaigns`,
`/vault/account`, `/setup/campaigns`) — correct "needs-setup" gating that the UI renders
as empty states, not defects.

---

## 4. Top issues found (ranked)

### #1 — [LAUNCH-BLOCKER, FIXED] `/api/applicant/features` 401 kills the entire app boot
- **Surface:** every surface (the whole front-door).
- **Repro:** log in as admin; `GET /api/applicant/features` with the session cookie →
  **401 `{"detail":"Not authenticated"}"`** (while `GET /api/sessions` with the same
  cookie → 200). In the browser, the app shell's `fetch` wrapper (`app.js:58`) redirects
  to `/login` on any non-auth 401, so this 401 **aborts boot**: the `#app-loader`
  overlay (z-index 99999) never clears, no `window.applicant*Module` ever attaches, and
  the operator sees a permanent "Taking longer than expected" splash / dead screen.
- **Root cause:** `workspace/app.py` listed `"/api/applicant/features"` in
  `AUTH_EXEMPT_EXACT`. The auth middleware `return`s early for exempt paths **without
  setting `request.state.current_user`** — but the route handler
  (`workspace/routes/applicant_routes.py`) calls `require_user(request)`, which then sees
  no user and (auth configured) raises 401. The path was simultaneously "skip auth" and
  "require auth" → unreachable for every real caller.
- **Fix:** removed `/api/applicant/features` from `AUTH_EXEMPT_EXACT` so it authenticates
  normally like its sibling owner-scoped proxy routes (its own docstring says it is
  "Auth-protected"). Verified: `GET /api/applicant/features` → **200** with full
  `{engine_available:true, sections:{…}}`. Requires an engine restart (Python change).
- **Screenshot:** before — boot stuck (no clean shot, app never rendered); after —
  `playtest-screens/home-desktop.png`, `portal-desktop.png` (app fully renders).

### #2 — [LAUNCH-BLOCKER, FIXED] `workspace/services/search/content.py` won't import (front-door won't boot)
- **Surface:** the whole front-door (process won't start).
- **Repro:** boot the front-door → `SyntaxError: invalid syntax` at `content.py:11`, then
  (after that) `ModuleNotFoundError: No module named 'services.search.analytics'`.
- **Root cause:** two layered defects in one file:
  - `from typing import` / `from core.safe_path import safe_join List` — the
    `from typing import List` line was mangled when the path-traversal `safe_join` import
    was inserted (commit #496). The module uses `List[...]` ~10×.
  - `from .analytics import …` / `from .cache import …` — relative imports to modules
    that **don't exist** in `services/search/` (no `analytics.py`/`cache.py` there). The
    canonical copies live in `src/search/`, and the sibling files `core.py`/`providers.py`
    correctly import `from src.search.analytics import …`. This file (a duplicate placed
    in the wrong package) used relative imports from the start.
- **Fix:** restored `from typing import List` + `from core.safe_path import safe_join`,
  and pointed the two imports at `src.search.analytics` / `src.search.cache` (matching
  the sibling modules). `python -m compileall` clean; front-door boots.
- **Note:** `node --check` and `py_compile` were the CI JS/py gates — but the *import
  graph* (`services/__init__.py → search → content`) is exercised only at **boot**, which
  CI never does (no `compose up`), so this shipped. CI's workspace `compileall` covers
  `app.py routes src` but **not `services/`**, which is why the syntax error slipped the
  gate too.

### #3 — [LAUNCH-BLOCKER, FIXED] `focusLibrary is not defined` ReferenceError on every page
- **Surface:** every page (fires 4× on load).
- **Repro:** open any front-door page → `pageerror: focusLibrary is not defined`.
- **Root cause:** `workspace/static/js/documentLibrary.js:3972` lists `focusLibrary` in
  the `documentLibraryModule` export object, but `focusLibrary` is **never defined or
  imported** anywhere (appears exactly once, in that object literal). Evaluating the
  object literal throws a `ReferenceError`. `node --check` (the only CI gate for JS)
  validates syntax but **not** undefined references, so it shipped.
- **Fix:** removed the dangling `focusLibrary,` from the export (nothing consumes it).
  Verified the `pageerror` no longer fires. (This error compounded #1: it broke module
  init even before the 401 redirect.)

### #4 — [POST-LAUNCH / observation] Settings "Add Models" panel body appeared empty in one capture
- **Surface:** Settings → Add Models tab.
- **Repro:** open Settings; the left tab list renders fully, but in the screenshot the
  right-hand panel body for the selected "Add Models" tab was blank
  (`playtest-screens/settings-desktop.png`).
- **Assessment:** likely a **timing/capture artifact** (panel paints after the shot) or
  the shared endpoint-manager node being relocated between the OOBE overlay and Settings
  (the protocol §2 warns about this DOM-relocation). All Settings tabs clicked without
  error. **Needs a focused re-check with the model-endpoint manager**; not counted as a
  hard defect. (Other tabs were not individually screenshotted.)

---

## 5. Honest summary — how much of the FE genuinely "does what it says"

**After the three boot-blocking fixes: essentially all of it, structurally.** Every one
of the ~14 first-class Applicant surfaces plus the 7 vendored routed pages renders,
carries white-labeled "Applicant" copy (no codename/`FR-` leaks observed in the crawled
text), matches its nav label and `overview.md` description, and responds to clicks with
**zero** console/page/5xx errors. The Portal and Chat empty states are exemplary —
honest *"not connected yet, connect a model in Settings"* messaging rather than dead
controls or fabricated data. The OOBE wizard correctly reuses the existing Local/Remote
endpoint manager (lift-and-shift, per principle #1) and takes precedence while setup is
incomplete (by design).

**But the as-shipped front-door was 100% broken on this branch's tip** — it would not
even boot, and *even after* booting it would have been a dead screen for the logged-in
operator because of the `/api/applicant/features` 401→`/login` redirect loop. These are
**not** environmental artifacts of the hermetic lane: #1 is an HTTP-level auth
contradiction reproducible with `curl`, #2/#3 are static source defects. They are exactly
the class of bug the protocol exists to catch — "reachability is the definition of done,"
and the CI gates (which never `compose up` and never run an undefined-ref JS check) let
all three through.

**What is genuinely "only-claims / needs-live-data"** (not defects, correctly degraded):
the digest "Today's roles", real pending actions, material review/redline, chat answers,
activity now/next/recent, vault entries, compare data — all require a connected model
and/or live discovery, which this environment can't provide. Each degrades to an honest
empty state or a 409 gate, exactly as specified.

**Net:** the front-door's breadth and claim-fidelity are strong, but it was shipped in a
**non-booting** state on this tip. The three fixes restore it to a clean, fully-reachable
green crawl (1/24, that one a harness-only mobile gap).

---

## 6. Fixes applied on this branch

| File | Change |
|---|---|
| `workspace/app.py` | Removed `/api/applicant/features` from `AUTH_EXEMPT_EXACT` (it calls `require_user`; exempting it 401'd every session and aborted boot). |
| `workspace/services/search/content.py` | Fixed corrupted `from typing import List` / `safe_join` import; repointed `.analytics`/`.cache` → `src.search.analytics`/`src.search.cache` (matches sibling modules). |
| `workspace/static/js/documentLibrary.js` | Removed dangling `focusLibrary` from the export object (undefined symbol → `ReferenceError` on every page). |
| `scripts/playtest_crawl.py` | New: the §6a automated crawl harness (added, not a product change). |

**Green-increment gates run (all pass):**
- `uv run ruff check .` → All checks passed.
- `DATABASE_URL=…@127.0.0.1:1/none uv run pytest -q workspace/tests/test_applicant_*.py` → **425 passed**.
- `node --check workspace/static/js/documentLibrary.js` → OK.
- `python -m compileall workspace/app.py workspace/services/search/content.py` → OK.
- Front-door boots; `/api/applicant/features` → 200; full crawl → 1/24 (harness-only).

---

## 7. Harness notes (so the next run trusts the green)

- **CSP has no `unsafe-eval`** (a security positive). Playwright's `wait_for_function`
  uses `eval()` and is **blocked** by the page CSP — it throws a misleading
  `unsafe-eval` `pageerror` and always times out. The harness was switched to
  `wait_for_selector(state="detached")` for the loader and to direct
  `query_selector`/`evaluate(function)` calls. A run that uses `wait_for_function` will
  fabricate phantom "app-loader never cleared" and CSP `pageerror` findings — those are
  harness artifacts, **not** product bugs.
- **The OOBE wizard auto-opens** (setup incomplete) as an `aria-modal .modal.ow-window`
  and intercepts clicks on every other surface (by design — the wizard takes precedence).
  To audit a surface behind it, detach the overlay node the app's way (mirrors
  `_dismiss()`), which the harness now does for non-onboarding surfaces.
- **Mobile settings** needs `#hamburger-btn` opened before `#user-bar-settings` is
  visible; the harness doesn't yet, hence the single residual flag.
