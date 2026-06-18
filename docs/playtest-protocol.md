# Front-Door Playtest & Audit Protocol (repeatable, agent-runnable)

This is the **operational playbook** for the recurring audit + playtest of the
white-labeled `workspace/` front-door. It supersedes nothing in
`frontend-audit-protocol.md` (the visual/HCI lenses) — it **folds that in** and
adds the parts that only emerge from actually *using* the product: standing up a
real stack with a live model, **role-playing as the user in the UI**, judging LLM
output quality, and the **note → debug → fix → re-run** loop. A fresh agent should
be able to execute this end-to-end with no other context.

> **Hard requirement: an LLM API key must be supplied at the very start.** The
> data-dependent states (digest, review, redline revision, chat, material
> generation) are unreachable without a configured model. Get the key before Phase 1.
> Treat it as a secret: store only in the git-ignored `.audit-telemetry/.orkey`,
> never commit/screenshot/log it, and remind the user to revoke it when done.

---

## 0. ROLE & MINDSET

Act simultaneously as: a **Postdoctoral HCI Researcher** (visual topology, Gestalt,
cognitive load, wayfinding), a **Principal Frontend Architect** (CSS tokens,
responsive correctness, component reuse), an **Autonomous QA Agent** (click every
control, sweep every endpoint), and — the addition this protocol exists for — a
**role-playing end user** who is actually trying to get a job with this tool and
will notice when something is dumb, broken, or lies to them.

Two non-negotiable disciplines:
- **Investigate before filing.** Reproduce the root cause. Never report an artifact
  of your own tooling as a product bug (see §8 "Known false positives").
- **Reachability = done.** A thing works only when it's operable in the
  white-labeled `workspace/` front-door (spec → engine endpoint → `/api/applicant/*`
  proxy → JS → nav), not because a test passes.

---

## 1. STAND UP THE STACK (concrete; remote/cloud container)

Background the slow steps first; they parallelize.

1. **Postgres + engine** (the engine needs Postgres; it does NOT fall back to SQLite):
   ```
   pg_ctlcluster 16 main start
   # role/db once: createuser applicant; createdb -O applicant applicant_live3
   DATABASE_URL=postgresql+psycopg://applicant:applicant@127.0.0.1:5432/applicant_live3 \
     uv run alembic upgrade head
   DATABASE_URL=…applicant_live3 ORCHESTRATOR_BACKEND=shim BROWSER_CHANNEL=chrome \
     PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers APPLICANT_INTERNAL_TOKEN=audit-internal-token \
     uv run uvicorn applicant.app.main:app --host 127.0.0.1 --port 8000   # background
   ```
   Re-use a DB that already holds a completed-onboarding campaign (e.g.
   `applicant_live3`) so you skip re-onboarding every run.
2. **Front-door ×2** (run a second on :7001 sharing the same engine to halve
   capture wall-clock). The vendored app's heavier deps aren't in the root env —
   install `workspace/requirements.txt` into an isolated **venv** (a Debian-managed
   PyJWT breaks system `pip`):
   ```
   python -m venv .audit-telemetry/venv && .audit-telemetry/venv/bin/pip install -r workspace/requirements.txt
   cd workspace && ENGINE_URL=http://127.0.0.1:8000 APPLICANT_INTERNAL_TOKEN=audit-internal-token \
     .audit-telemetry/venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 7000   # bg
   #  …repeat for :7001
   ```
   First-run admin: `python setup.py` creates SQLite + an admin. If you don't know
   the password, reset it directly: `AuthManager()._config["users"]["admin"]["password_hash"]=_hash_password("…"); _save()` then **restart the workspace** (it caches auth in memory).
3. **Sandboxed Playwright/Chromium** in git-ignored `.audit-telemetry/`:
   `npm i playwright && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright install chromium`.
4. **Connect the model** (gates everything): `POST /api/applicant/setup/llm` (or the
   OOBE) with `{provider, base_url, model, api_key}`. For a tier ladder use
   `PUT /api/applicant/setup/llm/tiers`. Verify provider egress first
   (`GET https://<provider>/.../models`). After changing the key/ladder, **restart
   the engine** — it builds the ladder at boot.
5. **Verify** `:8000/` and `:7000/` and `:7001/` return 200/302 before capturing;
   `GET /api/applicant/setup/status` should show `automated_work_allowed: true`.

**Gotchas that have bitten us:**
- Background servers die when a foreground shell returns — use the runner's
  background mechanism, not a bare `&`.
- Postgres can crash; if endpoints 500 or psql says "connection refused", restart
  the cluster AND the engine (the engine's pool dies with it).
- Run the **engine test suite** with an UNREACHABLE `DATABASE_URL`
  (`…@127.0.0.1:1/none`) so it uses in-memory storage and mirrors CI — a reachable
  Postgres cross-pollutes `create_app()` tests.

---

## 2. TELEMETRY & SCREENSHOTTING (autonomous; ingest with vision)

Author Node+Playwright scripts in `.audit-telemetry/`. Each script:
- **Auth via the API** so the cookie is reused by all pages:
  `await ctx.request.post(BASE+'/api/auth/login', {data:{username,password}})`.
  (Drive the *form* only when auditing login itself: `#username`,`#password`,`#submitBtn`.)
- Navigate, wait `waitForLoadState('networkidle')` + a short fixed settle, capture
  **full-page PNGs** to `.audit-telemetry/shots/`, and dump `page.innerText` to
  `.audit-telemetry/text/` for the copy/proofreading pass.
- **Breakpoints: Desktop 1440×900 AND Mobile 375×812 for every state.**
- **In-page defect scan on every surface:** horizontal overflow (`scrollWidth >
  clientWidth`; elements whose right edge exceeds the viewport), stray whitespace
  (space-before-punctuation, double spaces, spaces in parens), leaked `FR-`/`NFR-`
  jargon + codenames in visible text, and collected `console`/`pageerror` events.
- **Parallelize:** both breakpoints + independent surfaces via separate
  contexts/pages under `Promise.all`; across processes
  `node a.js & node b.js & wait`; split surfaces across :7000/:7001. Serialize
  state-mutating steps; parallelize read/capture freely.

**Closing the auto-opened windows.** The Portal (home base) AND the OOBE overlay
auto-open and are **scrim-less tool windows** (see §8) — they stack over whatever
you open next. Before capturing another surface, close them the app's way:
`document.getElementById('applicant-portal-close')?.click()` and the onboarding
`#ao-finish`/close. Do NOT `.remove()` the OOBE overlay — it relocates shared DOM
nodes (e.g. `#adm-endpoint-manager`) and you'll fabricate phantom "empty pane" bugs.

---

## 3. SURFACE & SELECTOR MAP (so a new agent doesn't re-derive it)

Open surfaces via the JS seams (most reliable) or the visible controls:

| Surface | Open it | Key selectors |
|---|---|---|
| Login | `/login` | `#username` `#password` `#submitBtn` `#remember` |
| **Settings** | click **`#user-bar-settings`** (the bottom-left gear). `#rail-settings` is hidden when the sidebar is expanded. | tabs `[data-settings-tab="X"]` (ai, sandbox, tools, services, integrations, notifications, reminders, email, fonts, search, appearance, account, shortcuts, users, system); panels `[data-settings-panel="X"]` |
| Portal (home base) | `window.openApplicantPortal()` (auto-opens on landing) | `#applicant-portal-modal` `#applicant-portal-refresh` `#applicant-portal-close`; cards `.applicant-portal-row`; `.applicant-portal-review` `.applicant-portal-resolve` |
| Documents / review | Portal "Review" → `window.documentModule.openLibrary({tab:'applicant',appId})` | `#doclib-applicant-appid` `#doclib-applicant-lookup-btn` `#doclib-applicant-results`; redline turn: `.doclib-applicant-kind` `.doclib-applicant-instruction` `.doclib-applicant-send` (POST `/turn`); Approve/Decline buttons |
| Job Assistant chat | `window.applicantChatModule.openApplicantChat()` | input `#applicant-input`; **send via `#applicant-send` or Ctrl/Cmd+Enter (plain Enter does NOT send)**; thread `#applicant-thread .msg-ai .body` |
| Vault (saved sign-ins) | `window.openApplicantVault()` | `#applicant-vault-list` `#applicant-vault-empty` `#applicant-vault-save` |
| Remote / live-takeover | `window.openApplicantRemoteSession(appId, url)` | `#applicant-remote-takeover` `#applicant-remote-frame`; handoffs: resume-account / resume-detection / submit-self / authorize-engine-finish |
| Activity / Debug | `window.applicantDebugModule.openApplicantDebug()` | tabs Activity/Logs/Variants/Run controls/Sources/Tools/Update |
| Theme | `#rail-theme`.click() (JS) or remove `.hidden` from `#theme-modal` | Themes/Customize tabs, swatch grid |
| OOBE wizard | `window.launchApplicantSetup()` | steps welcome→llm→onboarding; intake sections incl. `#ao-resume-file`, conversion `#ao-preview` |

Mobile: the sidebar collapses behind `#hamburger-btn` — open it before clicking
rail items. Tool windows become full-screen sheets; tab bars become horizontal
scrollers (so off-screen tabs read as "overflow" — a false positive, §8).

---

## 4. THE FIVE HCI LENSES (per state, dense & cited)

1. **Spatial equilibrium & wayfinding** — hierarchy, foveal/kinematic flow,
   dead-ends, clutter.
2. **Gestalt** — proximity, similarity, enclosure, figure-ground, negative space.
3. **Cognitive load & affordance** (Sweller/Gibson/Norman) — unambiguous signifiers;
   path of least resistance = intended journey.
4. **Viewport agnosticism & micro-interactions** — 1440 vs 375; static CSS read of
   `:hover`/`:focus-visible`/`:active` coverage.
5. **Architectural execution** — Flexbox/Grid correctness, baseline/type alignment,
   positioning collisions, contrast.

---

## 5. ROLE-PLAY THE USER (the functional playtest)

Drive the actual UI as a person with a goal, and **judge outcomes, not just HTTP
codes**. Walk the longitudinal journey:

1. **Initial** — login / zero-data landing.
2. **Onboarding** — the full OOBE: connect model → 12 intake sections → résumé
   upload + conflict reconciliation → conversion preview accept/reject → complete.
   (Backend can be walked via `POST /api/applicant/setup/onboarding/{cid}/section`
   etc.; the wizard reaches the résumé/conversion step at intake index for
   `base_resume`.)
3. **Core operational (populated)** — Portal home base with real pending actions;
   digest "Today's roles"; Refresh; digest decisions; **Research** on a role.
4. **Component interactions** — the daily loop: Review → redline → **Request change
   (a real LLM revision)** → Approve; chat; vault; remote; settings; themes.

**For every interactive control, verify intended functionality.** A click that
returns 200 but does nothing (or echoes a stub) is a bug — that's exactly how we
found the redline-revision stub and the chat false-"missing-profile" bug.

### 5a. Judge LLM output quality (flash-vs-pro lens)
At each LLM-driven step, capture the actual text and ask: *is the model good enough
for this task, or should it escalate?* Heavy writing (résumé/cover-letter/essay
generation + redline revision) runs at the escalation tier (L2/pro); chat, criteria,
factual answers run at L1 (flash). **Note any task where the entry model is "too
stupid"** (vague, wrong, fabricated, or refuses) and flag it for escalation —
this is a first-class finding, recorded alongside CSS/copy defects.

---

## 6. THE CONTRACT SWEEP (fastest bug-finder)

Before/after the UI walk, sweep every `/api/applicant/*` endpoint through the
front-door proxy with the session cookie. **Any 5xx is a bug.** A 409/422 is usually
a correct gate/validation (e.g. criteria edits are confirmation-gated → 409, and the
UI re-sends with `confirm:true`) — confirm the UI handles it before filing.
- GET sweep: hit all read endpoints (status, campaigns, criteria, attributes,
  digest, library, documents, portal, remote, vault, ops/runs, discovery, etc.).
- Mutation sweep: POST/PUT with valid bodies (aggressiveness, banned-phrases,
  criteria, attributes, learning/preview, chat/message, research/run). Use
  non-destructive payloads and restore state (delete test attrs, reset values).
- **Offline degradation:** stop the engine and confirm the front-door returns a
  graceful `{engine_available:false, …}` (200), not a 500 / white screen.

Enumerate routes from `workspace/routes/applicant_*_routes.py` (prefix + paths).

---

## 7. NOTE → DEBUG → FIX → RE-RUN (the loop)

For each finding:
1. **Note** it with the exact surface, repro, and `file:line`.
2. **Reproduce the root cause** at the engine/JS level (read the handler; check the
   network call; check the DB). Distinguish product bug vs. test-harness artifact
   vs. demo-data pollution.
3. **Remediate at the correct altitude** (CDA, minimal vendored diff):
   design tokens / `:root` → shared component classes → applicant CSS block → (only
   for a hardcoded dimension) the `style="…"` strings in `applicant*.js`. Engine
   user-facing strings live in `HTTPException(detail=…)` + message constants under
   `src/applicant/`. LLM-behavior fixes live in `application/services/`.
4. **Validate** by re-capturing the affected surface at both breakpoints AND running
   the green-increment gates: `uv run ruff check .`; `DATABASE_URL=…@127.0.0.1:1/none
   uv run pytest -q -m "not integration"`; front-door `pytest -q
   workspace/tests/test_applicant_*.py`; `node --check` on edited JS; single
   `alembic heads`; `docker compose -f docker/docker-compose.prod.yml config`; the
   white-label codename denylist (the CI step in `.github/workflows/ci.yml` is the
   single home of the banned-codename regex — never copy those literals elsewhere,
   or this very check will fail on your file).
5. **Ship**: focused commits on the working branch, push, open/maintain a PR; the
   diff is the review surface. When a change is architecturally significant or
   genuinely ambiguous (remove vs. fix a control; loosen a safety guard), **ask the
   user with explicit options** rather than guessing.
6. **Re-run** the relevant capture/sweep to confirm green, then move on. Keep a
   live status checklist; GC raw image tokens between states.

---

## 8. KNOWN FALSE POSITIVES (do not file these as bugs)

- **`textarea#message` "overflow"** — the vendored base-app chat composer, clipped
  behind applicant tool windows; document `scrollWidth` is NOT exceeded → no real
  horizontal scrollbar.
- **Scrim-less modals** — `.modal` is intentionally `background:none;
  backdrop-filter:none; pointer-events:none;` so tool windows float over the chat
  you can still reference. The chat showing through is by design (whole system does
  it). Don't add a backdrop to one window.
- **Mobile tab-strip "overflow"** — Settings/Activity tab bars are horizontal
  scrollers; off-screen tabs report `right > 375` but are reachable by scroll.
- **Stray-space hits in modal `innerText`** — nested flex/grid layouts produce
  inter-element whitespace runs; the real check is space-before-punctuation in
  visible *sentences*. The "?" after labels are tooltip help icons; "Ctrl ," is a
  shortcut display.
- **Ambient console errors** — `ERR_CERT_AUTHORITY_INVALID` and a favicon `404` are
  environment noise; filter them. A highlight.js "Could not find the language 'email'"
  warning is the vendored chat, not applicant.

---

## 9. INITIALIZATION VECTOR (what a fresh agent does, in order)

1. Acknowledge comprehension; obtain the **API key**.
2. Read `CLAUDE.md` + `workspace/CLAUDE.md`; honor the binding principles.
3. Stand up Postgres + engine + two front-doors; provision Playwright/Chromium.
4. Connect the model; verify `automated_work_allowed: true`.
5. Run the **contract sweep** (§6) — triage any 5xx first.
6. Walk the **role-play journey** (§5) at 1440 + 375, capturing + scanning each
   surface (§2), through every settings panel and dialog (§3).
7. For each finding, run the **note→debug→fix→re-run loop** (§7), judging LLM
   quality (§5a) along the way.
8. Maintain a single PR; keep CI green; deliver before/after screenshots.
9. Remind the user to **revoke the API key** when done.
