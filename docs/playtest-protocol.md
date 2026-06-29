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

### 5b. Assistant learning panels + desktop assist degrade
Two lift-and-shift capabilities to verify (specs: `docs/spec/agent-intelligence.md`,
`docs/spec/computer-use.md`):
- **What the assistant remembers / saved playbooks (live).** Open the Profile memory
  panel (`applicantMind.js`) and confirm "what the assistant remembers" + "saved
  playbooks" render and read back (proxy `/api/applicant/mind/memory` + `/mind/skills`).
  All copy is plain-language Applicant — flag any leaked upstream/dev string
  (e.g. `MEMORY.md`, `SKILL.md`, `skill_manage`, a codename) as a white-label bug.
- **Curation approvals (live).** When the assistant proposes a memory/playbook write it
  appears as an approve/deny item in the portal (`/api/applicant/mind/curation`). Confirm
  **only approving** applies it (a proposal alone changes nothing) — that is the
  advisory-not-authorization rule, not a bug.

### 5c. The agent learns, reports itself, and is steerable
The loop now learns from its own runs + the user's feedback, uses that learning, and reports
it in first person (specs: `docs/spec/agent-intelligence.md` FR-MIND, master-spec FR-AGENT-7 /
FR-OBS-2). Verify all three, end-to-end, with a populated campaign:
- **The chatbot reports its activity truthfully.** Open the Job Assistant chat
  (`applicantChatModule.openApplicantChat()`) and ask what it's doing / what it did / what's
  next. It should answer in **first person as the agent** (one identity, not a generic
  assistant) and the answer should match REAL state — cross-check against the run status,
  scheduler "next run" estimate, and recent application history (the same state the activity
  panel shows). **Flag fabrication**: if it claims activity that didn't happen, or says it
  can't see its own state, that's a bug (it should say "nothing yet" rather than invent).
- **The activity panel shows now / next / recent.** Open the "what the agent is doing" panel
  (`applicantActivity.js`; proxy `/api/applicant/activity/snapshot`) and confirm the now-line,
  the next-action line, and the recent-runs list render and agree with the chat answer and the
  Activity/Debug history. Offline-degrade check: stop the engine and confirm it returns a
  graceful `{engine_available:false}` empty state, not a 500/white screen. A daily status
  update should also arrive via the notification ladder (in-app inbox + opt-in fan-out).
- **A curation proposal appears for review after runs/feedback.** After at least one run AND a
  piece of user feedback (decline a digest role with a reason, or send a redline-revision
  instruction), the scheduled curation nudge should mine that signal and produce an approve/deny
  proposal in the portal (`/api/applicant/mind/curation`). Confirm the proposal text reflects
  the real run/feedback (not a placeholder), and that **only approving** writes it — declining
  leaves memory unchanged. (If `CURATION_SCHEDULE` is off for the playtest, trigger the nudge
  directly per the engine's curation route; absence of a proposal with the schedule off is not
  a bug.)
- **Desktop assist degrades (dormant).** In the live-session modal (`applicantRemote.js`)
  the "let the assistant help on the desktop" toggle ships **present-but-grayed**:
  `GET .../desktop/health` reports unavailable and `enable`/`action` are refused with
  honest copy until the desktop driver is baked into the sandbox image. A grayed, honestly-
  labeled control here is the **intended** state (no dead UI), not a defect — file a bug
  only if it renders as if live, or returns a 5xx instead of a graceful disabled state.

### 5d. Wave 2 — minimal onboarding + agent-callable tools + provenance
Three Wave 2 legs (deeper learning + onboarding; specs: `docs/spec/agent-intelligence.md` FR-MIND,
master-spec FR-ONBOARD/FR-OOBE). Verify each end-to-end:
- **Minimal onboarding begins setup but applying stays blocked until essentials exist.** Connect
  ONLY a model (skip the rest of the profile) and confirm setup proceeds, then check
  `GET /api/applicant/setup/status`: `automated_work_allowed` should be **false** with
  `apply_ready:false`, an `apply_missing` list (target roles, work mode, locations, salary floor,
  key skills, résumé), and an `apply_blocked_reason`. The wizard should show an honest "what's still
  needed to start applying" banner naming those gaps — not claim it's ready. Fill the essentials and
  confirm the gate flips to allowed. (A blocked gate with model-only setup is the **intended** state,
  not a bug.)
- **The chat can call a tool and the write is staged for approval.** With `CHAT_TOOLS` enabled, ask
  the Job Assistant chat to remember something or save a playbook. Confirm the tool call does NOT
  silently mutate memory — it lands as an approve/deny item in the portal curation queue
  (`/api/applicant/mind/curation`), and **only approving** applies it (review-before-write). A tool
  asserting authority (e.g. "submit this application") must be refused, not honored.
- **The review surface shows "What I drew on".** After a material generation that used learned
  memory/playbooks/recall, open the document/résumé review and confirm a **"What I drew on"** panel
  renders the recorded provenance (`GeneratedDocument.provenance`). Empty provenance should render an
  honest empty state, not a fabricated list.

### 5e. The grounding oracle — anchor every claim to engine truth (anti-fabrication)
Stop eyeballing fabrication. The engine is the source of truth; the chat, activity
panel, digest, and notifications are read-replicas that **must agree with it**
(NFR-TRUTH-1, FR-AGENT-7/FR-OBS-2). Verify it **mechanically**, every LLM-driven step.

The two cardinal sins:
1. **Invented entity** — a concrete fact in the rendered text (a company/role, an
   application status, a "next run" time, a count, a document it claims to have
   produced) that is NOT present in engine state.
2. **State bypass** — the assistant narrates an outcome the engine never committed
   ("I submitted to X", "I tailored your résumé") while the engine's status/history
   did not move.

**The before/after diff (the mechanical core):** snapshot the engine's closed-set
read endpoints before a step (`GET /api/applicant/activity/snapshot`, run/ops
status, application history, digest) and after; then assert (1) every concrete claim
in the rendered text maps to a real value in the snapshot; (2) any asserted outcome
is reflected by a real state change (a new run row, a status transition, a
`GeneratedDocument`); (3) when there's nothing to report, the text says "nothing
yet" rather than inventing. **Name-set check** for the digest: every company/role
narrated must appear in the engine's discovered-roles payload.

**False-positive discipline:** a sentence-initial capitalized word is not an invented
company — reconcile candidates against the engine list first. A transient optimistic
UI value that reconciles after the network settles is not a divergence — re-query
before filing. Only an unbacked claim, an outcome with no state change, or a
non-reconciling divergence is the bug. This is a first-class finding class alongside
CSS/copy defects.

### 5f. Two-window concurrency & parity (Applicant is multi-user — test it like one)
The same campaign can be open in two tabs. The protocol already stands up a second
front-door (§1.2) — use it to test **consistency**, not just to halve capture time.
The engine is the oracle for every parity claim.

1. **At-rest parity:** open the Portal, digest, and activity panel in both windows on
   the same account; the engine-truth fields (pending-action set, application
   statuses, "next run", digest contents) must be identical.
2. **Reconcile-after-action:** resolve a pending action in window A; window B must
   reconcile (the item disappears) within a bounded lag via the app's own refresh/
   notification path, not only after a manual reload.
3. **Concurrent-write race — and loop it (N≥10):** fire a state-mutating action in
   both windows near-simultaneously, then compare. A single green pass proves nothing
   about a race. Flag any iteration where engine state and the two UIs disagree, a
   pending item is lost/duplicated, or a JS error fires. A confirmation-gated 409
   with clean recovery is the guard working; a divergence without a 409 is the bug.
4. **Transient vs persistent:** if two windows diverge, reload both. Reconciles on
   reload ⇒ render-layer bug (scope the fix to the front-door); doesn't ⇒ data-layer
   bug (worse). A legitimate per-viewer difference (each window's own in-flight
   optimistic state) is not a defect; a lost/duplicated pending action or a
   non-reconciling engine-truth divergence is.

### 5g. The job-seeker persona & the "does this respect the applicant" rubric
Make §5's role-play repeatable and domain-expert: adopt ONE stable persona and play
it identically across runs so any behavior change is attributable to the product. The
persona is a job-search expert with low tolerance for tooling that wastes their time,
who files findings as "a real job application doesn't work like this." Keep the OOBE
intake (target roles, work mode, locations, salary floor, key skills, résumé)
identical across re-runs. For breadth, run 2–3 distinct personas in sequence (e.g. a
high-volume applicant, a selective senior candidate, a career-changer with a thin-fit
résumé) — each is this persona re-parameterized at intake.

Score every step; a miss is a finding tagged **[CORRECTNESS]** or **[RESPECT]**:
- *Correctness:* no fabrication ever (generated material states only what the user's
  profile/résumé supports); review-before-submit is inviolable (no engine self-submit);
  match quality is honest (surfaced roles fit the stated criteria); tailoring is real
  and grounded with accurate "What I drew on" provenance; learning is real (a declined
  role with a reason / a redline feeds curation, and only approving writes it).
- *Respect:* no dead ends or lies about state; the agent has one honest first-person
  identity ("nothing yet" over invention); approve/decline/redline moves something
  real; plain language, no jargon/codenames/`FR-`/`NFR-` leaks (principle #3).

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

## 6a. AUTOMATED UI MONKEY / CRAWL (full-regression, run-until-green)

The contract sweep (§6) exercises endpoints; this exercises the **rendered UI the
way a user's clicks do** — it opens every surface and clicks every (non-destructive)
interactive control, catching handler exceptions, console errors, and bad HTTP that
a passive capture misses. It's the automated backbone of a "test the whole product,
re-run until 100% green" pass. Author it as an ephemeral Node+Playwright script in
git-ignored `.audit-telemetry/monkey.js`; it is a *test harness*, not shipped code.

**What it does (deterministic crawl, not random):**
1. **Auth once** via `ctx.request.post('/api/auth/login', …)` so every page shares the cookie.
2. **Enumerate surfaces** and open each via the JS seam (most reliable) — fresh page per
   surface, `goto('/')`, remove the auto-opened onboarding overlay (except when auditing
   onboarding), then:
   | Surface | Opener | Root to await |
   |---|---|---|
   | home | (none) | — |
   | portal | `window.applicantPortalModule.openApplicantPortal()` | `#applicant-portal-modal` |
   | chat | `window.applicantChatModule.openApplicantChat()` | `#applicant-chat-modal` |
   | vault | `window.openApplicantVault()` | `#applicant-vault-modal` |
   | remote | `window.openApplicantRemoteSession()` | `#applicant-remote-modal` |
   | onboarding | `window.launchApplicantSetup()` | `#applicant-onboarding-overlay` |
   | **settings** | click **`#user-bar-settings`** (NOT `#rail-settings` — it's hidden when the sidebar is expanded, so clicking it silently no-ops) | `#settings-modal` |
   | debug | click `#tool-debug-btn` | — |
   …plus the URL-routed pages `/memory /library /calendar /notes /tasks /gallery /email`.
3. **Click every control** within the surface root: `button:not([disabled]), .cal-btn,
   .admin-tab, [role="button"], a[href^="#"], a:not([href]), [data-settings-panel]` —
   tag each with `data-monkey-idx`, **skip destructive labels** (a denylist regex:
   `log\s?out|sign\s?out|delete|remove|trash|danger|reset|disconnect|revoke|deactivate|
   wipe|destroy|decline|^pass$|unsubscribe|clear all|drop`), click, press `Escape` to
   dismiss any popover, capture errors. Cap at `MAX_CLICKS` (40) per surface.
4. **Mobile pass** (375×812) over the modal surfaces (they become full-screen sheets).

**Classify findings precisely (so "green" means green):**
- `pageerror` — uncaught JS exception. **Always a defect.**
- `http5xx` — any 5xx response. **Always a defect.**
- `http4xx` — a 4xx response **whose URL is not in the NOISE allowlist** (a genuinely
  wrong/missing endpoint). Known-benign gated/auth/empty 4xx are filtered by URL.
- `console` — a real `console.error`/uncaught message. **Drop URL-less "Failed to load
  resource" lines** — they carry no URL, are unactionable, and are redundant with the
  URL-aware response handler; judging HTTP by URL+code (not by that string) is what lets
  the run go truthfully green.
- `open-failed` — the surface root never appeared (a real reachability bug, OR a wrong
  opener in the harness — verify which before filing).
- **NOISE allowlist** (URL/text regexes, per §8): `ERR_CERT_AUTHORITY_INVALID`;
  `/api/research/status/…` + `/api/chat/stream_status/…` (vendored stale-session stream
  poller, 404 by design); `/api/applicant/email/digest/…` (require_automated_work-gated
  → 409 pre-setup, handled in the Portal UI); favicon 404; highlight.js "Could not find
  the language"; `net::ERR_ABORTED` (fetches aborted on teardown).

Exit `0` = green (empty report), `1` = issues (writes `monkey-report.json`).

**The run-until-green loop.** Run it; for every issue decide **product bug vs. harness
bug vs. known-benign noise**:
- *Product bug* → fix at the right altitude (§7) and re-run.
- *Harness bug* (e.g. clicking the hidden `#rail-settings`, so settings was never
  actually exercised; or filtering by an URL-less console string) → fix the harness so
  coverage is real, then re-run. A hollow green (a surface that silently failed to open)
  is **not** green.
- *Known-benign* → add the precise URL/text to the NOISE allowlist with a comment.
Re-run until **0 issues across every surface + route + the mobile pass**, then confirm
stability with one extra identical run (the click-through has timing variance).

**The full-product green bar** = this crawl green **AND** every CI gate: `uv run ruff
check .`; `DATABASE_URL=…@127.0.0.1:1/none uv run pytest -q -m "not integration"`;
`pytest -q workspace/tests/test_applicant_*.py`; `node --check` on every edited JS;
single `alembic heads`; `docker compose -f docker/docker-compose.prod.yml config`
(`APP_PORT=8000 POSTGRES_PASSWORD=ci-validate`); the white-label denylist.

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

## 8a. CODE-LEVEL SAFETY AUDIT (static — beyond the visual sweep)

The UI sweep finds reachability + visual defects; it does NOT find a **safety
guarantee that is silently inert on the reachable path**. Audit those statically
with one lens: **for each stated promise, is it actually enforced where the
front-door reaches?** Trace promise → the rule → every call site → the reachable
caller's inputs. Real bugs found this way (each shipped as a focused PR):

- **A guard that no-ops when the caller omits an optional input.** The redline
  revision (`MaterialService.apply_turn`) ran the fabrication guard only `if
  true_source is not None`, but the front-door turn sends none → every in-app
  revision skipped it (NFR-TRUTH-1). Fix: derive ground truth server-side; never
  trust the caller to opt into a safety guard.
- **In-memory state defeated by a per-tick rebuild.** The scheduler builds a fresh
  `AgentLoop` every tick, so its in-memory resume backoff + failure-cap reset each
  tick — both inert under the real 24/7 loop though green in unit tests. Fix: a
  process-lived ledger injected into every per-tick instance. **Check any
  per-tick-rebuilt service for cross-tick in-memory state** (caches/dedup/counters).
- **A manual action polluting scheduled state.** `run_now` overwrote the
  scheduler's `_last_tick_at`, corrupting the "next run" estimate.
- **A permanently-failing retry with no cap.** A stuck application re-drove forever;
  add a consecutive-failure cap + a single deduped alert.

**Safety-property checklist (all verified enforced as of this audit — re-verify):**
- **No engine self-submit.** The pipeline `recv` final-approval gate PARKS on
  timeout (never proceeds); submit only fires on an explicit user-delivered
  decision; the browser final-submit click is gated by `engine_submit_authorized`
  (True only on the `authorize-engine-finish` endpoint); `record_submission`
  enforces the review gate (`ensure_submittable`).
- **No secret leakage.** Credentials are libsodium-sealed at rest; `store` logs only
  metadata; GET endpoints return tenant keys, never secrets; tier `get_tiers` omits
  keys (exposes only an `api_key_ref` marker).
- **Fabrication guard + non-AI-voice post-filter on EVERY material path** —
  resume/cover/screening generation AND revision (post-filter before the guard).
- **Confirmation gate (FR-FB-3).** Integral attribute/criterion changes route
  through `ensure_change_allowed`; chat never auto-commits integral.
- **Internal callback channel.** Token unset ⇒ 403 (disabled); constant-time
  `secrets.compare_digest`; `verify_internal_token` is the first statement of every
  handler.
- **No unbounded memory growth** in process-lived singletons (research cache is
  budget-bounded; the notifier prunes).
- **Every new proxy route carries an auth guard** (`_require_admin` /
  `require_user` / `require_privilege`).

---

## 8b. LLM TRANSPORT-CONFORMANCE AUDIT (static — the streaming error contract)

§5a judges whether the model's *output* is good enough; this audits the *transport*,
where a turn dies with no error surfaced. Locate the engine's single LLM HTTP
boundary (the model client under `src/applicant/adapters/` that builds
chat-completions requests and parses the streamed response) and score each item
SUPPORTED / PARTIAL / MISSING:
- **Mid-stream error chunk (`finish_reason:"error"`):** a provider can emit an
  in-band error *after* streaming starts (overloaded, policy block, timeout). If the
  client ignores it and treats the stream as a normal end, the user sees text stream
  then disappear, or a blank turn, with no error — the likeliest cause of "it
  generated then vanished." Confirm the client detects and surfaces it.
- **`Retry-After` on 429/503:** a fixed backoff that ignores it re-hits the limit and
  burns the retry budget on a transient one timed retry would survive.
- **Typed errors not flattened:** moderation/content-policy/provider errors carry
  structured metadata; flattening to "HTTP 4xx" makes an input-flagged failure
  indistinguishable from a dead key — and for a résumé/cover generator, an
  input-policy block must be legible.
- **Empty-completion retry:** a streamed round yielding zero content should retry, not
  surface as a blank document.
- **(Lower priority) JSON-mode for constrained extraction** (discovery/criteria/
  learning) hardens the parse against the model wrapping JSON in prose.

These map directly to user-visible failures in the data-dependent states (digest,
review, redline revision, chat, material generation).

---

## 9. INITIALIZATION VECTOR (what a fresh agent does, in order)

1. Acknowledge comprehension; obtain the **API key**.
2. Read `CLAUDE.md` + `workspace/CLAUDE.md`; honor the binding principles.
3. Stand up Postgres + engine + two front-doors; provision Playwright/Chromium.
4. Connect the model; verify `automated_work_allowed: true`.
5. Run the **contract sweep** (§6) — triage any 5xx first.
6. Run the **automated UI monkey/crawl** (§6a) across every surface + route +
   the mobile pass; triage each finding (product / harness / noise) and **re-run
   until 0 issues**, then one extra run to confirm stability.
7. Walk the **role-play journey** (§5) at 1440 + 375, capturing + scanning each
   surface (§2), through every settings panel and dialog (§3).
8. For each finding, run the **note→debug→fix→re-run loop** (§7), judging LLM
   quality (§5a) along the way.
9. Run the **code-level safety audit** (§8a): for each safety promise, trace it to
   the reachable caller and confirm it is actually enforced (not inert).
10. Confirm the **full-product green bar** (§6a): the crawl green AND every CI gate.
11. Maintain a single PR; keep CI green; deliver before/after screenshots.
12. Remind the user to **revoke the API key** when done.

> The exit condition is no longer "0 issues" — it is **§10's ship gate**: no
> launch-blocker open and the front-door-airtight bar proven (the looped §5f
> harness), on top of the full-product green bar (§6a).

---

### 9a. Per-run plan & findings record (vs. this playbook)
This file is the **stable, reusable playbook**. Each actual audit also produces two
dated artifacts under `docs/audits/` (create it if absent), so runs are comparable
and the playbook stays clean:
- **A run plan** — what's specific to this run: persona(s), model/tier ladder,
  DOC-ONLY vs fix-as-you-go, and the state ladder to walk: **S1** initial/zero-data →
  **S2** onboarding (connect model → intake → résumé upload + conflict reconciliation
  → conversion accept/reject) → **S3** core loop (Portal, digest, refresh, research,
  the review→redline→approve loop, chat, settings) → **S4** resolution/edge
  (final-submit / live-takeover, offline-degrade, multi-window §5f). Capture a
  screenshot at each *distinct* UI state.
- **A findings record** — dated `docs/audits/YYYY-MM-DD-playtest-*.md`: each finding
  under the §4 lenses + the §5 functional/grounding checks, triaged **[Launch-Blocking]
  vs [Polish]** against §10, each backed by a cited screenshot, with fixes at the §7
  altitude. Keep secrets out (the key lives only in the git-ignored telemetry dir).

---

## 10. THE SHIP GATE (what actually blocks a release)

"0 issues across every surface" (§6a) is the **quality** bar for a clean audit — not
the **ship** bar; held literally, a cosmetic nit blocks release forever. This draws
the hard line: a finite set of launch-blockers, everything else explicitly
post-launch or parked. The reason blockers hide is that **every CI gate stubs the
LLM** — the product's real behavior lives in the model↔engine seam (digest reasoning,
tailoring, the truthful self-report), the one thing CI never exercises. So make the
**real-model golden path** the acceptance bar.

The golden path (real model wired, not a stubbed gate):

| # | Gate | Pass criterion |
|---|---|---|
| G1 | Onboarding completes | model + profile → `automated_work_allowed: true`, `apply_ready: true`. |
| G2 | Honest gate when incomplete | model-only setup leaves it false with a truthful "what's still needed" banner. |
| G3 | Loop runs without a nudge | discovery → digest → review reach the user on schedule; "now/next/recent" matches the run log. |
| G4 | Digest grounded | every surfaced role exists in engine discovery and fits criteria (§5e holds). |
| G5 | Tailoring grounded & review-gated | generation/revision state only profile-supported facts; the fabrication guard fires on every material path incl. revision; non-AI-voice post-filter; provenance renders. |
| G6 | No engine self-submit | a final submit fires only on an explicit user decision; the review gate holds. |
| G7 | Truthful self-report | chat/activity match engine state; "nothing yet" when nothing happened (§5e holds). |
| G8 | No machinery/leak in user text | no internal ids, reasoning tokens, secrets, codenames, or `FR-`/`NFR-` jargon; credentials stay sealed (§8a). |
| G9 | Multi-user isolation | one owner never sees another's data; every proxy route auth-guarded; concurrency holds (§5f). |

**The front-door-airtight bar** (gate separately — model-independent): the §5f
two-window checks — no lost pending action, right control state, concurrent writes
converge with zero loss, prompt reconcile — proven by the *looped* harness.

**Triage rubric — bucket every open issue on sight:**
- **LAUNCH-BLOCKER** — breaks G1–G9 on the real-model golden path or the airtight bar
  (dead screen, fabrication, leaked secret/codename, self-submit, stuck loop,
  cross-user violation, lost user action). Only these block ship.
- **POST-LAUNCH** — real but doesn't break the golden path (secondary-surface polish,
  reachable responsive nits, enhancements, calibration §11). Ship; fast-follow.
- **PARKED** — needs a product decision or external input (deploy/host-dependent items
  like the takeover-desktop sandbox). Surface to the maintainer; don't spend agents.

A long bug list is **not** a launch backlog — it's overwhelmingly post-launch/parked.
Where possible, make the golden path an automated gate (record one real run; replay it
deterministically; nightly real-model smoke for prompt drift).

---

## 11. CALIBRATION DATA (when the question is "is this tuned right?", not "is this broken?")

Some findings are **tuning**, not bugs: is the digest too aggressive/conservative? Is
the match scoring surfacing the right roles? Is tier-escalation sending the right tasks
to the stronger model (§5a)? Is the banned-phrase/aggressiveness setting producing
material that's too bland or too padded? Don't tune on vibes — gather data with a
controlled comparison and keep a dated record.

**Method (controlled A/B, attributable):** hold the input fixed (same profile/criteria,
same candidate role set) and vary ONE knob between two arms (e.g. aggressiveness low vs
high; entry tier vs escalated) over the same inputs, so any difference is attributable
to the knob. Measure the outcome that matters (roles surfaced and their real fit;
tailoring quality by the §5g rubric; fabrication/leak rate; escalation correctness).

**Deliverable:** a dated `docs/audits/YYYY-MM-DD-calibration-*.md` data record
(DATA-ONLY — changing the knob is a separate, deliberate follow-up) with a ranked
tuning menu (knob, direction, expected effect), ordered by impact-per-risk. After any
change, re-run the same comparison and confirm the safety guards still hold — a
calibration change that raises the fabrication or self-submit rate is a regression,
full stop. (Applicant has no seeded deterministic engine to replay, so this is a
fixed-input controlled comparison, not an N-seed simulation.)
