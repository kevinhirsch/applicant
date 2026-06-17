# Front-End Audit Protocol

A rigorous, reproducible protocol for auditing the white-labeled **`workspace/`
front-door** — visual/HCI quality, copy, and component architecture — using
autonomous visual telemetry. Written for this repo's realities (vanilla JS + vanilla
CSS, hexagonal engine behind a proxying front-door, remote/cloud runner). Adapt the
ports/paths if running elsewhere.

> TL;DR: stand up the stack → provision sandboxed Playwright/Chromium → walk the
> state journey at 1440 + 375 → analyze with the five lenses → catalogue defects →
> remediate at the design-token/component altitude → validate by re-capture + the
> CI gates → review via a single PR.

---

## ROLE & DIRECTIVE
Act as a Postdoctoral HCI Researcher, a Principal Frontend Systems Architect, and an
Autonomous QA Agent. Conduct a deterministic, theoretically grounded audit of the
frontend — visual topology, cognitive wayfinding, spatial equilibrium ("feng shui"),
component architecture — justified by foundational design heuristics. Beyond visuals,
**proofread all user-facing copy** (grammar, parallelism, agreement, clarity, leaked
internal jargon) and judge the **general experience**.

## READ FIRST (grounding — before any capture)
1. Read `CLAUDE.md` and `workspace/CLAUDE.md`. Honor the binding principles:
   - **Reachability = the white-labeled `workspace/` front-door chain** (spec →
     engine endpoint → `/api/applicant/*` proxy → JS → nav). The engine ships its own
     `frontend/` UI, but the **public surface is `workspace/`** — audit that.
   - **White-label, always:** zero upstream codenames and **zero `FR-`/`NFR-` jargon
     in user-facing strings** (error details, digest/portal text, tooltips). Treat any
     rendered `FR-…`/`NFR-…` as a defect.
   - **Lift-and-shift / reuse:** reuse existing design-system classes (`.modal`,
     `.admin-card`, `.cal-btn`, `.settings-*`, `.memory-*`); don't rebuild what exists.
2. **This is vanilla JS (ES modules) + vanilla CSS with a `:root` design-token
   system — NOT Tailwind, no build step.** Remediation altitude, in preference order:
   design tokens / `:root` in `workspace/static/style.css` → shared component classes
   → the applicant-specific CSS block → (only when the defect is a hardcoded
   dimension) the `style="…"` template strings inside `workspace/static/js/applicant*.js`.
   Engine-side user-facing strings live in `HTTPException(detail=…)` and message
   constants under `src/applicant/`.

## METHODOLOGICAL CONSTRAINT: AUTONOMOUS VISUAL TELEMETRY
No screenshots are provided. Provision your own telemetry, capture the DOM
programmatically, and ingest the image artifacts with your vision.

---

## PHASE 1 — STAND UP THE STACK & TOOLING
Background the slow steps up front and run them in parallel:
1. **Engine:** start Postgres (`pg_ctlcluster 16 main start`), create role/db,
   `DATABASE_URL=postgresql+psycopg://… uv run alembic upgrade head`, then
   `uv run uvicorn applicant.app.main:app --port 8000` (background).
2. **Front-door:** `pip install -r workspace/requirements.txt` into an isolated
   **venv** (not the system env — a Debian-managed `PyJWT` will break `pip`), then
   `python setup.py` (creates SQLite + admin; set `APPLICANT_ADMIN_USER/PASSWORD` for
   a deterministic login), then `uvicorn app:app --port 7000`
   (`ENGINE_URL=http://127.0.0.1:8000`) (background).
3. **Screenshot tooling, sandboxed:** create a git-ignored `./.audit-telemetry/`
   (never commit it). Inside: `npm i playwright` + `npx playwright install chromium`
   (set/keep `PLAYWRIGHT_BROWSERS_PATH`). Keeps browser deps out of the project graph.
4. Verify both ports return `200` before capturing.

### Screenshotting (explicit)
- Author Node + Playwright scripts in `.audit-telemetry/`. Each script: authenticates
  via the **API** (`POST /api/auth/login` on the context's `request`, so the cookie is
  reused by all pages) — or fills the form when auditing login itself; navigates; waits
  with a **robust heuristic** (`waitForLoadState('networkidle')` + a short fixed
  settle); captures **full-page PNGs** to `.audit-telemetry/shots/`.
- **Breakpoints:** Desktop **1440×900** and Mobile **375×812** for every state. On
  mobile the sidebar collapses behind `#hamburger-btn` — open it before clicking rail
  items.
- **Dismiss the OOBE overlay correctly:** it relocates shared DOM nodes (e.g.
  `#adm-endpoint-manager`) into itself. Do **not** `.remove()` it to "see behind" —
  that deletes the shared node and fabricates phantom "empty pane" defects. Close it
  the way the app does, or complete/relaunch setup.
- Ingest each PNG with vision. Also dump `page.innerText` of key surfaces for the
  proofreading pass.
- **In-page defect scan on every surface:** horizontal overflow (`scrollWidth >
  clientWidth`; elements whose right edge exceeds the viewport), stray whitespace in
  visible text (space-before-punctuation, double spaces, spaces in parens), and
  collected `console`/`pageerror` events (catches JS crashes that surface as UI text,
  e.g. an unguarded `.map`).

### Parallelization (explicit)
- **Within a script:** capture both breakpoints and independent surfaces concurrently
  via separate browser **contexts/pages** under `Promise.all`.
- **Across processes:** parameterize scripts by `BASE_URL`/surface-set and run several
  at once: `node passA.js & node passB.js & wait`. Don't rely on a bare `&` for
  long-lived servers — use the runner's background mechanism (a foreground shell reaps
  children on exit).
- **Two front-doors:** run a **second workspace instance on `:7001`** sharing the same
  engine, and split surface coverage across `:7000`/`:7001` to halve wall-clock time.
  Capture/read passes are safe to parallelize on shared state; serialize
  state-mutating steps.
- Background the long poles (pip install, Chromium download, Postgres/Alembic).
- **Engine test suite caveat:** it's hermetic via **in-memory storage when no DB is
  reachable** (the CI lane). A *reachable* Postgres makes `create_app()` tests hit it
  and cross-pollute. To mirror CI, run with an unreachable `DATABASE_URL` (e.g.
  `…@127.0.0.1:1/none`) so it falls back to in-memory.

---

## PHASE 2 — THEORETICAL EVALUATION FRAMEWORK
For each state, evaluate through and cite:
1. **Spatial equilibrium & wayfinding:** visual hierarchy, foveal/kinematic flow,
   dead-ends, clutter, claustrophobic clustering.
2. **Gestalt:** proximity, similarity, enclosure, figure-ground, negative space as
   semantic boundary.
3. **Cognitive load & affordance (Sweller / Gibson / Norman):** unambiguous signifiers,
   perceived affordances, path of least resistance = intended journey.
4. **Viewport agnosticism & micro-interactions:** 1440 vs 375, and a static CSS read of
   `:hover` / `:focus-visible` / `:active` coverage (a11y).
5. **Architectural execution:** Flexbox/Grid correctness, baseline/type alignment,
   positioning collisions, contrast failures.

---

## PHASE 3 — LONGITUDINAL STATE AUDIT (sequential; click EVERYTHING)
Audit each state **exhaustively** — click every visible button on every screen and
every subscreen, **including after the OOBE concludes**: every rail/tool launcher,
every settings panel and sub-section, every modal/tab, and **every theme**. Audit both
**empty** and **populated** states.

**State journey**
1. **Initial instantiation** — login / zero-data landing.
2. **Onboarding/configuration** — the OOBE wizard, step by step, every sub-option +
   validation.
3. **Core operational** — the home base / dashboard, **populated**.
4. **Component-level interactions** — modals, forms, complex interactive states.

**Reaching the data-dependent states (3–4 are otherwise locked)**
- Connect a real model (a temporary cloud API key, OpenRouter/OpenAI-compatible).
  Treat it as a secret: store only in the git-ignored sandbox; never commit /
  screenshot / log it; remind the user to revoke it. Verify provider egress first.
- Configure it (OOBE "Connect a model" or `POST /api/setup/llm`), then complete the
  full **12-step onboarding** (including résumé upload + conflict reconciliation).
- Populate the pipeline **offline** (no live job boards): seed a `JobPosting` for the
  campaign, then `GET /api/digest/{id}` → `POST /api/digest/{id}/deliver` to
  materialize the digest "Today's roles" + a pending **Review** action in the Portal.

**Per-state execution loop**
1. **Telemetry:** run the capture script; ingest Desktop + Mobile artifacts.
   *Guardrail:* if E2E navigation fails on dynamic/auth state, reset to a known state
   (fresh DB / re-auth) or request a direct URI — don't rabbit-hole script debugging.
2. **Theoretical analysis** (Phase 2 lenses), dense and specific.
3. **Defect catalogue:** UX-friction vectors, CSS/DOM regressions, copy defects
   (jargon/grammar/agreement/parallelism), console/page errors — each tied to
   `file:line`.
4. **Investigate before filing** — reproduce the root cause; never report artifacts of
   your own tooling as product bugs.
5. **Remediate at the correct altitude** (tokens → component classes → applicant CSS
   block → JS template-string dimensions; engine strings for jargon). Strict CDA: no
   spaghetti, no ad-hoc inline styles, reuse existing classes, keep the vendored diff
   minimal.
6. **Validate** by re-capturing affected surfaces at both breakpoints, and run the
   green-increment gates: engine hermetic suite (in-memory) + front-door
   `test_applicant_*` tests + `node --check` on edited JS + `ruff` + single Alembic
   head + `docker compose config` + the white-label codename denylist.

---

## REVIEW, ROLLBACK, CONTEXT (environment-adapted)
The interactive `/diff`, `/rewind`, `/compact` slash commands are **not available** in
the remote/web runner. Adapt:
- **Review:** focused commits on the working branch, push, maintain a **single PR**;
  the diff is the review surface. Summarize changes in the PR body and keep it updated.
- **Rollback:** `git revert` (the "/rewind" equivalent); re-capture to confirm.
- **Context GC:** summarize decisions and discard raw image tokens as you move between
  states.
- When a change is **architecturally significant or genuinely ambiguous** (remove vs.
  fix a control; schema migration vs. startup-seed for a data-model bug), **ask the
  user with explicit options** rather than guessing.

## INITIALIZATION VECTOR
Acknowledge comprehension. Read `CLAUDE.md`; stand up Postgres + engine + front-door
(and a second front-door on `:7001` for parallel capture); provision the sandboxed
Playwright/Chromium tooling; begin **Phase 3, State 1** by capturing the Desktop (1440)
and Mobile (375) artifacts and proceeding through the loop.
