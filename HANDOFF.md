# Applicant 2.0 — Handoff

> The port of the Applicant engine onto the Agent Zero (A0) shell. This document is the single
> pick-up point: current state, what's blocked on whom, turnkey runbooks, architecture, ops tooling,
> and the hard-won gotchas. Written 2026-07-21.

---

## TL;DR

Applicant 2.0 is **functionally built and validated against the live engine.** The A0-shell surface
layer (35 panels), the intelligence-routing config, ship tooling, and the mock data-lane basis are all
in and green. **Completing it is now ~90% three unlocks only you can provide** — not more coding:

1. **`GITHUB_TOKEN`** → close the ~21 verified-done issues (the only thing that drops the open count).
2. **`API_KEY_OTHER` (+ engine `LLM_API_KEY`)** → wake A0's cloud tier *and* the engine's Plane-B LLM.
3. **Mailbox/calendar credentials** → the real email/calendar lanes (a mock basis already exists).

Everything else is either gated on those, owned by you (business/legal), or minor polish.

**Verification (2026-07-21):** unit suite **7895 passed** at the known 2-failure baseline
(`test_prod_compose_env_file` + `test_deploy_hardening_lens04` — the ONLY allowed failures, pre-existing);
integration **42 passed + 11 cleanly skipped** (the skips are the companion-gated lane-regression tests);
**39/39 a0-applicant panels render clean in a real browser** (Playwright). Branch:
`claude/refactor-agent-zero-applicant-xn7xoc` (local only — never pushed).

---

## 1. The three unlocks (critical path) — turnkey runbooks

### 1a. `GITHUB_TOKEN` → close the done issues
- **Rotate** your PAT first, then `export GITHUB_TOKEN=<rotated>`.
- **Turnkey:** `~/agent-zero-ops/close-done-issues.sh` — dry-run by default (prints exactly what it would
  do); `close-done-issues.sh --confirm` posts an evidence comment + closes all **21** verified-done issues
  (list + evidence baked into the script; mapped by DELIVERABLE since the FR-INTEL commit #s were scrambled).
- Underlying tool: `~/agent-zero-ops/gh-issue.py` (reads `GITHUB_TOKEN`/`GH_TOKEN` from env only; never prints secrets).
- The close-ready list is in §3. (#838/#839/#842 are near-close-ready — NOT in the auto-close set; they have
  deferred sub-items, so review + close those individually once the cloud coder finishes them.)

### 1b. LLM key → engine Plane-B **and** A0's cloud coder (ONE key, two places)
Both are OpenAI-compatible; use the rotated DeepSeek key.
- **Engine (Plane B — material generation, curation, mind bridge):** `LLM_PROVIDER=openai`
  `LLM_BASE_URL=https://api.deepseek.com/v1` `LLM_MODEL=deepseek-chat` `LLM_API_KEY=<key>`.
  **⚠️ Do NOT put these in the repo root `.env`** — the pytest suite loads it via pydantic Settings and
  the `llm_configured` tests break (20 failures, seen 2026-07-21). Inject them into the **engine
  CONTAINER** instead: add them to the `api` service's `environment:` in `docker/docker-compose.yml`
  (which currently uses inline env, not `env_file`), or a container-only env file, and also add
  `secrets/` to `.dockerignore` (root-owned → breaks the build context). Then recreate `docker-api-1`.
  Plane B is only needed for #145 / live material generation — not for the shell or the cloud coder.
- **A0's cloud coder/overseer — ACTIVATED 2026-07-21 (was the cause of all-session local grinding).**
  A0's LIVE model config had every agent on `{"model_preset":"Default"}` (local Qwen) — the FR-INTEL
  topology was only a repo spec, never applied to A0. Fix (all `.bak`-backed): (1) `API_KEY_OTHER=<key>`
  in `/a0/usr/.env`; (2) `/a0/usr/plugins/_model_config/config.json` → `{"model_preset":"DeepSeek-Chat"}`
  (overseer); (3) `/a0/usr/agents/coder/plugins/_model_config/config.json` → `{"model_preset":"DeepSeek-Flash"}`;
  (4) `docker restart agent-zero`. VERIFIED: GPU stays 0% while drives progress = cloud. Panels now land
  in ONE clean drive (the automation-prefs panel that stalled twice on local built in one cloud drive).
  **LESSON: keep A0's live `_model_config` in sync with the repo topology spec.** Revert to local:
  restore the `.bak-pre-cloud*` files + restart.
- **Why it matters:** the local Qwen-27B converges on small/contract units but **over-explores and
  grinds/stalls on multi-file panel work** (multiple incidents this session — one file took 64 min).
  The cloud key is *the* accelerator for all remaining panel/gap-fill work.

### 1c. Mailbox/calendar creds → the real lanes
- A **mock backend already exists** (`src/applicant/adapters/workspace/mock_workspace_client.py`,
  toggle `LANE_BACKEND=mock`) with fixture rejection/interview/offer emails + a fake calendar (read +
  write-back + de-dup). Lane logic is real and testable **without creds** (see `tests/unit/test_lane_mock_backend.py`).
- **Real Gmail** (docs: `docs/backlog/lane-mock-and-real-creds.md`): IMAP app-password + `imap.gmail.com:993`
  / SMTP `smtp.gmail.com:587`; Google Calendar via CalDAV/OAuth. Configure on the **companion** (it owns
  the IMAP/CalDAV clients; the engine reaches it over the internal-token channel). The same lane code +
  tests then run against the real backend.
- **Companion onboarding:** the companion (`docker-companion-1`) is up but its API returns 401 /
  "Setup required" — it needs a first-run account/login before its memory substrate (the mind bridge,
  #145) is usable. That account step is **yours** (Claude is prohibited from creating accounts / entering passwords/keys).

---

## 2. Architecture — the running stack

```
                         HOST (docker, network: docker_default)
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  docker-api-1 (ENGINE :8000)  ── MIND_BACKEND=bridge ─┐                    │
  │     Plane B LLM (needs LLM_API_KEY)                   │ internal-token     │
  │     /api/campaigns,/api/tracker,/api/setup/*,...      │ /api/applicant/    │
  │        ▲                                              ▼ internal/*         │
  │        │ ENGINE_URL=http://api:8000        docker-companion-1 (:7000)      │
  │        │ (resolves only if A0 is on             workspace/mailbox/caldav   │
  │        │  docker_default — ensure-engine-net.sh)     "Setup required" 401  │
  │  docker-postgres-1   docker-chromadb-1   docker-searxng-1                  │
  └────────┼───────────────────────────────────────────────────────────────┬─┘
           │ (a0-applicant proxies forward here)                            │
  ┌────────┼──────────────────────────────┐              lanes: engine ──► companion
  │  agent-zero container (A0 SHELL :80)   │              (email/calendar/research)
  │   35 a0-applicant panels ◄─callJsonApi─┤              mock: LANE_BACKEND=mock
  │   overseer agent0 + coders (Qwen local │              real: mailbox/caldav creds
  │     until API_KEY_OTHER → DeepSeek cloud)              (companion-side, yours)
  └────────────────────────────────────────┘
```


**Two model planes (FR-INTEL suite defines them, all as version-controlled contracts under `config/`):**
- **Plane A — shell/agent models:** A0's overseer + workers. 9 profiles → 3 tiers
  (`config/intel_tiers.yaml`): agent0/reviewer/security/*-cloud → cloud-flash; coder/explorer/test-engineer
  → local-fast; debugger → cloud-pro. Governed by `config/intel_{envelope,routing,escalation,orchestration,sampling,planes}.yaml`.
- **Plane B — engine LLM calls:** parse-verify, tailoring, screening, viability_scoring. Engine tier-ladder.
- Disjoint ownership is pinned in `config/intel_planes.yaml`.

**The running containers (host, `docker/docker-compose.yml`, network `docker_default`):**
`docker-api-1` (engine, :8000, healthy), `docker-companion-1` (workspace/companion, :7000), `docker-postgres-1`,
`docker-chromadb-1`, `docker-searxng-1`. Engine is pre-wired for the bridge (`MIND_BACKEND=bridge`,
`APPLICANT_INTERNAL_TOKEN`, `WORKSPACE_URL=http://companion:7000`).

**A0 shell** runs in the `agent-zero` container on port 80, serving the a0-applicant panels
(`window.openModal('/plugins/applicant/webui/<panel>.html')`).

**Critical wiring (do NOT lose):** the a0-applicant proxies default to `ENGINE_URL=http://api:8000`,
which only resolves if `agent-zero` is on the `docker_default` network. This was fixed with
`docker network connect docker_default agent-zero` (survives restart, NOT container recreation).
Re-establish after any A0 recreation with **`~/agent-zero-ops/ensure-engine-net.sh`** (idempotent).
Alternatively set `ENGINE_URL=http://172.17.0.1:8000` (docker0 bridge). With this, proxies hit the
real engine — verified: `campaigns.list`/`tracker.board` → 200 with live data; all 35 panels function against it.

---

## 3. What's built + verified — CLOSE-READY the moment the token is set (~21)

- **FR-INTEL suite (7):** #865 #866 #867 #868 #869 #870 #871 — intelligence-routing/tiering contracts
  (`config/intel_*.yaml` + `src/applicant/ports/intel/{envelope,routing}.py`), byte-verified vs the
  reference deployment.
- **Gates (4):** #851 #852 (closed 2 real prompt-injection vulns) #853 #854.
- **Surfaces/tooling (7):** #843 (dormant preservation) #845 (help system A+B) #850 (lane regression tests)
  #856 (traceability gate) #859 (release-readiness gate) #846 (a0-webui build-time overlay) #849 (companion
  headless hardening).
- **Gap-fill (this session) → now CLOSE-READY (3):** #838 (health + global pause), #839 (full settings
  suite: channels/tiers/privacy/automation-prefs panels — the last built on cloud), #842 (vault/easy_apply/
  screening/today/ops/audit-export/save-a-job/shortcuts/interview-prep/demo-data all built; campaign-switcher
  skipped as redundant — 19 panels already have in-body campaign pickers).

Plus infra/quality not tied to a single issue: the **A0-shell playtest harness**
(`scripts/playtest_panels.py`) that renders every panel in a real browser (found + fixed real render
bugs source-asserts missed); the **mock lane backend**; the **real-integration proxy smoke + write-path tests**.

---

## 4. Gated / remaining engineering (built the moment the unlock lands)

- **Needs LLM key (1b):** #145 mind-bridge verification; #839 automation-prefs (15-field form — cloud coder).
- **Needs mailbox/calendar creds (1c):** #844 real config-write + live round-trip; #861 email cutover; #862 calendar cutover.
- **Needs a provider choice + live infra:** #860 MCP-provider adapter (contract slice was attempted); #863 credentials-collapse.
- **Ship-gate + go-ahead:** #857 front-door retirement *execution* (runbook + tested rollback + readiness
  gate are DONE — `docs/ops/front-door-retirement.md`); #858 workspace-migration *execution* (per-entity
  matrix contract is DONE — `config/migration_matrix.yaml`, D15/D19 invariants pinned).
- **Owner/business (yours):** ToS #672, pricing/name/cohort/launch #698–708, key-rotation #718, license #722, deferred #716/#717.
- **Minor polish (low value; save for cloud coder):** #842 shortcuts overlay / demo banner / campaign-switcher-in-headers.

---

## 5. Ops tooling + how to drive A0

Everything lives in `~/agent-zero-ops/`:
- **`az-send.sh "<spec>" "<ctx>"`** — fire a drive to A0 (plain `docker exec -i`, NOT sudo — sudo fails
  silently in detached shells). Spec discipline: keep units SMALL (proxy + panel + 1 test + sidebar =
  reliable; adding help/traceability/playtest to the same drive = grind). Do consistency (traceability
  row + help affordance + help_content entry) as a tiny follow-up drive. Always tell it "you are already
  on the correct branch; ZERO git branch/checkout/switch; only add + commit."
- **`az-rmchat.sh <ctx>`** — remove a drive chat (frees the GPU; orphaned generations drain in ~1 min).
- **`ensure-engine-net.sh`** — re-attach A0 to the engine network (see §2).
- **`gh-issue.py`** — safe issue close/comment (env-token only).
- **Verify visual work yourself:** `PLAYWRIGHT_BROWSERS_PATH=/a0/tmp/playwright FRONTDOOR_URL=http://localhost:80
  /opt/venv-a0/bin/python scripts/playtest_panels.py` → `playtest-panels-results.json`. The project `.venv`
  has NO playwright; A0's `/opt/venv-a0` does.
- **Drive loop:** a `Monitor` on `git for-each-ref refs/heads` (plain `docker exec`) pings on every commit;
  react on commits, not timers. Verify each commit against reality (run its tests + full suite; the local
  overseer's own gate is not trusted). Test runner is `.venv/bin/pytest` (NOT `/opt/venv-a0`).
- **A0 parity patches applied this program** (in `/a0/usr/agents/*/prompts/*` + `_guardrails`, all `.bak`-backed):
  whole-spec delivery, streaming-gate + commit-before-gate, port-from-source, exact-engine-paths,
  no-credential-hunting, no-branch-switching, phantom-0-collect guard, R6/R9 size-route doctrine,
  playtest-verify-visual, destructive-command classifier (blocks git branch ops + `reset --hard`).

---

## 6. Hard-won gotchas / lessons

- **Local Qwen limits:** great on small/contract units; over-explores → grinds/stalls on multi-file panel
  work. Keep drives tiny; the cloud key (1b) is the fix. Liveness ≠ progress: diff msg-mtime + file set +
  bytes over time — GPU% alone lies (a runaway is 100% busy, 0% productive).
- **Worktree-branch confusion:** drives in a git worktree try `git branch/checkout` (blocked by the guard)
  → commit to a DANGLING state or stall. Prefer **single drives on the main tree** for reliability; if you
  must parallelize, cap at ~2–3 and verify each committed to ITS branch. Recover a dangling commit with
  `git checkout <sha> -- <file>` (host-side; the guard doesn't apply to direct docker exec).
- **Source-assert ≠ works:** the playtest caught real JS bugs (undefined `.data`, `const` without
  initializer) that green source-assert tests missed. Playtest every panel.
- **Harness fidelity:** `playtest_panels.py` loads panels standalone, so shell globals (`window.openModal`)
  are stubbed — an unstubbed one is a harness false-positive, not a product bug (investigate before filing).
- **The 2 baseline test failures** (`test_prod_compose_env_file`, `test_deploy_hardening_lens04`) are
  pre-existing and the ONLY allowed failures — never "fix" or count them.
- **Secrets:** never write/echo API keys; the DeepSeek + OpenRouter keys shared in chat this session
  should be rotated. Claude cannot enter keys/passwords/accounts — those steps are yours.

---

## 7. Recommended next sequence

1. Rotate keys → set `GITHUB_TOKEN` (I close ~21) → set `API_KEY_OTHER` + engine `LLM_API_KEY` (unblocks
   cloud coder + Plane B) → onboard the companion → add mailbox/calendar creds.
2. With the cloud coder live: automation-prefs + any minor chrome in single fast drives.
3. With companion + LLM: verify #145 mind bridge; build #844 live + #861/#862 lane cutovers vs the mock→real seam.
4. Business/legal decisions in parallel (yours).
5. Ship: #857 retirement + #858 migration execution with your sign-off.
