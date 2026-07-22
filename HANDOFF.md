# Applicant 2.0 — Handoff

> The port of the Applicant engine onto the Agent Zero (A0) shell. This document is the single
> pick-up point: current state, what's blocked on whom, turnkey runbooks, architecture, ops tooling,
> and the hard-won gotchas. Originally written 2026-07-21; **this revision 2026-07-22** adds the
> user-journey debugging arc (three product-wide frontend bugs found + fixed + browser-verified
> against a fully wired deployment), the end-to-end deployment recipe, and the current git topology.

---

## TL;DR

Applicant 2.0 is **functionally built and now verified end-to-end in a real browser against the live
engine**: 19/20 sidebar journey panels open clean *with real engine data* in a wired deployment
(the 20th is a test-harness click artifact, not a product bug — see §4.4). Getting here required
finding and fixing **three product-wide frontend bugs that no source-level test could see**
(§4.1–4.3) — they are the most important new knowledge in this document.

State of the world:

- **Backlog:** 63 → **38 open** (25 closed + verified this program). The former "big blocker" —
  no browser-testing deployment for panel work — is **RESOLVED** (§5). The AZ5/AZ6/AZ7 chains are
  unblocked.
- **Branch:** everything lives on `claude/refactor-agent-zero-applicant-xn7xoc`
  (local tip `21470f8f2`). Local branch is **307 commits ahead** of its pushed copy on origin;
  local `main` is 192 ahead / 1 behind `origin/main`. Reconciliation is a deliberate, owner-approved
  step (§7) — do not casually push or merge.
- **Production gap:** the compose stack's `docker-a0-1` (:8090) still runs a **pre-fix image**.
  One rebuild command rolls all three bug-fixes out (§5.3).
- **The remaining unlocks are unchanged** and are yours (credentials/business): GitHub token for
  issue ops, LLM key placement, mailbox/calendar credentials, companion first-run (§2).

---

## 1. The two products — NEVER conflate them

- **Agent Zero** = the personal agentic *coding tool* at `localhost:5080` (container `agent-zero`).
  It must stay pristine base-A0. It is also the upstream that Applicant tracks
  (`upstream` remote = `agent0ai/agent-zero`).
- **Applicant** = a standalone product: a HUGE fork of A0 (`github.com/kevinhirsch/applicant`) that
  takes A0's MIT frontend and reshapes it. Own repo, own container images, own deployment.
- **Never mount Applicant code into the personal A0.** (A plugin-symlink once made base A0 render the
  Applicant UI — removed 2026-07-21. Do not repeat.) Applicant UI testing gets its OWN containers (§5).
- The A0 *tool* is also the **coder**: Claude pilots (specs/verifies/steers), A0 writes all Applicant
  code (see §6). Repo checkout lives at `/a0/usr/projects/applicant` inside `agent-zero`
  (host path `/home/kevin/agent-zero/agent-zero/usr/projects/applicant`, root-owned — read/edit it
  via `docker exec`, not from the host).

---

## 2. The owner unlocks (critical path) — turnkey runbooks

### 2a. `GITHUB_TOKEN` / issue ops
- Issue closes this program went through **A0's github MCP** (no PAT in any shell — decision:
  keep it that way). For bulk closes, dispatch A0 with the issue list + evidence comments.
- If you do export a PAT: rotate first; `~/agent-zero-ops/gh-issue.py` reads `GITHUB_TOKEN`/`GH_TOKEN`
  from env only and never prints secrets. GOTCHA: GitHub's **GraphQL and REST-core rate limits reset on
  separate clocks** — when `gh issue close` (GraphQL) is exhausted, `gh api -X PATCH
  repos/kevinhirsch/applicant/issues/N -f state=closed -f state_reason=completed` (REST) still works.

### 2b. LLM key → engine Plane-B and A0's cloud tier (ONE key, two places)
- **Engine (Plane B):** `LLM_PROVIDER=openai`, `LLM_BASE_URL=https://api.deepseek.com/v1`,
  `LLM_MODEL=deepseek-chat`, `LLM_API_KEY=<key>`. **Do NOT put these in the repo root `.env`** —
  pydantic Settings loads it and 20 `llm_configured` tests break. Inject into the **api container's**
  `environment:` in `docker/docker-compose.yml`, then recreate `docker-api-1`. Needed only for live
  material generation (#145 etc.), not for the shell.
- **A0's model tiering — CURRENT LIVE STATE (post-revert):** the 2026-07-21 "everything to cloud"
  global swap was **REVERTED**. A0 now runs the §0.3 reference topology
  (`docs/backlog/az-port-intelligence-routing.md`): overseer `agent0` = DeepSeek-Chat;
  `coder`/`explorer`/`test-engineer` = **Default preset (local Qwen3.6-27B @ 10.0.1.225:8000)**;
  `reviewer`/`security-auditor`/`coder-cloud`/`explorer-cloud` = DeepSeek-Flash; `debugger` =
  DeepSeek-Pro. Live config = `/a0/usr/agents/<name>/plugins/_model_config/config.json`
  (backups: `.bak-pre-localfix`, `.bak-pre-cloud`). **Keep the live `_model_config` in sync with the
  repo topology spec** — the original all-local grind happened because the spec was never applied.
- Local Qwen converges on small/contract units but over-explores on multi-file panel work — keep
  drives small; escalate hard units to the cloud profiles.

### 2c. Mailbox/calendar credentials → real lanes
- Mock backend exists (`src/applicant/adapters/workspace/mock_workspace_client.py`,
  `LANE_BACKEND=mock`) — lane logic is testable without creds.
- Real Gmail/CalDAV go on the **companion** (it owns IMAP/CalDAV; engine reaches it via the
  internal-token channel). Docs: `docs/backlog/lane-mock-and-real-creds.md`.
- **Decision of record (2026-07-21):** credentials are **self-served by the owner via the UI**
  (Connections panel, build #844) — Claude/A0 never handle them. Companion first-run setup is to be
  cracked programmatically where possible; the account/password step itself is the owner's.

### 2d. Business/owner items (locked decisions)
- Product name = **"Applicant"** — locked; never re-ask business items.
- Owner-held issues — **never touch**: #671, #672, #698–700, #706–708, #716–718, #722.

---

## 3. Architecture — the running stack

```
                         HOST (docker, network: docker_default)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  docker-api-1 (ENGINE :8000)  ── MIND_BACKEND=bridge ─┐                    │
  │     Plane B LLM (needs LLM_API_KEY)                   │ internal-token     │
  │     /api/campaigns,/api/tracker,/api/setup/*,...      │ /api/applicant/    │
  │        ▲                                              ▼ internal/*         │
  │        │ ENGINE_URL=http://api:8000        docker-companion-1 (:7000)      │
  │        │ (resolves only on docker_default —     workspace/mailbox/caldav   │
  │        │  ensure-engine-net.sh)                 "Setup required" 401       │
  │  docker-postgres-1  docker-chromadb-1  docker-searxng-1  docker-ntfy-1    │
  │  docker-a0-1 (PRODUCTION Applicant shell :8090 → 80) ← REBUILD PENDING §5.3│
  └────────┼───────────────────────────────────────────────────────────────┬─┘
           │ (a0-applicant proxies forward here)                            │
  ┌────────┼──────────────────────────────┐              lanes: engine ──► companion
  │  agent-zero container (A0 CODER :5080) │              mock: LANE_BACKEND=mock
  │   repo at /a0/usr/projects/applicant   │              real: creds (owner, via UI)
  │   overseer DeepSeek + local Qwen coder │
  └────────────────────────────────────────┘
  applicant-e2e (:8091) = disposable wired test instance, §5.2
```

- **Two model planes** (FR-INTEL contracts under `config/intel_*.yaml`): Plane A = shell/agent
  models (9 profiles → 3 tiers); Plane B = engine LLM calls. Disjoint ownership pinned in
  `config/intel_planes.yaml`.
- **Fork image:** `docker/Dockerfile.a0` = `FROM agent0ai/agent-zero:v2.4` +
  `COPY a0-applicant/ /a0/plugins/applicant/` + branding overlay. `/a0/plugins` is unmasked image
  content (the `a0-data:/a0/usr` volume masks `/a0/usr` on first boot — a plugin under `/a0/usr/plugins`
  would be masked; that's why the image copies into `/a0/plugins`). `get_plugin_roots()` scans both.
- **Panel loading path:** sidebar launchers (defined in
  `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`) call
  `window.openModal('/plugins/applicant/webui/<panel>.html')` → `openModal` (`webui/js/modals.js:262`)
  → `importComponent` (`webui/js/components.js:11`).
- **Critical wiring:** a0-applicant proxies default to `ENGINE_URL=http://api:8000`, which resolves
  only if the calling container is on `docker_default`. After recreating any shell container, run
  `~/agent-zero-ops/ensure-engine-net.sh` (idempotent) or pass `--network docker_default`.

---

## 4. ⭐ THE JOURNEY-DEBUG ARC (2026-07-21→22) — three product-wide frontend bugs

Every one of these was invisible to source-assert tests AND to the standalone panel-render harness.
They only surfaced by driving the *real shell* in a *real browser* through the *real sidebar* against
a *wired backend*. Understand all three before touching panel code.

### 4.1 Modal-init bug (~30 panels) — commits `4130aa3bb`, `06bda0eb3`, `8882eb57a`, `3ca6dad76`
- **Symptom:** every panel opened via the sidebar threw `"<name>Panel is not defined"`; panels only
  worked when loaded standalone (which is all the old harness ever tested).
- **Root cause:** panels registered Alpine data inside `<script type="module">` behind
  `document.addEventListener("alpine:init", ...)`. The shell's `importComponent` executes inline
  module scripts via **async `import(blobUrl)`** — by the time they run, Alpine has already mounted
  the modal and `alpine:init` has already fired. Standalone full-page loads don't have this timing.
- **Fix pattern (now the house style for every panel):** a **non-module** `<script>` wrapped in an
  IIFE that registers synchronously:
  ```html
  <script>
  (() => {
    const _apiP = import("/js/api.js");
    const callJsonApi = async (ep, ...a) => (await _apiP).callJsonApi(
      (ep && String(ep).startsWith("plugins/")) ? ep : ("plugins/applicant/" + ep), ...a);
    window.Alpine.data("healthPanel", () => ({ /* ... */ }));
  })();
  </script>
  ```
  The IIFE is REQUIRED — non-module top-level `const`s collide globally across panels
  (`"_apiP already declared"`). Reference implementations: `documents.html`, `today.html`.

### 4.2 API-prefix bug (all 38 API-calling panels) — commit `e70891408`
- **Symptom:** in a wired deployment every panel's data fetch 404'd; panels showed empty/error states
  even though the engine was healthy.
- **Root cause:** A0 serves **plugin** api handlers at `/api/plugins/<plugin>/<handler>` —
  `helpers/api.py:206-268` registers one Flask rule `/api/<path:path>`; a bare path resolves only
  against the **built-in `/a0/api/*.py`** handlers, and plugin lookup triggers only when the path
  starts with `plugins/`. All panels called `callJsonApi("campaigns")` → `/api/campaigns` → 404.
  Built-in plugins (`_memory`, `_time_travel`) avoid this via an `apiPath()` helper the fork never used.
- **Red herrings to avoid re-chasing:** `/api/health` returns 200 *without* the fix because a
  **built-in** `/a0/api/health.py` shadows the applicant one (gitinfo payload, not ours).
  Test-importing handlers with `/usr/bin/python3` fails on `flask` — that's the wrong interpreter;
  A0's runtime python is `/opt/venv-a0/bin/python` and imports all 43 handlers cleanly.
- **Fix:** the per-panel `callJsonApi` wrapper prepends `plugins/applicant/` (see 4.1 snippet) —
  38 files, call sites untouched. Verified: `/api/plugins/applicant/campaigns` → 200 with live
  campaign rows from postgres.

### 4.3 Null-init bug (criteria, ops; pattern applies everywhere) — commits `16c20d84b`, `21470f8f2` (+ `51e61dad4` for tracker/research)
- **Symptom:** `Cannot read properties of null (reading 'titles'/'entries'/…)` at panel open, even
  with data-guards in the load methods.
- **Root cause (subtle):** **`x-show` only toggles CSS display — Alpine still evaluates every child
  binding.** An `x-for="t in criteriaData.titles"` inside a hidden `x-show` block dereferences
  `criteriaData` at *initial mount*, before any `load()` method has run. So post-load normalization
  (which A0's coder correctly wrote, twice) can never fix it.
- **Fix pattern:** initialize every x-data field to its real empty *shape*, never `null`:
  `criteriaData: { titles: [], locations: [], work_modes: [], keywords: [] }`,
  `signatureData: { facets: {}, samples_total: 0 }`, `historyData: { applications: [] }`,
  `detectionsData: { detections: [] }`, `logsData: { entries: [] }` — plus keep the load-method
  normalization (`d.titles = d.titles || []`) for the post-fetch path.
- **Rule for new panels:** no `x-data` field that a template dereferences may start as `null`.

### 4.4 Verification result (the current ground truth)
- Journey crawl (real login → click each of 21 sidebar launchers → capture pageerrors) against the
  wired `applicant-e2e` instance: **19/20 panels CLEAN with real engine data**
  (Setup, Today, Documents, Connections, Vault, Tiers, Health, Mind, Tracker, Screening, Campaigns,
  Profile, Model Endpoints, Easy Apply, Criteria, Ops, Research, Automation, Save a Job — and Digest,
  which was clean in the first post-fix crawl).
- **Digest "CLICK-FAIL" in later crawls is a harness artifact:** the crawler clicks launchers by
  visible text and intermittently can't click "Digest" mid-sequence (modal overlay timing). The
  launcher exists and is correct (`hello-world.html`, `openModal('/plugins/applicant/webui/digest.html')`)
  and the panel opened clean when the click landed. A `Chat` CLICK-FAIL is the same artifact
  (label-text ambiguity).
- Remaining known noise: `err_no_message` from the older panel harness is a NOISY metric (mix of
  panels that don't try/catch `callJsonApi`'s **throw** — it throws on error, `api.js:44`, it does not
  return `{ok:false}` — and static panels with no API calls). Do not chase it to 0; fix by adding
  try/catch per panel opportunistically (pattern: `today.html` loadItems).

---

## 5. Deployments + test instances (the former "big blocker", now solved)

### 5.1 Production compose stack (project `docker`, fork's `docker/docker-compose.prod.yml`)
`docker-a0-1` (Applicant shell, :8090→80, image `applicant/a0:latest`), `docker-api-1` (engine :8000),
`docker-companion-1` (:7000), `docker-postgres-1`, `docker-chromadb-1`, `docker-searxng-1`,
`docker-ntfy-1`, `docker-updater-1`. The stack auto-restarts on reboot. `.env` at the fork root is
root-owned — drive compose with `sudo -n docker compose --env-file .env -f docker/docker-compose.prod.yml …`.

### 5.2 Disposable wired e2e instance (the panel-verification workhorse)
```bash
cd /home/kevin/agent-zero/agent-zero/usr/projects/applicant
sudo -n docker compose --env-file .env -f docker/docker-compose.prod.yml build a0
docker rm -f applicant-e2e; docker run -d --name applicant-e2e -p 8091:80 \
  --network docker_default \
  -e AUTH_LOGIN=e2etest -e AUTH_PASSWORD=e2etestpw123456 \
  -e ENGINE_URL=http://api:8000 -e COMPANION_URL=http://companion:7000 \
  -e A0_SET_MCP_SERVERS='{"mcpServers":{"applicant-engine":{"url":"http://api:8000/mcp","type":"sse","disabled":false}}}' \
  applicant/a0:latest
```
Boots in ~20-25s (poll `/login` for HTTP 200 before testing — a too-early crawl reports 0/0 CLEAN).
Known creds because A0's `get_dotenv_value` = `os.getenv(key, default)` — env vars override `.env`.
There is also a lighter mount-based variant (`applicant-panels` on :5081, ro-mount of `a0-applicant/`
over `/a0/plugins/applicant`) for pure UI iteration without a rebuild.

### 5.3 ⚠️ PENDING: roll the fixes into production
`docker-a0-1` still runs a pre-journey-fix image. When ready:
```bash
cd /home/kevin/agent-zero/agent-zero/usr/projects/applicant
sudo -n docker compose --env-file .env -f docker/docker-compose.prod.yml build a0
sudo -n docker compose --env-file .env -f docker/docker-compose.prod.yml up -d --no-deps a0
```
Then re-run the journey crawl against :8090 to confirm.

### 5.4 Verification tooling (all run from the `agent-zero` container — it has playwright)
- **`/a0/tmp/journey_via_sidebar.py`** (source: session scratchpad `journey_via_sidebar.py`) — the
  gold-standard check: real login (env `JBASE`/`JUSER`/`JPW`), clicks all 21 sidebar launchers,
  captures per-panel pageerrors. Run:
  `docker exec -e JBASE=http://applicant-e2e:80 -e JUSER=… -e JPW=… -e PLAYWRIGHT_BROWSERS_PATH=/a0/tmp/playwright agent-zero /opt/venv-a0/bin/python /a0/tmp/journey_via_sidebar.py`
- **`scripts/playtest_panels.py`** — standalone render + error-injection harness (stubs shell
  globals). Good for per-panel iteration; remember its two blind spots: it cannot see modal-timing
  bugs (4.1) and it false-positives on unstubbed shell globals.
- **`scripts/playtest_crawl.py`** — front-door monkey/crawl.
- Chromium lives at `/a0/tmp/playwright` (base container only — fresh instances don't have it, which
  is why crawls run *from* `agent-zero` *against* the target instance over the docker network).
- Project `.venv` has NO playwright; use `/opt/venv-a0/bin/python` for browser work,
  `.venv/bin/pytest` for the test suite.

---

## 6. Driving A0 (the coder) — pipeline + discipline

### 6.1 The working pipeline
1. **Scope** batches with cost-routed Claude Workflows (sonnet agents; one per issue) → per-issue
   `{already_done, gap, a0_spec, acceptance_oracle, effort, needs_visual, blocked_on}`.
2. **Close** already-done issues (via A0's github MCP; see §2a for rate-limit fallbacks).
3. **Dispatch** gaps to A0 **serially** (concurrent drives cross-stage `git add -A` commits):
   session-login + CSRF → `POST /api/message_async` with a fresh `context` per task. Helper:
   `~/agent-zero-ops/az-send.sh "<spec>" "<ctx>"`. Plain `docker exec` — **never `sudo docker exec`
   in detached shells** (fails silently).
4. **Verify every commit:** `git show --stat` must be fork-only (never `/a0/usr/agents` or
   `/a0/usr/plugins`); run the unit's acceptance oracle; **browser-verify anything visual** (§5.4).
5. **Full-suite gate** per batch: `.venv/bin/pytest -q`; baseline = the known pre-existing env/doc
   failures ONLY (`test_prod_compose_env_file`, `test_deploy_hardening_lens04`, + the documented
   compose/doc-drift set). Never "fix" the baseline failures; never accept new ones.
6. React on **commits, not timers**: a Monitor on the repo HEAD pings per commit; keep a ~1500s
   stall safety-net. `az-rmchat.sh <ctx>` frees the GPU after a drive.

### 6.2 Spec discipline (what makes local Qwen reliable)
- Small units: proxy + panel + 1 test (+ sidebar wire-in as a separate tiny drive).
- Always include: work ONLY in `/a0/usr/projects/applicant`; ZERO `git branch/checkout/switch`;
  exact engine paths (coders confabulate paths — e.g. `/api/auth` vs `/api/admin`); the exact
  commit-message text; a runnable VERIFY command with expected output.
- **When A0 misses the same root cause twice, stop re-dispatching and fix it directly** (the
  standing "mechanical fix" exception) — e.g. the 4.3 initializer fix was 5 surgical lines after two
  A0 attempts normalized post-load only.
- A0 parity patches applied to the coder profiles (all `.bak`-backed, in `/a0/usr/agents/*/prompts` +
  `_guardrails`): whole-spec delivery, commit-before-gate, exact-engine-paths, no-credential-hunting,
  no-branch-switching, destructive-command classifier, playtest-verify-visual, size-route doctrine.

### 6.3 Verified A0 gotchas
- A0 file-rewrites can **drop the executable bit** (broke `backup.sh`/`restore.sh`; fixed via
  `git update-index --chmod=+x`, commit `86d237699`). Check `git ls-files -s` after script edits.
- A per-issue oracle can pass while a cross-cutting test breaks — the batch full-suite gate is
  non-negotiable (caught the #836 gate regression and 4 registry regressions).
- The DeepSeek overseer once correctly **refused** a mis-scoped issue rather than hallucinate a
  commit — trust but verify every commit's scope.
- Heredoc-fed `docker exec -i … python -` sometimes silently delivers an empty script (observed
  twice). **Always write scripts to a file, `docker cp` in, then execute** — and verify effects
  (e.g. `git diff --stat`) rather than trusting echoed OKs.

---

## 7. Git topology + reconciliation (read before pushing ANYTHING)

As of 2026-07-22 ~02:45 local:

| ref | state |
|---|---|
| `claude/refactor-agent-zero-applicant-xn7xoc` (local) | tip `21470f8f2` — ALL program work; 307 ahead of its origin copy |
| `main` (local) | `4257ded85` — 192 ahead / 1 behind `origin/main`; branch is 121 ahead of it |
| `origin/main` | `910b281d8` — has 1 commit local main lacks; NOT an ancestor of the branch (diverged) |
| `upstream` | `agent0ai/agent-zero` — for future A0-release reconciliation into the fork |

- **No credentials exist in the container or host shells to push** (deliberate). Pushes/API commits
  go through A0's github MCP on explicit owner instruction only.
- Reconciliation order when the owner wants it: (1) land the branch → local `main` (merge —
  **never `git reset --hard`**; prefer `--ff-only` where possible), (2) reconcile the 1
  divergent `origin/main` commit, (3) push. Review the 307-commit delta before any public push.
- The recent-history commits that matter for review: `e70891408` (api-prefix, 38 files),
  `51e61dad4` + `16c20d84b` + `21470f8f2` (null-safety), `3ca6dad76`/`8882eb57a`/`06bda0eb3`/`4130aa3bb`
  (modal-init, ~30 files), `0f2a95db9` (gate-test fix), `86d237699` (+x restore).

---

## 8. Backlog state (38 open)

- **Now unblocked by §5 (former browser-deployment blocker):** the ~13 panel issues
  (az-2 #833–837 remnants, az-3 #839–845 remnants, AZ1-3 #831) and, downstream of them, the AZ5
  gates (#851–853 remnants), AZ6 release-eng (#854–859), AZ7 lanes (#860–863).
  #854 ("adapt playtest to A0 shell") is effectively DONE in spirit by `journey_via_sidebar.py` —
  fold that script in and close.
- **Deferred pending owner decisions:** Applicant assistant persona (`agents/applicant/`) — unblocks
  #837/#851/#852; Portal #833; visual identity #847; upstream cherry-pick drill #848.
- **Owner/business:** ToS #672, pricing/cohort/launch #698–708, key-rotation #718, license #722,
  #716/#717 last. Plus ops-tail P-issues #654/#684/#686/#703 and #681 (docs close-out, needs Actions
  API). #145/#685 blocked on #841/#723.
- Full per-issue reasons: session scratchpad `deferred.tsv`.
- **Never touch:** #671, #672, #698–700, #706–708, #716–718, #722 (owner-held).

---

## 9. Hard-won gotchas (cumulative — the ones that cost hours)

1. `x-show` hides, it does not gate evaluation — x-data fields must init to their empty shape (§4.3).
2. Plugin APIs live at `/api/plugins/<plugin>/<handler>`; bare `/api/<name>` = built-ins only (§4.2).
3. Shell modals run inline module scripts async — Alpine registration must be sync + IIFE (§4.1).
4. `callJsonApi` **throws** on error (`api.js:44`); guards must try/catch, an `else` never runs (§4.4).
5. Built-in `/a0/api/health.py` shadows the plugin's health handler — test with a handler that has no
   built-in namesake (§4.2).
6. Test imports with `/opt/venv-a0/bin/python`, never system python3 (§4.2).
7. Standalone-render harnesses cannot see shell-timing bugs; the sidebar journey crawl can (§4.4).
8. A crawl against a still-booting instance reports 0/0 CLEAN — always gate on `/login` → 200 (§5.2).
9. `sudo docker exec` in detached shells fails silently — plain `docker exec` (§6.1).
10. Heredoc-fed container python can silently no-op — file + `docker cp` + verify effects (§6.3).
11. A0 rewrites can drop +x bits (§6.3).
12. GraphQL vs REST rate-limit clocks are separate (§2a).
13. Fork files are root-owned on the host — all repo IO via `docker exec` (§1).
14. Env vars override `.env` (`get_dotenv_value` = `os.getenv`) — that's how test instances get known
    creds without touching secrets (§5.2).
15. GPU% alone lies about drive progress — diff message mtimes + file sets over time (§6.2).
16. The 2 baseline test failures are the ONLY allowed ones — never fix, never count (§6.1).
17. Keys pasted in any chat this program should be rotated; Claude never handles credentials (§2c/2d).

---

## 10. Recommended next sequence

1. **Roll production:** rebuild + `up -d --no-deps a0` (§5.3), journey-crawl :8090 to confirm.
2. **Close the journey-arc issues** via A0's github MCP: the panel issues proven clean in §4.4,
   plus fold `journey_via_sidebar.py` into #854 and close it.
3. **Resume the backlog pipeline** (§6.1) on the now-unblocked chains: remaining az-2/az-3 remnants →
   AZ5 gates → AZ6 release-eng → AZ7 lanes. Cost-route scoping; serial dispatch; browser-verify visuals.
4. **Owner unlocks in parallel** (§2): companion first-run, creds via Connections UI, LLM key
   placement, business decisions.
5. **Reconciliation + ship** (§7 order, owner-supervised): branch → main → push; then #857 front-door
   retirement + #858 workspace migration execution with sign-off.

---

## 11. Spec-pilot lineage & two-stream reconciliation (added 2026-07-22)

> §1–§10 were written by the **build stream** (the Claude session that drives A0 to write Applicant
> code). This section is added by the **spec stream** (the Claude session that authored the spec,
> decisions, and backlog, and merged them to `main`). It exists because the single biggest source of
> confusion in this program is that **two Claude sessions share the branch *name* but not the *work***.
> Read this before trusting any "PR is idle / no activity" signal.

### 11.1 The two Claude streams — do not conflate (this is the #1 confusion)

| Stream | What it did | Where its output lives |
|---|---|---|
| **Spec stream** (this section's author) | Authored the strategy + product spec; recorded 26 owner decisions; filed the 60-issue backlog; merged the spec docs to `main` via PRs #822 and #864. **Wrote no build code.** | `origin/main` (durable, reviewed) |
| **Build stream** (author of §1–§10) | Drove A0 (the coder at :5080) to build the port, closed ~25 issues with real commits, found/fixed the three journey bugs (§4), authored FR-INTEL (#865–871), wrote this HANDOFF. | **local unpushed branch** in the A0 container (`21470f8f2`, 307 ahead — see §7) |

Both use the branch name `claude/refactor-agent-zero-applicant-xn7xoc`, but on **different checkouts**:
- the **build** is the local branch inside `agent-zero` (`/a0/usr/projects/applicant`), never pushed;
- **`origin/claude/refactor-agent-zero-applicant-xn7xoc`** (tip `13fbb71`) holds **only the spec
  stream's 2 housekeeping commits** — it is *not* the build.

**Correction of record (so no one repeats it):** the spec stream spent ~3 days polling **origin PR
#864** and reported it "idle" ~25 times while the build was in fact progressing on the **local**
branch. Origin never saw the build (no push creds, §7). **To gauge build progress, read the closed
issues' completion notes and the container's local branch — never an origin PR.** #822/#864 carried
**docs only** (verified: `3b83ed7` = 2 files); neither merged any build code to `main`.

### 11.2 What is durably on `origin/main` (the reviewed spec — the build stream's map)

- **#822 (`910b281`)** — the four strategy docs the whole build follows:
  `docs/agent-zero-plane-map.md` (architecture, the safety line, updateability discipline),
  `docs/backlog/agent-zero-port.md` (parity matrix + phases **AZ-0…AZ-7 + AZ-R**, 41 stories,
  decisions **D1–D26**), `docs/design/agent-zero-user-journey.md` (rebrand, guided setup,
  notifications, integrations, interactability, the instructions gate),
  `docs/backlog/az0-kickoff-prompt.md` (the coding-agent kickoff contract).
- **#864 (`3b83ed7`)** — D22 revision (spec-first merge) + kickoff re-point.
- **`8e11153`** — this HANDOFF (build stream).
- The build itself (`agent-zero/` subtree, `a0-applicant/`, `a0-webui/`, `branding/`) is **NOT on
  `origin/main`** — it is the 307-commit local branch (§7).

### 11.3 The decision record (D1–D26) — all owner-decided; full table in `docs/backlog/agent-zero-port.md` §5

Load-bearing ones the build must not silently drift from: **D1** bespoke UI (managed `a0-webui/`
fork; framework subtree byte-pristine) · **D2** A0 collects the model, syncs to engine; engine keeps
the tier ladder · **D3/D9** companion services now, MCP-lane convergence committed as **AZ-7** ·
**D4** single-user + login · **D5** engine notification ladder authoritative · **D6** both Applicant
artifacts out-of-tree, applied at build · **D7** front-door retires at the ship gate (no dual-UI) ·
**D8** one unified chat · **D10** ntfy opt-in push · **D11** all three model-connect forks · **D12**
curated default + power-tools toggle · **D13** new visual identity, owner-approved · **D14**
"Applicant", warm-professional · **D15** full workspace-data migration (per-entity matrix;
engine-owned state never migrates) · **D16** VM grows · **D17** A0 stock autonomy (makes AZ5-1 the
load-bearing control) · **D18** Discord stays first-class · **D19** memory routed by content
(job facts → engine mind via curation gate) · **D20** owner dogfoods from AZ-2 · **D21** ships as
Applicant 2.0 · **D22** spec-first merge (revised) · **D23** accept A0's disk-trust secret posture,
documented · **D24** English-only, i18n-ready · **D25** soft spend budget · **D26** upstream release
tags, on-demand sync.

### 11.4 Backlog audit reconciliation (2026-07-22, cross-checked against GitHub)

- **38 open · 30 az-port closed** (verified via the issues API). The build stream closed all of
  **AZ-0** (#823–828, incl. the #828 seam gate), **AZ-1** (#829–832 + the FR-INTEL suite #865–871),
  most of **AZ-2** (#834–836,838), most of **AZ-3** (#839,841–845), **AZ-4** (#849,850), **AZR-1**
  (#846), and the real deploy bug it found and fixed (#872, the `fastapi_mcp` API-mismatch that had
  blocked the seam).
- **Still open** (the build stream's §8 is the authority on why): AZ1-3 #831, AZ2-1/2-5 remnants
  (#833,837), AZ3-2 #840, AZR-2/3 (#847,848), AZ5 gates (#851–853), AZ6 (#854–859), AZ7 (#860–863),
  plus the retained road-to-market track (#654,671,672,681,684–686,698–708,716–718,722) and #145.
- **Dedupes the unification caught, still valid:** AZ4-3 → superseded by **AZ7-2 #861**;
  **AZ6-5 = #671** (the existing PAG-1 gate, not duplicated).
- **FR-INTEL provenance:** #865–871 were authored **by the build stream mid-build** (not in the
  original #822 spec) — the local↔cloud model-routing doctrine that keeps paid tokens for judgment
  and free local Qwen for typing (spec: `docs/backlog/az-port-intelligence-routing.md`). Treat that
  doc as a first-class spec addendum alongside the #822 set.

### 11.5 Safety-line status (the product's identity — verify it never regresses)

- **Verified:** the #828 seam-proof passed live — the engine's MCP surface refuses a consequential
  submit **server-side** even to the A0 agent. "The autopilot that can't fire itself" holds across
  the shell boundary at the MCP layer.
- **Outstanding hard gate:** **AZ5-1 #851** — the *bypass* negative test (the A0 agent's own
  browser/shell cannot complete a real application *around* the engine). Under **D17** (stock A0
  autonomy) this is the load-bearing control, not optional. It is not yet closed. Ship (AZ-6) does
  not happen before it, AZ5-3 (H1–H5 re-audit #853), and PAG-1 (#671) are green.

### 11.6 If you are picking this up cold — the one-paragraph orientation

The spec is on `origin/main` (§11.2). The build is functionally done and browser-verified but lives
on an **unpushed local branch** (§7) and is **not** on `origin/main`; reconciliation is a deliberate,
owner-supervised step. Progress is tracked by **closed issues + their commit-cited completion notes**,
not by any origin PR. The piloting model is **Claude specs/verifies/steers, A0 writes the code**
(§6). The remaining work is the still-open chains in §11.4 (drive via §6.1), the owner unlocks (§2),
and — before any launch — the AZ5-1 bypass test, the H1–H5 re-audit, and PAG-1 (§11.5).
