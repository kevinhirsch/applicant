# Known issues — living bug log

Every bug/finding observed during validation that is **not being actively fixed in an
open PR** is recorded here so nothing is lost in an agent transcript. When a finding is
fixed, it moves to "Resolved" with its PR. Status legend:

- **OPEN** — real defect, not yet fixed; needs a fix PR.
- **PRODUCT-DECISION** — a spec/behavior that's contradictory or out-of-design; needs the owner to decide.
- **DEPLOY-GATED** — cannot be validated in the hermetic/sandbox lane; verify under `docs/production-smoke.md` (`compose up --build`).
- **INFRA** — a limitation of this sandbox (no Docker daemon / blocked egress), not a product bug.
- **RESOLVED** — fixed; PR linked.

> Source tags reference the validation pass that found it (live core-validation, browser-prefill,
> spec-categorization, the gap-closer agents G1–G6, etc.).

> **Companion log.** Bugs found incidentally while sweeping the 12-lens UX-hardening backlog
> live in [design/audits/discovered-issues.md](design/audits/discovered-issues.md) (the "DISC"
> ledger), and per-lens backlog status in
> [design/audits/exhaustive2/CLOSURE-STATUS.md](design/audits/exhaustive2/CLOSURE-STATUS.md).
> Notifier-adapter correctness fixes (dedup/re-fire, ntfy reach/preempt) shipped in **PR #626**;
> the cross-user isolation thread (owner-scoping the front-door proxies on reads **and** writes)
> closed in **#626/#629/#630**. Note K5 (ntfy not front-door-configurable) remains OPEN — that
> is the config-thread-through, distinct from the adapter fixes.

---

## OPEN (real defects awaiting a fix)

| # | Severity | Finding | Where | Source |
|---|---|---|---|---|
| K1 | LOW (test-harness) | Camoufox and chromium cannot co-reside in one Playwright process — the module-level `_camoufox_launchable()` probe launches Camoufox at collection, poisoning the shared driver so the next chromium `launch_persistent_context` dies ("Target/context closed / Missing X server"). Causes ~3–4 spurious failures on an unguarded full-file run of the real-browser tests. Both engines work standalone. | `tests/integration/test_real_browser.py` (module-level probe) | browser-prefill validation |
| K2 | HIGH (resilience) | After a transient Postgres blip, boot-Session-bound gate services stay stuck at HTTP 500 (`PendingRollbackError: can't reconnect until invalid transaction is rolled back`) until an engine **restart** — blast radius ~25 `require_llm_configured`-gated routers. Route-handler storage is per-request and recovers; the gate dependency is not. Not data-loss (restart-recoverable), but a transient DB hiccup shouldn't need a restart. Fix: per-request/short-lived session for these reads, or rollback-and-retry in `app_config_store.get/set`, or `pool_pre_ping=True`. | `app/deps.py:296-301`; `app/container.py:425-426,:203`; `adapters/storage/app_config_store.py` | resilience injection (G6) |
| K4 | HIGH (deploy config) | Live SearXNG discovery silently yields **zero postings** in prod — the `searxng` service has no `volumes:` mount for its settings file, and `searxng/searxng:latest` disables `?format=json` by default (answers 403/HTML). The correct settings (`formats: [html, json]` + secret) exist at `workspace/config/searxng/settings.yml` but aren't mounted, and `secret_key` is still the `__SEARXNG_SECRET__` placeholder. Graceful (logs `searxng_json_disabled`, returns `[]`) — but one of the two discovery sources is dead. jobspy/RSS unaffected. Fix: mount that settings.yml into the prod `searxng` service + substitute the secret. | `docker/docker-compose.prod.yml` `searxng` service (~:262-274); `workspace/config/searxng/settings.yml` | discovery/ATS validation (G4) |
| K5 | MEDIUM (reachability) | **ntfy is not configurable from the front-door** (principle #2 unmet): `ChannelsIn` has no `ntfy_url` field in the proxy or engine, `configure_channels` forwards only discord+apprise+email and drops ntfy, and the wizard JS submits only `discord_webhook_url`+`apprise_urls`. ntfy works in the adapter but is settable **only** via the `NTFY_URL` boot env var — no Settings field, no "Send a test". Discord + email ARE fully UI-configurable + testable. Fix: thread an `ntfy_url` field through wizard JS → proxy → engine `configure_channels`. | `workspace/routes/applicant_setup_routes.py:123`; `app/routers/setup.py:49,237-241`; `workspace/static/js/applicantOnboarding.js:544` | notifications validation (G2) |
| K6 | LOW (UX honesty) | When `NOTIFICATIONS_LIVE` is unset (off), the Settings "Send a test" returns `{"sent":true}` while **nothing actually sends** (in-memory no-op) — no UI signal it's a dry run. Prod compose defaults `NOTIFICATIONS_LIVE=true` so a real Compose deploy is fine; bites bare-uvicorn / dev runs. Fix: surface live-vs-dry-run state in the test response/UI. | `app/routers/setup.py` test endpoint; `adapters/notification/apprise_notifier.py` | notifications validation (G2) |
| K7 | LOW (deps) | Two `pip-audit` advisories are **not reachable-and-high** in this deployment but the version bumps are deferred: `langsmith` < 0.8.18 (file read via `TracingMiddleware` — the middleware is never constructed; langsmith is an unused transitive dep of langgraph) and `markdownify` < 0.14.1 (memory-DoS via `<h999…>` — reachable only through a crafted job-board page, CVSS 3.1). Deferred because re-locking with a uv version other than the repo's pinned one (CI `setup-uv` v5.4.2 / the Docker digest) re-resolves the `webarena-verified` URL dep and churns ~760 lines, dropping the `eval` extra. Fix: bump both in a deliberate lockfile-maintenance pass **using the pinned uv**. The reachable `lxml` XXE was fixed at the boundary instead (P2-3, `docs/security-review.md`). | `uv.lock`; `docs/security-review.md` | security pass (P2-3) |
| K8 | MEDIUM (resilience, DBOS backend only) | **Hand-off resume is structurally unavailable on the optional `ORCHESTRATOR_BACKEND=dbos` path.** Two layers: (a) `DbosOrchestrator` exposes no `clear`, so the run loop's checkpoint-clear-on-handoff is a (now loud, no longer silent) no-op there — mitigated backend-agnostically: `run_pipeline` re-reads the persisted §7 state (`PipelineContext.persisted_state`) whenever the checkpointed prefill step serves a cached hand-off, so a stale step checkpoint alone can no longer lock an application at the wall (hermetic regression: `test_p2_12_durability_drills.py::TestDrillHandoffWithoutClear`). (b) UNMITIGATED residual: a pipeline pass that RETURNS a hand-off result is a COMPLETED workflow in DBOS terms, and DBOS returns a completed workflow's cached result on a same-id re-drive **without re-executing the body at all** — so the mitigation in (a) never runs on DBOS re-drives. Fixing (b) needs per-attempt workflow executions (a persisted attempt id per application) — its own story. Not reachable on the default shim backend, which is the only lane hand-off recovery is proven on (`@pytest.mark.integration` covers DBOS basics only). | `adapters/orchestration/dbos_orchestrator.py` (module docstring documents it); `application/workflows/application_pipeline.py`; `application/services/agent_loop.py::_clear_checkpoint` | Greptile P1 on PR #767 (P2-12) |
| K9 | HIGH (CI/runner infra) | **The self-hosted Integration Lane runner is online but cannot start the lane's Postgres service container.** Confirmed via the GitHub Actions API (read-only — no dispatch permission from this session, see below): runner `ubnthost01-applicant` (id 21, `Default` group, label `self-hosted`) picks up both prior scheduled runs (2026-06-28 run #1, 2026-07-05 run #2) within seconds of the cron firing, but each fails at the **"Initialize containers"** step — the runner's own `docker version` check reports `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`. Every following step (TeX verify, browser install, Alembic, the `-m integration` suite itself) is then skipped; only the `if: always()` steps (artifact upload, the ATS dry-run summary, which trivially reports "no URL provided") run and report green, so the run's overall red conclusion is the only visible signal — nothing in the four deploy-box legs (P1-2/P1-7/P2-10/P2-13) has ever actually executed on this runner. Root cause: the runner service's OS user is not a member of the host's `docker` group (`usermod -aG docker <runner-user>` + a runner-service restart, or restart the whole runner host, is the fix — needs the runner host operator, not a code change). This also blocks the new `destroy-drill` job added for P1-7 (workflow PR: `claude/integration-lane-live-legs`) and the `install-uninstall-drill` job added for P3-1 (`claude/p3-1-install-targets`), both of which need Docker identically. | Runner host `ubnthost01` (`ubnthost01-applicant`, self-hosted); `.github/workflows/ci-integration.yml` `services.postgres` | read-only Actions-API audit of runs #28313417474 (2026-06-28) and #28731310457 (2026-07-05), job id 85197302278 |

_(gap-closer agents G1–G5 still running; their report-only findings — résumé render, notifications, pristine OOBE, discovery/ATS, deploy review — get appended here as they land.)_

> **Validation caveat (process):** the shared local working checkout at `/home/user/applicant` is
> periodically contaminated by builder worktree-bleed, and the live `:7000` front-door serves files
> from it per request — so a re-audit against the live stack can surface **phantom regressions** that
> are NOT on `origin/main`. A re-audit on 2026-06-30 reported a `focusLibrary` boot-blocker + "Ithaca"
> persona leaks + a lost white-label test; **all three were verified ABSENT on clean `origin/main`** —
> they were the dirty checkout, not the shipping branch. The post-wave re-audit must run from a fresh
> clean checkout, not the bled live stack.

---

## PRODUCT-DECISION (spec contradictions / out-of-design — owner must decide)

| # | Finding | Detail |
|---|---|---|
| P1 | Spec `#343` combobox shared-prefix filter is self-contradictory | Its `@pending` AC requires `_filter_query("United States Minor Outlying Islands")` to return **>2 words**, but a sibling **non-retired** regression scenario pins the **same call** to **exactly** "United States" (2 words). Unsatisfiable by one deterministic method. Left `@pending`. Decide which expectation wins. |
| P2 | Per-board rate-limiting spec (`enh_195`) has no seam | No per-source pacing seam exists; only a campaign-level cap ships. Building a new `source_pacing` rule is net-new scope — confirm in-scope or `@skip`. |
| P3 | Dead-code "today" probes are contradictory by design | Specs asserting the *current* duplicated/orphaned state (byte-identical search files, duplicated fetch/esc/toast helpers, one-shot cleanup targets) flip to fail once their sibling "cleaned" specs are implemented. The "today" probe must be retired in the same PR as the cleanup. |
| P4 | Doc-sync specs will re-drift | `README describes the 3-step OOBE` and `documented skip-count matches the real integration suite` are hardcoded assertions that drift unless computed. Decide: compute them, or accept periodic updates. |

---

## DEPLOY-GATED (cannot pass hermetically — verify at `compose up --build`)

These are honest "the deployed image needs this dependency" signals, **not** bench bugs. They
must NOT be forced green in CI. Verified via `docs/production-smoke.md` on a Docker host.

| # | Finding |
|---|---|
| D1 | CUA driver-schema reconcile (`#142`), engine↔workspace bridge round-trip / curation-persist (`#145`), desktop-assist-operable health (`#179`) — need the real `cua-driver` image + a live workspace. |
| D2 | Font-embedded real PDF résumé render (`#2` gap) — needs TeX baked in the image (sandbox shows `tex: NOT FOUND → stub PDF`). |
| D3 | Startup capability report "real vs stubbed", CI hosted-fallback/JS-test runner, seeded-E2E + migration-data-integrity harnesses — need the built image / CI runner. |
| D4 | `patchright install chromium` (added to `docker/Dockerfile` in #550) downloading + the chromium engine launching without falling back to plain playwright — first exercised at image build. |
| D5 | ~~Credential keyfile persistence / `update.sh` rollback / bridge over service-DNS~~ — **REVIEWED CLEAN (G5 deploy review)**: keyfile is on the `secrets` named volume and only created when absent (no regen on rebuild); `update.sh` backs up before migrate, auto-restores + refuses to serve on migration failure, `--rollback` reverts code+images+DB; bridge uses `api:8000`/`applicant-ui:7000` + a shared token minted once + healthcheck ordering. Image layers (TeX/LibreOffice/real-Chrome/camoufox/Xvfb, non-root) all baked. Still verify live via `docs/production-smoke.md`, but no static defect found. |

---

## INFRA (sandbox limitation, not a product bug)

| # | Finding |
|---|---|
| I1 | Live job discovery (jobspy / SearXNG) can't run here — outbound egress is blocked, so real-posting discovery → scoring → digest has only been exercised with seeded/mock-shaped data. Needs the `searxng` service + egress on the deploy. |
| I2 | No Docker daemon in the sandbox → the image build + the full Compose stack (searxng/chromadb/ntfy/takeover) are first exercised at deploy. |

---

## RESOLVED (fixed this session)

| Finding | PR |
|---|---|
| **`compose up` aborted at chromadb** — the unpinned `chromadb/chroma:latest` pulled Chroma 1.x, whose minimal image has no `python`/`curl`/`wget`, so the python-based heartbeat healthcheck failed exit-127 forever (`unhealthy`) and blocked the whole stack even though the server was serving. 1.x also persists to `/data`, not the mounted `/chroma/chroma`, so vectors weren't durable. Fixed: pinned `chromadb/chroma:1.0.21` (prod + workspace compose), moved the volume to `/data`, and dropped the impossible in-container healthcheck for a `service_started` gate (the RAG client retries). | (this PR) |
| `scored` audit events persisted with NULL `campaign_id` → invisible to campaign-scoped export | #550 |
| `browser` extra's `patchright` resolved to the non-importable `0.0.1` name-squatter stub (chromium stealth silently degraded); chromium binary-rev mismatch | #550 |
| Chat couldn't converse — boot-time LLM adapter never reloaded after a runtime model-connect; `max_tokens=256` starved reasoning models | #543 |
| 409 setup-gates mislabeled "engine offline" across Portal/Activity/Ops; chat proxy dropped `control_actions` | #544 |
| Front-door white-label runtime regression (vendored tools re-shown by `applyUIVis`); Portal had no sidebar door; dead-but-enabled nav; persona leaks | #542, #546 |
| Front-door boot-blockers (search-package SyntaxError, `/api/applicant/features` 401→login loop, `focusLibrary` ReferenceError) | #539 |
| **K3** (was OPEN) — a pre-fill landing the §7 TERMINAL `FAILED` state (e.g. a crashed browser tab mid-walk, #207/#336) fell through the durable pipeline into material generation + a final-approval request for an application that had already died, instead of stopping. Contrary to K3's original note, the sandbox slot **did** leak (`yield_for_block` only releases on a `_YIELDING_STATES` member, and `FAILED` is not one — confirmed by a P2-12 durability drill: after a simulated browser crash, a second application could never be admitted to the single sandbox slot). Fixed: `run_pipeline` now stops (`status="failed"`) the moment pre-fill reports a `TERMINAL_STATES` member, reusing the existing `core/state_machine.TERMINAL_STATES` set; `AgentLoop._apply_outcome` releases the slot + clears the checkpoint on that outcome exactly like `done`. | P2-12 (this PR) |
| **Stale-checkpoint hand-off lockout** (found by a P2-12 durability drill, not previously tracked) — once the durable "prefill" step checkpointed a BLOCKED_*/AWAITING_ACCOUNT_HUMAN_STEP/EMERGENCY_DATA_HANDOFF hand-off, `run_step` never re-ran it: EVERY later re-drive of that application (whether the scheduler's per-tick resume or a boot-time restart recovery) replayed the stale cached hand-off forever, so the application could never advance even after the human resolved the block (proved: a `BLOCKED_MISSING_ATTR` app stayed stuck across 3 ticks in the drill). Fixed: `AgentLoop._apply_outcome` clears the workflow's checkpoint when a pure pre-fill hand-off lands (NOT for `MATERIAL_REVIEW`, which intentionally stays cached, #1), so the next drive re-enters `_prefill()` and picks the right `resume_after_*` entry point (#4). | P2-12 (this PR) |
