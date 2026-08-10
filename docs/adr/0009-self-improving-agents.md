# ADR-0009: Self-improving product — Reflection Coach + Automation Engineer

**Status:** Proposed (grounds `docs/APPLICANT-BACKLOG.md` § EPIC AGENTS).
**Numbering:** next free slot after `docs/adr/0008-autonomous-self-healing.md` in the existing
`docs/adr/0001`–`0008` sequence.
**Extends:** `docs/adr/0008-autonomous-self-healing.md` (EPIC SELF-HEAL). This is not a parallel
architecture — §"Relation to ADR-0008" below maps ADR-0008's detect→remediate loop onto this
ADR's Automation Engineer, and explains why nothing here duplicates a detector or remediator
ADR-0008 already defines.

## Context

Applicant's north star (`docs/APPLICANT-BACKLOG.md` line 3) is a review-ready queue of tailored
applications produced automatically, with no manual babysitting. ADR-0008 covers the product
*not breaking*. EPIC AGENTS covers the next layer: the product **getting better at its job on
its own** — evaluating whether the campaign is actually working, and building/extending itself
when it needs to. Product owner's framing (`docs/APPLICANT-BACKLOG.md` line 47-48, verbatim):

> "Applicant continuously evaluates its own effectiveness and improves itself — extending
> SELF-HEAL from *detect→remediate* to *reflect→strategize* and *build→ship*."

Ten decisions are already made by the product owner (backlog lines 47-68); this ADR designs to
them, it does not re-litigate them. Two in-product agents, built in parallel starting now, with
one responsible gate:

- **Agent A — Reflection Coach (RC):** daily + event-driven re-evaluation of whether the
  campaign is actually getting Kevin hired, faster — not just producing volume — and
  auto-applies transparent, reversible profile/strategy tweaks.
- **Agent B — Automation Engineer (AE):** monitors, fixes, and autonomously builds/extends
  Applicant itself, including deploy, inside a hard safety harness.

**What already exists to build on** (grounded by file — reuse-first per
`docs/APPLICANT-BACKLOG.md` line 13):

- **The exact reversible-tweak mechanism RC needs already ships**:
  `src/applicant/application/services/criteria_service.py`, `CriteriaService.edit_criteria`
  (L44-61) for direct/gated edits and `apply_learned_adjustment` (L66-89) for LLM/learning
  mutations — non-integral deltas auto-apply, integral fields (`titles`/`locations`/
  `salary_floor`, `_INTEGRAL_FIELDS` L26) are staged as a `proposed_integral` learned adjustment
  needing confirmation, and every learned delta lands in `learned_adjustments` (with an
  LLM-or-fallback human-readable summary, `_summarize`) so it is visible and revertible via
  `clear_learned=True`. RC is a **new caller** of this existing seam, not a new mutation path.
- **The scheduled-closed-loop precedent, twice over**:
  `src/applicant/application/services/scheduler.py` (`Scheduler.tick`, driving each active
  campaign's `AgentLoop.tick`, the daily digest, and `NotificationService.advance` off one
  injected clock) and its existing sibling
  `src/applicant/application/services/curation_service.py` (`CurationService` — FR-MIND-7, "the
  scheduled closed learning loop": reviews recent run summaries, **proposes** memory/skill
  updates, **stages** them for approval, deterministic-testable via an injected summarizer,
  cross-tick state held in a process-lived `CurationLedger` never on the instance, FR-MIND-10).
  RC's daily cadence is a **third sibling** of this exact shape; its event-driven cadence
  (rejection / velocity stall / N-apps-sent / fit-trend-shift) is a new detector class emitted
  onto the bus below, consumed the same way.
- **The domain event bus + durable audit trail, already extended once for exactly this
  purpose**: `src/applicant/core/events.py` (`DomainEventBus`, `event_bus`) and
  `src/applicant/application/services/audit_log_service.py` (`_ACTION_MAP`, L46-58). ADR-0008's
  S1 slice (merged, commit `52b3f6c2a`) already added `LocalLlmWedgeDetected` → `"detector_fired"`
  and `RemediationRequested` → `"remediation_requested"` to this exact map
  (`src/applicant/application/services/llm_wedge_detector.py`) — the precedent this ADR follows
  for every new RC/AE event type, not a new bus or store.
- **`RemediationRequested` is already defined as an unconsumed signal** (`core/events.py`
  L157-166): "Purely informational... a separate vLLM-host watchdog is the intended consumer of
  this signal." AE is architecturally that intended consumer for the *build-a-fix* half of that
  signal (§"Relation to ADR-0008" below) — ADR-0008 explicitly deferred this, it did not decide
  against it.
- **The human-alert / oversight channel to extend, not replace**:
  `src/applicant/application/services/notification_service.py`,
  `NotificationService.notify_error(title, body, dedup_key)` (L156-165, IMMEDIATE urgency, FR-
  NOTIF-5) — the fail-safe path AE's proactive-comms requirement (Q7) and RC's transparency
  requirement (Q3) both route through for anything urgent, alongside the existing digest-ready /
  decision-ladder notification kinds already on this service.
- **A precedent for a global automation gate, to model the kill switch on, not reuse
  directly**: the *automated-work gate* (`src/applicant/application/services/agent_loop.py`
  L457, `src/applicant/application/services/scheduler.py` multiple sites, e.g. L79/L94/L194) —
  a real, already-shipped per-campaign kill mechanism (Settings > Automation override,
  `_AUTO_DRAFT_TOP_N_DEFAULT`/`_SCORE_BATCH_PER_TICK_DEFAULT`'s documented "0 is the kill
  switch" convention, `agent_loop.py` L74-87). It gates *campaign* automation (discovery/
  scoring/drafting), not code changes or deploys — Q8's **global** kill switch + **per-action**
  veto for RC/AE is new scope this ADR must build (§Guardrails), following this convention
  rather than inventing a different shape.
- **The updater sidecar + control-plane pattern AE's deploy step extends**:
  `scripts/updater-daemon.sh` + `docker/updater.Dockerfile` — a sidecar holding the host Docker
  socket + bind-mounted repo, driven by a file-based control plane (`request` in,
  `status.json`/`update.log`/`updater.alive` out), today only running the full-stack
  `scripts/update.sh --apply`. ADR-0008 already flagged narrowing this to a single-service
  restart as a genuine new build (its Consequences, Gap 1); AE's deploy harness needs the same
  control-plane *shape* one level up: promote/rollback/snapshot requests, not just restart.
- **A disposable, already-working canary target**: `docker-compose.prod.yml`'s `a0`/`api`
  services plus the documented disposable **`applicant-e2e`** instance (`:8091`,
  `HANDOFF.md` §5.2 — `docker rm -f applicant-e2e; docker run -d --name applicant-e2e -p
  8091:80 --network docker_default ... applicant/a0:latest`, booting in ~20-25s) and the
  production rollout step it feeds (`HANDOFF.md` §5.3, `docker compose ... build a0` then
  `up -d --no-deps a0`). AE's canary-before-promote guardrail is this exact
  build→run-disposable→verify→roll-into-prod sequence, driven by AE instead of by a human typing
  the commands in HANDOFF.md.
- **Verification tooling AE's hard TDD/BDD + monkey-crawl gate reuses directly**:
  `/a0/tmp/journey_via_sidebar.py` (real login, clicks all 21 sidebar launchers, captures
  pageerrors — the "19/20 panels CLEAN" gold-standard check, `HANDOFF.md` §4.4/§5.4) and
  `scripts/monkey_crawl.py` (Playwright crawl, `console.error`/`pageerror`/`requestfailed`/
  HTTP≥400/`RENDER_ERR` regex — already cited by ADR-0008 detector #10 as "offline-only" today).
  Both already run against a disposable instance exactly like `applicant-e2e`; AE's canary layer
  schedules them instead of a human invoking them.
- **The never-auto-submit boundary AE's guardrail must respect, at the architecture level, not
  just by convention**: `src/applicant/application/services/final_approval_service.py`
  (`FinalApprovalService`) — `AWAITING_FINAL_APPROVAL` is a **durable `recv` gate** on the
  `final_approval` topic (`prefill_service.FINAL_APPROVAL_TOPIC`); only a `send` carrying
  `DECISION_SUBMIT_SELF` (the user, via the API) or `DECISION_ENGINE_FINISH` (an explicit
  per-app auto-submit opt-in, RUX-4) unblocks it. There is no code path that submits an
  application without a `send` landing on this topic — AE's own tooling must never be granted
  a caller of that `send`.
- **The vendored coding-stack the epic's Q9 asks to "copy in" is already substantially
  vendored** — not a from-scratch build. `config/intel_tiers.yaml` and
  `config/intel_orchestration.yaml` are a **shipped CONTRACT** (enforced by
  `tests/unit/test_intel_tier_topology.py` / `test_intel_orchestration.py` /
  `test_intel_orchestration_prompt.py` / `test_intel_planes.py`) defining exactly the
  coder/reviewer/debugger roster the backlog asks for: `agent0` (cloud overseer,
  "planner/reviewer, not typist"), `coder`/`explorer`/`test-engineer` (local `Qwen3.6-27B`,
  `local-fast`), `coder-cloud`/`explorer-cloud`/`reviewer`/`security-auditor` (DeepSeek-Flash,
  `cloud-flash`), `debugger` (DeepSeek-Pro, `cloud-pro`). The delegation doctrine ("think here,
  build there") and the R1-R9 remote-only escalation catalog are not just config — they are
  **shipped as agent profiles** at `a0-applicant/agents/{agent0,coder,coder-cloud,explorer,
  explorer-cloud,reviewer,security-auditor,debugger,test-engineer}/` (each with its own
  `plugins/_model_config` and, for `agent0`, the doctrine prompt
  `prompts/agent.system.main.specifics.md`, contract-tested to name all six delegate profiles
  and all nine R-ids). `a0-applicant/` is what `docker/Dockerfile.a0` copies into the product
  image (`/a0/plugins/applicant/`) — so this roster already ships inside Applicant's own shell
  container (`docker-a0-1`, `:8090`), independent of the external pristine A0 install at `:5080`
  that today develops Applicant under Claude's piloting. **What is genuinely missing** (grounded
  by absence, not assumed): no file under `src/applicant/` invokes this roster
  programmatically — `grep -rl "automation_engineer\|reflection_coach" src/` returns nothing,
  and the only consumers of `call_subordinate`/`orchestrate`/the `subagent` tool today are a
  human (or Claude) typing into the `agent0` chat UI. AE needs a callable bridge from a
  `src/applicant` service into this already-vendored roster; it does not need to vendor the
  roster itself.
- **Tool-access substrate for whatever AE's bridge calls into**:
  `src/applicant/adapters/tools/tool_registry.py` /
  `src/applicant/ports/driven/tool_registry.py` (`ToolRegistryPort.is_enabled`/`set_enabled`/
  `all_tools`, FR-UI-4) — the per-tool on/off seam any new AE-invoked tool registers through,
  same as every existing tool.

## Decision

Adopt the **two-agent architecture the product owner specified**, built as new services
alongside the existing scheduler/event-bus/audit substrate — RC and AE are each a sibling of
`CurationService`/ADR-0008's remediator, not a new agent runtime, a new bus, or a new store.

### Agent A — Reflection Coach

- **Cadence:** driven by `Scheduler.tick` for the daily pass (same "once per campaign per UTC
  day" idiom `Scheduler` already uses for the digest and the curation nudge), plus new
  `DomainEvent` subclasses for the event-driven triggers (a rejection, a response-rate/velocity
  stall, N applications sent, a fit-score trend shift) emitted at the points those facts are
  already known (`ApplicationStateChanged`, `OutcomeRecorded` handlers) and consumed by RC the
  same way `AuditLogService` consumes every other domain event.
- **Effectiveness signals:** response/interview rate, velocity + time-in-stage, fit-score trend
  + Kevin's approve/discard/edit feedback (RUX-2's discard-reason negative-learning-signal path
  is a live example of exactly this kind of signal already flowing into learning today), and
  funnel progress (discovered→drafted→submitted→responded→interview→offer) vs. the deadline.
  Evaluation is semantic (Q2: "is this getting the right job, fast"), so the assessment step is
  an LLM call over the aggregated signals, not a threshold rule — mirroring
  `CriteriaService._summarize`'s "LLM only for the human-readable judgment, deterministic
  mutation underneath" split (token frugality, FR-LEARN-7).
- **Authority:** calls `CriteriaService.apply_learned_adjustment` for non-integral tweaks
  (auto-applied, transparent via `learned_adjustments`, one-click revert via `clear_learned`)
  and `edit_criteria(confirm=...)`'s existing integral-field confirmation gate for anything
  touching `titles`/`locations`/`salary_floor` — RC never bypasses that gate; it proposes and
  waits like any other caller. "Strategy tweaks" outside criteria (sources/thresholds/pacing/
  throughput) reuse the same campaign-config surfaces those already have (e.g. the automated-
  work gate's tunables, `SCORING_BATCH_PER_TICK`-style per-campaign settings) rather than a new
  config store.
- **Handoff to AE:** programmatic needs RC surfaces (e.g. "a source keeps 403ing, needs a new
  connector"; "scoring never recovers below threshold for this campaign shape") are filed as a
  new `DomainEvent` (e.g. `ProgrammaticNeedRaised`) carrying a routine/urgent flag — routine
  lands on a **shared backlog queue** (a durable table AE polls/consumes, the same "staged
  proposal a consumer picks up" shape `CurationService`'s `MemoryProposal`/`SkillProposal`
  already use), urgent instead **directly invokes** AE's task-intake path (§Agent B) the way
  `NotificationService.notify_error` bypasses queuing for IMMEDIATE urgency today.

### Agent B — Automation Engineer

- **Triggers:** user-initiated (a new UI action), RC-initiated (queue or direct handoff, above),
  or self-detected (AE subscribes to the same detector events ADR-0008 defines, most directly
  the currently-unconsumed `RemediationRequested`, §"Relation to ADR-0008" below).
- **Scope:** Applicant's own code, campaign config/criteria/sources, the infra it runs on
  (vLLM/router/DB/deploy), and new external integrations — the full surface `docker-compose
  .prod.yml` + `src/applicant` + `a0-applicant` already cover, nothing wider.
- **Execution substrate:** the already-vendored `a0-applicant/agents/{coder,explorer,
  test-engineer,reviewer,security-auditor,debugger,coder-cloud,explorer-cloud}` roster
  (above), invoked through a **new, narrow bridge service** in `src/applicant` (a genuine new
  build, not reuse — nothing today calls this roster programmatically) that hands a task to the
  `agent0` overseer profile via the same `call_subordinate`/`orchestrate`/`subagent` shape a
  human operator uses today, and gets back a result AE can gate/canary/promote. Running on
  Applicant's own local+DeepSeek ladder means: no new model plane — the bridge targets the
  **existing** Plane A tier topology (`config/intel_tiers.yaml`), which already routes bulk
  coding to local `Qwen3.6-27B` and review/security/hard-debugging to DeepSeek-Flash/Pro per the
  **existing** R1-R9 escalation catalog (`config/intel_orchestration.yaml`) — including R7
  ("repeated local failure (>=2 struggles) → DeepSeek-Pro"), which is already the built-in
  stronger-tier escalation path for a struggling local coder, not something AE has to invent.
- **Deploy safety harness (all 4, per Q6):**
  1. **Canary first:** build the image, run it as a disposable instance (the `applicant-e2e`
     recipe, `HANDOFF.md` §5.2, generalized to a scripted "build → run disposable → wait for
     `/login` 200" step AE drives instead of a human), then run the **full test suite** plus a
     **browser monkey-crawl** (`journey_via_sidebar.py` + `scripts/monkey_crawl.py`) against it.
     Promote only if both are green.
  2. **Hard TDD/BDD gate:** no promotion unless the change's own unit tests AND its BDD
     scenarios (this epic's, or the feature's own) pass — mirrors the standing convention
     already enforced project-wide (`docs/APPLICANT-BACKLOG.md` "Delivery = full TDD + BDD").
  3. **Auto-rollback on failed health:** post-promote, poll the **existing** `/healthz`
     aggregation (`src/applicant/app/main.py`, referenced in ADR-0008 detector #7) and the
     **existing** `/api/health/capabilities` surface; a failed check within the post-deploy
     window triggers an automatic revert (new capability — see below).
  4. **Snapshot + instant revert on every deploy:** every promotion is preceded by a snapshot
     (image tag retained + a DB/schema snapshot mirroring `scripts/install.sh`'s existing
     pre-migration snapshot step, ADR-0008 detector #6) so "revert" is a single scripted action,
     not a manual `git revert` + rebuild.
     **Genuinely new build:** nothing in the stack today snapshots or auto-rolls-back a
     promotion — `scripts/updater-daemon.sh` only runs `update.sh --apply` forward. This harness
     is a new, narrow sibling of that control-plane pattern (request/status handshake), scoped
     to promote/health-check/rollback rather than restart.
- **Proactive comms:** every new piece of functionality is communicated to Kevin as it's being
  built (Q7 hard rule), not after — routed through the **existing** `NotificationService`
  (a new notification kind alongside `notify_error`/`notify_digest_ready`, not a new channel).

### Shared: oversight

- **Proactive notifications + daily digest:** extend `NotificationService` with RC/AE-specific
  notification kinds (learned-tweak-applied, feature-shipped, remediation-outcome), reusing the
  existing escalation ladder and digest cadence rather than a second notification system.
- **Live activity feed + audit log with revert buttons:** the **existing** `AuditLogService`/
  `ActionEvent` trail is the data source (new `DomainEvent` subclasses → `_ACTION_MAP` entries,
  same pattern as ADR-0008's S1). **Revert buttons are new**: today's audit panel
  (`src/applicant/app/routers/audit.py`) is read-only — no endpoint calls back into "undo this
  action." For RC this is nearly free (`CriteriaService.edit_criteria(clear_learned=True)`
  already *is* the revert operation, a button just needs to call it); for AE, "revert" means the
  harness's snapshot-restore path above. Both are new UI/API wiring over an existing or
  newly-built reversal primitive, not a new revert engine.
- **Global kill switch + per-action veto:** new scope, modeled on the automated-work gate's
  shape (a settings-backed boolean the tick loop checks every cycle, "0 is the kill switch"
  idiom) but broader — one switch that halts RC's auto-apply and AE's build/deploy pipeline
  entirely, plus a per-action veto surfaced wherever an action is proposed (the shared backlog
  queue, the activity feed) so a single item can be blocked without killing everything else.

### Responsible gate (Q10)

Both agents start now. RC's auto-apply authority is live from the start (it was already
authorized reversible authority, Q3). **AE's autonomous-DEPLOY step stays OFF** — AE builds,
canaries, and *proposes* a promotion, but a human approves the actual promote — until two
conditions both hold: (a) the core pipeline stably produces a full, relevant review queue
(observable via the same funnel signals RC already tracks), and (b) the deploy safety harness
above is built **and independently verified** (a real promotion exercised end-to-end, including
a forced-failure drill that proves auto-rollback actually fires). This is a config flag on the
bridge service (§Agent B), not a structural fork — flipping it later requires no redesign.

## Relation to ADR-0008 (EPIC SELF-HEAL)

AE **subsumes/extends** SELF-HEAL's remediation layer; RC is the strategic layer above both.
Concretely, mapped slice-by-slice so nothing here duplicates a detector or remediator ADR-0008
already owns:

| ADR-0008 slice | What it owns today | How AE extends it |
|---|---|---|
| **S1** — remote-repairs-local LLM | Detects a wedged local LLM, escalates inference, emits `RemediationRequested` **but does not consume it** (`core/events.py` L157-166: "S1 does NOT implement the actual local-service restart... a separate vLLM-host watchdog is the intended consumer"). | AE's bridge is architecturally that intended consumer for the *build/fix* half — e.g. a config drift or a bad env value causing the wedge gets an AE-authored fix + redeploy through the harness, not just a restart request. Purely operational restarts (no code change) stay S1's own scoped control-plane action; AE only engages when the fix requires a code/config change beyond a restart. |
| **S2** — detector bus + audit store | Wires detector events onto `DomainEventBus`/`AuditLogService`. | AE and RC's new event types (`ProgrammaticNeedRaised`, feature-shipped, etc.) land on the **same** bus/store via the same `_ACTION_MAP` pattern — S2's infrastructure is reused verbatim, not re-built. |
| **S3** — scorer-degrade auto-heal | Re-scores poisoned postings once the LLM recovers; diagnoses systemic vs. isolated failure. | Out of AE's scope by default (S3 already closes this loop operationally). AE only engages if RC's effectiveness assessment surfaces a **pattern** S3 can't fix operationally (e.g. the embedding-fallback threshold itself needs recalibrating) — a code/config change, filed through RC's programmatic-need handoff like any other AE task. |
| **S4** — panel-error auto-heal | Explicitly scoped to detect + audit + safe-mitigate (disable the broken gadget) + alert — self-healing.md's Gap 5 states outright: *"Remediating a code-level bug is out of scope for this epic... A future 'AI writes the patch, updater sidecar redeploys it' loop is a materially bigger, separate capability and is explicitly not part of this epic."* | **This is EPIC AGENTS, named in advance.** AE is exactly that deferred capability: S4 detects/mitigates/alerts; AE is the consumer that can write the actual patch and redeploy it through the safety harness. No overlap — S4's scope is unchanged by this ADR. |
| **S5** — stuck-queue / idle-txn auto-heal | Bounded operational remediation (release-and-retry a sandbox slot, terminate an idle session) before the existing human-notify cap. | Unchanged; AE only engages if the *pattern* itself (not one stuck instance) indicates a code-level cause RC/AE should file as a build task. |

RC has no ADR-0008 analogue — SELF-HEAL is reactive (detect a break, fix it); RC is the new
proactive layer (is the *strategy* working, not just is the *system* up).

## Guardrails (inviolable, extending ADR-0008 layer 4)

- **Never auto-submit a user's job application.** Neither RC nor AE, nor anything AE builds,
  may be granted a caller of `FinalApprovalService`'s `final_approval` `send` with
  `DECISION_SUBMIT_SELF`/`DECISION_ENGINE_FINISH` on the user's behalf. AE may write code that
  touches the review/approval UI; it may never call the submit path itself, in dev, canary, or
  prod.
- **Never destroy user data.** AE's snapshot-before-promote step (above) is itself a guardrail:
  any migration or data change it ships is reversible by construction. Same ADR-0008 boundary
  (may reset a counter/circuit-breaker; may never drop an `Application`/`JobPosting`/credential/
  document) extends unchanged to anything AE builds.
- **Bounded, audited, fail-safe** — same ADR-0008 discipline (bounded retries, full audit trail,
  fail-safe alert on exhaustion) applies to RC's auto-apply loop and AE's build/canary/promote
  loop identically; a struggling AE build attempt escalates per the existing R7 tier rule, then
  gives up and notifies, it does not spin.
- **Kill switch + veto are checked, not advisory** — exactly like the automated-work gate is
  checked at the top of every tick (`agent_loop.py` L457), the global kill switch and per-action
  veto are checked at the top of RC's evaluation and at every AE pipeline stage (build, canary,
  promote), not just at task intake.

## Consequences

**Positive:**

- RC's entire authority mechanism (auto-apply + transparency + revert) already exists in
  production code (`CriteriaService`) — RC is a new *caller*, which is a small, well-bounded
  build relative to what it delivers (semantic campaign self-improvement).
- The "coder/reviewer/debugger + orchestration" stack the epic asks to vendor is **already
  vendored** (`a0-applicant/agents/*`, `config/intel_tiers.yaml`/`intel_orchestration.yaml`) —
  the real remaining work is a callable bridge, not standing up a second agent framework.
- SELF-HEAL's S4 gap notice named this epic's AE by name as the deferred capability ("a
  materially bigger, separate capability") — this ADR is that capability landing where the prior
  ADR already said it would, so the two epics were designed to fit together, not reconciled
  after the fact.
- The deploy harness reuses a real, already-exercised manual recipe (`applicant-e2e` +
  `journey_via_sidebar.py` + `monkey_crawl.py` + the `HANDOFF.md` §5.3 promote steps) — AE
  automates a sequence a human has already run successfully, not an unproven one.

**Negative / risks:**

- **The capability checkpoint is real and unresolved.** AE's default coding tier is local
  `Qwen3.6-27B` (GPTQ-Int4, 27B) with DeepSeek-Flash/Pro escalation — meaningfully weaker than
  the Claude-class coder that develops Applicant today (per Kevin's own standing note,
  `Piloting Not Coding`: "Claude pilots A0 to write ALL applicant code; Claude only
  specs/verifies/steers"). Handing this tier **production deploy authority** is a materially
  bigger trust step than handing it a subordinate coding task reviewed by a human. **Mitigated
  by:** (1) the Q10 responsible gate keeping auto-promote OFF until the harness is independently
  verified; (2) a **recommended validation gate** before that flip — run AE in propose-only mode
  against a representative slice of real backlog items (e.g. the same P1/P2 items already
  tracked in `docs/APPLICANT-BACKLOG.md`) for a defined period, and measure its output against
  the bar Claude-piloted commits already clear (does it pass the full suite untouched by a
  human, does its own BDD AC hold, does a `reviewer`/`security-auditor` pass catch what a human
  reviewer would) before trusting it to promote unattended; (3) a **stronger-coding-tier
  option**, not a new mechanism — `config/intel_orchestration.yaml`'s R7 rule already escalates
  a struggling local coder to DeepSeek-Pro; if that still proves insufficient after validation,
  the same env-gated-optional-rung pattern MODEL-RESILIENCY already established for the engine's
  own tier ladder (off without a key, byte-identical without it) is the template for adding an
  even-stronger optional rung (a Claude-class API key) to Plane A's `coder`/`debugger` profiles,
  rather than inventing a new escalation mechanism.
- **An over-eager or wrong-headed AE is a bigger blast radius than an over-eager remediator**
  (ADR-0008's equivalent risk) — a remediator can restart a service; AE can ship a bug to
  production. This is exactly why the harness's 4 layers are declared mandatory-all, not
  pick-some, and why the Q10 gate is a hard precondition, not a target date.
- **Cost.** RC's daily+event-driven semantic evaluation and AE's build/review/debug ladder both
  spend cloud tokens on every cycle (RC's LLM assessment call; AE's `reviewer`/`security-
  auditor`/`debugger` cloud tiers) — ongoing operational cost, same category ADR-0008 already
  flagged for its own remote-repair calls, now larger in scope.
- **New-build surface, called out explicitly rather than assumed away:** the AE↔`a0-applicant`
  bridge service, the shared backlog queue (RC→AE), `ProgrammaticNeedRaised` (and siblings) as
  new domain events, the snapshot/auto-rollback control-plane extension, revert-button
  endpoints on the audit surface, and the global kill switch + per-action veto are all genuinely
  new components with no existing seam to extend — recorded as prerequisites in the story doc
  rather than assumed covered by "reuse."
- **`monkey_crawl.py` and the migration-failure signal are still offline/gap items per
  ADR-0008** (its Consequences, and Gaps 3-4 in `docs/stories/self-healing.md`) — AE's canary
  layer depends on `monkey_crawl.py` at minimum being invocable non-interactively against a
  disposable instance (already true, per `HANDOFF.md` §5.4's `docker exec` recipe) even though
  it is not yet a *live* product detector; AE does not need the live-detector wiring, only the
  scripted invocation, which already works.

**Alternatives considered:**

- **One agent, not two** — rejected: the product owner's decisions (Q1-Q10) are explicit about
  two agents with different cadences, authorities, and blast radii (RC mutates config/criteria
  only; AE mutates code/infra/deploys). Merging them would either over-authorize RC (config
  changes getting deploy-level review overhead) or under-govern AE (code changes getting
  criteria-level lightweight review) — a mismatch, not a simplification.
  - **AE builds a coding stack from scratch instead of vendoring `a0-applicant`'s roster** —
  rejected: `config/intel_tiers.yaml`/`intel_orchestration.yaml` and the `a0-applicant/agents/*`
  profiles already exist, are contract-tested, and already encode exactly the delegation
  doctrine (local-bulk / cloud-review / cloud-debug) the epic asks for. Building a second one
  would violate the standing reuse-first principle for no benefit.
- **Auto-promote from day one (skip Q10's gate)** — rejected as the exact mistake ADR-0008
  warned against one level down (an over-eager remediator is worse than the failure it fixes);
  at AE's scale (shipping code to production) the same risk is categorically larger, so the gate
  is load-bearing, not a formality.
- **RC mutates criteria directly without going through `CriteriaService`'s gate** — rejected:
  would silently reopen the exact class of "core criterion silently mutated" risk
  `CriteriaService`'s confirmation gate (FR-FB-3) already exists to prevent.
