# EPIC AGENTS — Staged, safety-gated build plan (Reflection Coach + Automation Engineer)

**Synthesizes:** the four EPIC AGENTS design lanes — Reflection Coach (RC), Automation Engineer
(AE), the 4-layer deploy safety harness, and the A0-coding-stack recon — into **one staged,
safety-gated build order**.
**Grounds in (read-only):** `docs/adr/0009-self-improving-agents.md`,
`docs/stories/self-improving-agents.md`, `docs/adr/0008-autonomous-self-healing.md` +
`docs/stories/self-healing.md`, `docs/APPLICANT-BACKLOG.md` § EPIC AGENTS (Q1–Q10),
`src/applicant/core/events.py`, `scripts/update.sh` / `scripts/updater-daemon.sh`, `HANDOFF.md`
§5.2–5.4, and the vendored `a0-applicant/agents/*` roster + `config/intel_*.yaml`.
**Extends, does not duplicate:** ADR-0009 and the slice doc already define RC1–RC3 / AE1–AE6 /
SH1 / GATE-1 with per-slice DoR/AC/DoD. This plan re-cuts that work into **waves with
conflict-free file-sets** so slices parallelize safely, factors out the shared new-build
primitives ADR-0009 lists as "genuinely new," and makes Kevin's hard sequencing directive the
spine of the schedule. Where a story here maps 1:1 to a slice in the story doc, its ID is noted.

---

## The one hard rule this plan is built around

> **Kevin's directive:** the 4-layer safety harness **and** a concrete "base proven" gate MUST
> land and be **independently verified** BEFORE the Automation Engineer's **auto-deploy**
> capability is ever enabled. Both agents may be **built in parallel** — but AE's auto-promote
> stays **hard-OFF** (propose-only) until the gate clears.

Consequences that shape every wave below:

1. **Auto-promote is a config flag, default propose-only** (ADR-0009 Decision "Responsible gate";
   backlog Q10). It ships **OFF** with AE4 and is only flipped after Wave 4's `GATE-1` verification
   passes. No story in Waves 0–3 grants auto-promote authority — AE **builds → canaries →
   snapshots → proposes**; a human approves the production promote.
2. **The harness mechanism is built once, in the scripts lane** (`H1`, `H2`), and the AE Python
   pipeline stages (`AE2`–`AE5`) are thin, audited drivers over it — no layer is implemented
   twice. This dedupes the overlap between the harness design (one `scripts/harness.sh`
   orchestrator) and the AE slices (AE2–AE5).
3. **"Base proven" is measurable, not a vibe:** it reads RC1's own funnel signals
   (discovered→drafted→submitted→responded→interview→offer) showing sustained healthy throughput,
   AND the AE5 forced-failure rollback drill having actually fired and restored health. Both are
   `GATE-1` preconditions (backlog Q10 (a) + (b)).

---

## Dependency graph (waves flow top→bottom)

```
WAVE 0  F1 events+audit   F2 kill-switch/veto   F3 backlog-queue   F4 harness-common+dispatcher
          │  │  │              │                     │                    │
WAVE 1   RC1 ─ AE1 ──────────┘ (F1,F3)              │                   H1 preflight (canary+gate)
          │     │                                    │                    │
WAVE 2   RC2  RC3(F3)  AE2(gate)   SH1a(F1,F2)   AE6(notif kinds)         │
          │           │                                                    │
WAVE 3                H2 promote/snapshot/rollback(F4,H1) ── AE3 canary(H1) ── AE4 promote+GATE flag(H2)
                                                                              │
WAVE 4   AE5 auto-rollback+drill(H2)   SH1b revert+digest(RC2,AE4)   GATE-1 verify→authorize flip
```

**AE auto-deploy is enabled only when the whole left-to-bottom chain is green AND `GATE-1`
passes.** Everything above `GATE-1` runs in propose-only mode.

---

## Shared integration seams (the only files touched by more than one story)

To keep each story's file-set genuinely conflict-free, these cross-cutting files are handled by an
explicit convention rather than being claimed by any single story:

- **`src/applicant/app/container.py`, `src/applicant/app/deps.py`, `src/applicant/app/main.py`** —
  each new service/router appends its **own additive provider/route block**. Merge order = wave
  order; within a wave, land these blocks last, one story at a time (they are 3-to-10-line
  additive diffs, not rewrites). No story *owns* these files; every service story lists them as
  "additive-only integration edits."
- **`src/applicant/adapters/storage/models.py`** — F2 and F3 each add a table class. Additive, but
  the **same file**: land F2's table then F3's (Wave 0 internal order), or split each into its own
  model module imported by `models.py`.
- **`src/applicant/adapters/storage/alembic/versions/*`** — each migration is a new, uniquely-named
  revision file (no filename collision), **but Alembic `down_revision` must chain**: create
  migrations in a fixed order per wave and rebase `down_revision` — never author two parallel
  migrations off the same parent. This is the one place "parallel" needs a serialization point.
- **`scripts/harness.sh`** — created once in `F4` as a dispatcher that **glob-sources
  `scripts/lib/harness-*.sh`**, so `H1` and `H2` each drop in their own lib file with **no edit to
  `harness.sh` itself** (that is why they are conflict-free despite being "the same harness").

Every other file below is owned by exactly one story within its wave.

---

## WAVE 0 — Shared foundations

*Four stories, fully parallel — disjoint subsystems (events / gate / queue / scripts). These are
the "genuinely new components with no existing seam" ADR-0009 Consequences enumerates; building
them first unblocks both agents and the harness.*

### F1 — Agent domain events + audit map
Maps to: ADR-0009 "Shared: oversight" event wiring; prerequisite for RC3/AE1/SH1.

**DoR:** confirmed that the S2 pattern (`llm_wedge_detector.py` → `_ACTION_MAP`) is the exact
precedent (`ADR-0008 S1`, commit `52b3f6c2a`); the four RC event-driven triggers and the AE
lifecycle events are enumerated; failing tests written first.

**AC (Gherkin):**
```gherkin
Feature: RC/AE domain events land on the existing bus and audit trail
  Scenario: A new agent event is auditable via the existing map
    Given ProgrammaticNeedRaised (RC→AE) and the AE lifecycle events
      (build-started, feature-shipped, remediation-outcome, action-vetoed) are defined
    When any of them is emitted on the existing DomainEventBus
    Then AuditLogService records it via _ACTION_MAP with no new bus or store
    And a faulty subscriber never breaks the emitter (existing swallow-and-log contract holds)
```
**DoD:** new frozen `DomainEvent` subclasses added to `core/events.py`; `_ACTION_MAP` entries
added; TDD unit green; no new event bus/store introduced; fresh-install safe (zero events is
normal).
**Files:** `src/applicant/core/events.py`, `src/applicant/application/services/audit_log_service.py`,
`tests/unit/test_agents_events.py` *(new)*.
**Depends on:** none.

### F2 — Global kill switch + per-action veto primitive
Maps to: SH1 kill-switch/veto half (its no-dependency portion); backlog Q8; ADR-0009 Guardrails.

**DoR:** confirmed broader than the existing automated-work gate (`agent_loop.py` L457 /
`scheduler.py`), which only gates campaign automation, not RC tweaks or AE deploys (backlog Gap 5);
"0/OFF is the kill switch" idiom adopted; failing tests first.

**AC (Gherkin):**
```gherkin
Feature: A checkable global kill switch and per-action veto
  Scenario: The kill switch is a checkable primitive, not advisory
    Given the global kill switch is engaged
    When code asks the gate "may an agent action run?"
    Then it returns false, and re-engaging resumes without a restart
  Scenario: A single action can be vetoed independently
    Given a specific pending action id
    When it is vetoed
    Then only that id is blocked and every other action's gate check still passes
```
**DoD:** a settings-backed switch + a durable per-action veto record; a pure, unit-testable
`is_allowed(action_id)` primitive callers check at the top of every cycle; default OFF-for-automation
(safe default, mirrors the automated-work gate); migration + TDD green; **no UI yet** (SH1a).
**Files:** `src/applicant/application/services/agent_automation_gate.py` *(new)*,
`src/applicant/adapters/storage/models.py` *(additive: veto table)*, a new alembic revision,
`src/applicant/app/config.py` *(additive: kill-switch setting)*, `tests/unit/test_agent_gate.py`
*(new)*.
**Depends on:** none. *(Alembic chain + `models.py` order: land before F3's migration.)*

### F3 — Shared backlog queue (RC→AE durable hand-off)
Maps to: backlog Q4 "shared backlog queue"; slice-doc Gap 4; RC3 files onto it, AE1 polls it.

**DoR:** confirmed the closest existing shape is `CurationService`'s staged
`MemoryProposal`/`SkillProposal` (different payload/consumer, so followed not literally reused);
the port sits alongside `ports/driven/routine_store.py` as a sibling; failing tests first.

**AC (Gherkin):**
```gherkin
Feature: A durable queue carries routine programmatic needs from RC to AE
  Scenario: A routine need is queued and later consumed exactly once
    Given a ProgrammaticNeedRaised item is enqueued
    When AE's intake polls the queue
    Then it receives the item once and marks it consumed durably
    And a restart does not lose or double-deliver it
```
**DoD:** a new `AgentTaskQueuePort` + a Postgres-backed adapter; enqueue/poll/ack semantics;
migration + TDD green; empty queue is a normal, non-error state (fresh-install safe).
**Files:** `src/applicant/ports/driven/agent_task_queue.py` *(new)*,
`src/applicant/adapters/storage/agent_task_queue_repo.py` *(new)*,
`src/applicant/adapters/storage/models.py` *(additive: queue table — land after F2)*, a new alembic
revision *(chain after F2's)*, `tests/unit/test_agent_task_queue.py` *(new)*.
**Depends on:** none *(coordination-only with F2 on `models.py`/alembic ordering)*.

### F4 — Harness common library + dispatcher skeleton
Maps to: harness design's `scripts/lib/harness-common.sh` refactor; ADR-0009 harness §; slice-doc
Gap 2. **Zero behavior change to `update.sh`.**

**DoR:** confirmed `update.sh` already contains `snapshot` / `auto_rollback` / `restore_dump` /
`heartbeat` / `prune_backups` + smart-skip build (verified in `scripts/update.sh`); these are
extractable verbatim into a sourced lib; a shell test harness (bats/shellcheck) is available.

**AC (Gherkin):**
```gherkin
Feature: Deploy primitives are shared, and a dispatcher can sequence them
  Scenario: update.sh behaves identically after extraction
    Given the snapshot/rollback/restore/heartbeat/prune helpers move to harness-common.sh
    When update.sh --apply runs (dry-run and applied)
    Then its behavior is byte-for-byte unchanged (it now sources the lib)
  Scenario: The dispatcher discovers layer scripts without being edited
    Given scripts/harness.sh glob-sources scripts/lib/harness-*.sh
    When a new harness-<layer>.sh is dropped in
    Then its subcommand is dispatchable with no edit to harness.sh
```
**DoD:** `harness-common.sh` created with the extracted, already-tested helpers; `update.sh` sources
it with **no behavior change** (existing update tests still green); `harness.sh` dispatcher skeleton
added (glob-sources lib, routes subcommands); shell test green.
**Files:** `scripts/lib/harness-common.sh` *(new)*, `scripts/harness.sh` *(new dispatcher)*,
`scripts/update.sh` *(edit: source the lib — additive, no behavior change)*, `tests/scripts/`
*(new shell test)*.
**Depends on:** none.

---

## WAVE 1 — Agent cores + pre-flight gate executor

*Three stories, parallel across three lanes (RC service / AE service / scripts). Both agents' cores
start now (backlog Q10); the harness's fail-forward-safe half (canary + TDD/BDD gate, prod never
touched) lands in the scripts lane.*

### RC1 — Effectiveness assessment (signals + cadence)
Maps to: story-doc RC1. **Read-only: assesses, does not yet act (RC2).**

**DoR:** the four event-driven triggers (rejection / response-rate-velocity stall / N-apps-sent /
fit-score trend shift) map to existing emission points (`ApplicationStateChanged`,
`OutcomeRecorded`) with no new instrumentation beyond the trigger check; `Scheduler`'s "once per
campaign per UTC day" idiom confirmed as the daily template; the Q2 signals are all sourced from
existing services (`PipelineSummaryService`, `LearningService`, `ConversionService`,
`FeedbackService`) — no second analytics engine.

**AC (Gherkin):**
```gherkin
Feature: Reflection Coach effectiveness assessment
  Scenario: A daily evaluation runs once per campaign per day
    Given a campaign active for at least one day
    When the scheduler's daily tick fires
    Then RC produces one scored effectiveness assessment for that campaign
    And re-ticking the same day does not produce a second assessment
  Scenario: An event trigger fires an out-of-cadence evaluation
    Given a rejection, a velocity stall, N apps sent, or a fit-score trend shift occurs
    When that event is detected
    Then RC evaluates immediately, independent of the daily cadence
  Scenario: The assessment covers every required signal and is audited
    Given an assessment runs
    Then it includes response/interview rate, velocity + time-in-stage, fit-score trend with
      approve/discard/edit feedback, and funnel-vs-deadline progress
    And the result is recorded in the audit trail
  Scenario: It checks the kill switch first
    Given the global kill switch is engaged
    Then RC's next evaluation does not run
```
**DoD:** new `reflection_coach_service.py` producing a scored, audited assessment via one LLM call
over deterministic aggregates (mirrors `CriteriaService._summarize` token-frugality); daily hook via
scheduler + event-driven triggers; checks F2's gate at the top of every eval; TDD + BDD green;
verified on 10.0.1.11 (forced daily tick + forced event trigger both produce a visible, audited
assessment); fresh-install safe (no history → honest "insufficient data", no crash).
**Files:** `src/applicant/application/services/reflection_coach_service.py` *(new)*,
`src/applicant/application/services/scheduler.py` *(edit: additive daily hook)*,
`tests/unit/test_reflection_coach.py` *(new)*, `tests/bdd/steps/test_self_improving_agents_steps.py`
*(new, wires `rc1_effectiveness_assessment.feature`)*, `container.py`/`deps.py` *(additive)*.
**Depends on:** F1, F2.

### AE1 — Task intake + vendored coding-stack bridge
Maps to: story-doc AE1 — **the epic's single biggest new build (Gap 1)**. Recon confirms the roster
is already vendored; the gap is the callable, task-scoped bridge.

**DoR:** a callable entry point into the `agent0` overseer from outside its chat UI must be
**spiked first** (recon flagged this as the one genuinely-unproven piece — `grep -rl
"automation_engineer\|reflection_coach" src/` returns nothing today); one task schema agreed across
all three intake sources (user / RC / self) so AE2–AE5 build against one shape; the bridge targets
the **existing** Plane A tier topology (`config/intel_tiers.yaml`/`intel_orchestration.yaml`) — no
new model plane.

**AC (Gherkin):**
```gherkin
Feature: Automation Engineer task intake and coding-stack bridge
  Scenario: A task from any of the three sources reaches the bridge
    Given a user request, a ProgrammaticNeedRaised (RC3, queued or direct), or a
      RemediationRequested / AE-specific detector event
    When intake consumes it
    Then it is accepted as one Automation Engineer task with a single shared shape
  Scenario: The bridge delegates to the existing roster, not a new framework
    Given an accepted task requires implementation
    When the bridge dispatches it
    Then it hands a self-contained task to the vendored agent0 overseer and the existing
      coder/explorer/test-engineer/reviewer/security-auditor/debugger tiers
    And no parallel coding-agent framework is instantiated
  Scenario: A build is announced proactively at acceptance
    Given a task is accepted and building begins
    Then a proactive "building" notification + audit entry is emitted before it completes
```
**DoD:** new `automation_engineer_service.py` (intake for all three sources; subscribes to
`RemediationRequested`; polls F3 queue; direct-handoff path mirrors `notify_error`'s IMMEDIATE
bypass) + a new `AgentBridgePort` + adapter into the vendored `agent0` roster; emits the
build-started event/notification at acceptance (Q7 hard rule); checks F2's gate at intake and every
stage; TDD + BDD green; verified on 10.0.1.11 (one task per source reaches the bridge and dispatches
to the roster — propose-only outcome is fine here); fresh-install safe (roster unreachable →
queue/retry, never crash the engine).
**Files:** `src/applicant/application/services/automation_engineer_service.py` *(new)*,
`src/applicant/ports/driven/agent_bridge.py` *(new)*,
`src/applicant/adapters/agent_bridge/a0_bridge.py` *(new)*,
`tests/unit/test_automation_engineer.py` *(new)*, `container.py`/`deps.py` *(additive)*.
**Depends on:** F1, F3. *(Bridge-entry spike is a DoR gate, not a separate story.)*

### H1 — Pre-flight gate executor (layers 1+2: canary + TDD/BDD)
Maps to: harness design's promote pre-flight; ADR-0009 harness §1–2; story-doc AE3's script
prerequisite. **Fail-forward-safe: prod is never mutated on a failed gate.**

**DoR:** the `applicant-e2e` build→run-disposable→poll-`/login`-200→teardown recipe (`HANDOFF.md`
§5.2) and the `journey_via_sidebar.py` + `scripts/monkey_crawl.py` crawl (§5.4) are confirmed
invocable non-interactively against a disposable instance (already true per §5.4 `docker exec`
recipe — slice-doc Gap 6 does **not** block this).

**AC (Gherkin):**
```gherkin
Feature: Candidate images are gated before prod is ever touched
  Scenario: Build → disposable canary → suite + monkey-crawl, all on candidate images
    Given a candidate build
    When harness.sh runs the pre-flight gate
    Then it builds the image, runs it as a disposable e2e instance, waits for /login 200,
      runs the full test suite AND a browser monkey-crawl against it
    And it never overwrites :latest or applies a migration during pre-flight
  Scenario: A failed pre-flight leaves prod untouched
    Given the suite or the monkey-crawl fails on the canary
    Then the gate exits non-zero, prod images and DB are unchanged, and the failure detail is
      captured for the caller
```
**DoD:** `scripts/lib/harness-preflight.sh` implementing layers 1+2 over the disposable-instance
recipe + the existing crawl tooling; prod provably untouched on failure; shell test green; runnable
against 10.0.1.11's disposable instance.
**Files:** `scripts/lib/harness-preflight.sh` *(new)*, `tests/scripts/` *(new preflight shell
test)*. *(No edit to `harness.sh` — dispatcher glob-sources it, per F4.)*
**Depends on:** F4.

---

## WAVE 2 — RC actions, hand-off, gate stage, oversight controls, proactive comms

*Five stories. RC2/RC3 are file-disjoint (RC3 gets its own module). AE2 is the first Python pipeline
stage. SH1a builds the oversight surface over F1/F2. AE6 adds the notification kinds.*

### RC2 — Auto-apply reversible tweaks
Maps to: story-doc RC2.

**DoR:** RC1 merged; confirmed which "strategy tweaks" (sources/thresholds/pacing/throughput) route
through `CriteriaService` vs an existing per-campaign settings surface — **no new config store**
either way (ADR-0009 Agent A "Authority").

**AC (Gherkin):**
```gherkin
Feature: RC auto-applies transparent, reversible tweaks
  Scenario: A non-integral learned tweak auto-applies and is visible
    Given the assessment recommends a non-integral criteria adjustment
    When RC applies it
    Then CriteriaService.apply_learned_adjustment records the delta + human-readable summary in
      learned_adjustments, visible without the user asking
  Scenario: An integral-field tweak is proposed, not silently applied
    Given the assessment recommends changing titles, locations, or salary_floor
    Then it is staged as a proposed_integral learned adjustment needing explicit confirmation
  Scenario: Any auto-applied tweak is one-click reversible
    Given a tweak RC auto-applied
    When the user reverts it
    Then CriteriaService.edit_criteria(clear_learned=True) restores prior state, itself audited
```
**DoD:** RC1's assessment drives tweaks through the **existing** `CriteriaService` seams only (never
a new mutation path); integral fields hit the existing confirmation gate; TDD + BDD green; verified
on 10.0.1.11 (a real tweak visible in `learned_adjustments`, reversible via clear-learned — button
wiring may lag, the service call must work); fresh-install safe (automation off → applies nothing).
**Files:** `src/applicant/application/services/reflection_coach_service.py` *(edit: apply path)*,
`src/applicant/application/services/rc_tweak_apply.py` *(new, if the apply logic is split out to
keep RC3 file-disjoint)*, `tests/unit/test_rc_auto_apply.py` *(new)*, BDD steps *(extend, wire
`rc2_*.feature`)*.
**Depends on:** RC1.

### RC3 — Programmatic-need hand-off to AE
Maps to: story-doc RC3. **Own module so it is file-disjoint from RC2.**

**DoR:** RC1 merged; AE1's intake shape agreed (RC3's hand-off is one of AE1's three sources — queue
schema is F3, direct-handoff call shape is AE1) so nothing is designed twice.

**AC (Gherkin):**
```gherkin
Feature: RC files programmatic needs to AE
  Scenario: A routine programmatic need is queued
    Given the assessment identifies a need only code/config can fix, not marked urgent
    Then a ProgrammaticNeedRaised event is filed onto the shared backlog queue (F3), visible to
      AE's intake without further action
  Scenario: An urgent programmatic need bypasses the queue
    Given the need is marked urgent (e.g. a source newly broken, blocking the funnel)
    Then it is handed directly to AE's intake and does not wait for a poll cycle
```
**DoD:** routine → F3 queue; urgent → direct AE1 intake (mirrors `notify_error` IMMEDIATE bypass);
TDD + BDD green; verified on 10.0.1.11 (routine lands + is picked up by AE1; urgent reaches intake
immediately); fresh-install safe (empty queue + zero needs is normal).
**Files:** `src/applicant/application/services/rc_programmatic_handoff.py` *(new)*,
`tests/unit/test_rc_handoff.py` *(new)*, BDD steps *(extend, wire `rc3_*.feature`)*.
**Depends on:** RC1, AE1 (intake shape), F3.

### AE2 — TDD/BDD hard gate stage
Maps to: story-doc AE2; harness layer 2, driven from Python. **Own stage module (parallel-safe with
AE3/AE4/AE5).**

**DoR:** AE1 merged (produces a completed task's diff/commit for the gate to check).

**AC (Gherkin):**
```gherkin
Feature: AE TDD/BDD hard gate
  Scenario: A change with failing tests is blocked from canary
    Given AE completes a task
    When its unit tests or its BDD scenarios fail
    Then the change is not eligible for canary/promotion and the specific failing check is audited
  Scenario: A green change proceeds
    Given AE completes a task
    When its unit tests and BDD scenarios both pass
    Then the change becomes eligible to enter the canary stage (AE3)
```
**DoD:** `ae_pipeline/gate.py` runs the change's own unit + BDD against the real runner
(`.venv/bin/pytest`, no AE exemption) and gates eligibility; failing check recorded to audit; TDD +
BDD green; verified on 10.0.1.11 (a deliberately-broken change blocked, a green one proceeds);
fresh-install safe.
**Files:** `src/applicant/application/services/ae_pipeline/__init__.py` *(new, thin runner)*,
`src/applicant/application/services/ae_pipeline/gate.py` *(new)*,
`tests/unit/test_ae_gate.py` *(new)*, BDD steps *(extend, wire `ae2_*.feature`)*.
**Depends on:** AE1.

### SH1a — Kill switch + veto surface + live activity feed
Maps to: story-doc SH1 (its dependency-free half — backlog Q8). Revert buttons + digest are SH1b
(Wave 4).

**DoR:** F1 + F2 merged; kill-switch scope confirmed broader than the automated-work gate (new
switch, modeled on its shape, not a repoint).

**AC (Gherkin):**
```gherkin
Feature: Shared oversight controls
  Scenario: The activity feed shows every RC/AE action
    Given RC or AE has taken a recorded action
    When the user views the activity feed
    Then the action is listed with its audit detail
  Scenario: The kill switch halts both agents
    Given the global kill switch is engaged
    Then RC performs no further evaluations/auto-applies and AE performs no build/canary/promote,
      the halt is visible on the feed, and re-engaging resumes without a restart
  Scenario: A per-action veto blocks exactly one action
    Given multiple actions are queued/pending across both agents
    When the user vetoes one
    Then only that action is blocked; all others continue unaffected
```
**DoD:** a new agents router/panel exposing the F2 switch toggle + per-action veto + a live activity
feed over the existing `AuditLogService`/`ActionEvent` trail (read side); TDD + BDD green; verified
on 10.0.1.11 (kill switch demonstrably halts both, a veto blocks one action without affecting a
concurrent one); fresh-install safe (switch defaults OFF-for-automation; agents inert until enabled).
**Files:** `src/applicant/app/routers/agents.py` *(new)*,
`a0-applicant/agents/agent0/webui/…` or the product webui panel *(new activity-feed panel — exact
path per the UI kit; not shared with any other story)*, `tests/unit/test_agents_router.py` *(new)*,
BDD steps *(extend, wire the kill-switch/veto scenarios of `sh1_oversight.feature`)*,
`main.py` *(additive route registration)*.
**Depends on:** F1, F2.

### AE6 — Proactive communication (notification kinds)
Maps to: story-doc AE6 (Q7 hard rule). Landed early so **nothing AE builds is ever silent**; the
"building" kind is used by AE1 at acceptance; the "shipped" kind is wired by AE4/AE5 in their DoD.

**DoR:** AE1 merged (task acceptance is the first proactive-comms trigger).

**AC (Gherkin):**
```gherkin
Feature: AE communicates proactively, not after the fact
  Scenario: Starting a build is announced immediately
    Given AE accepts a task and begins building
    Then a proactive notification describing what is being built and why is sent before completion
  Scenario: A shipped feature is announced on healthy promotion
    Given a change is promoted and passes its health checks
    Then a proactive notification confirms what shipped, visible on the feed with linked audit
```
**DoD:** two new `NotificationService` kinds (building / shipped) on the **existing** escalation
ladder + digest cadence (no new channel); AE1's acceptance hook fires the building kind; TDD + BDD
green; verified on 10.0.1.11; fresh-install safe (degrades like existing notification paths when no
channel configured).
**Files:** `src/applicant/application/services/notification_service.py` *(edit: additive kinds)*,
`tests/unit/test_ae_notifications.py` *(new)*, BDD steps *(extend, wire `ae6_*.feature`)*.
**Depends on:** AE1.

---

## WAVE 3 — Promote/rollback executor + canary/promote pipeline stages

*The fail-back-safe half of the harness (`H2`) plus the AE stages that drive the harness. The
promote stage (`AE4`) ships the auto-promote flag **defaulted OFF (propose-only)**.*

### H2 — Promote + snapshot + rollback executor (layers 3+4) + control-plane verb
Maps to: harness design's promote/rollback flow + updater control-plane extension; ADR-0009 harness
§3–4; slice-doc Gap 2.

**DoR:** F4 + H1 merged; the updater sidecar's file control-plane (`request`/`status.json`/
`update.log`/`updater.alive`, per `scripts/updater-daemon.sh`) confirmed as the shape to extend
with `promote`/`rollback`/`snapshot` verbs (not a fork); `/healthz` + `/api/health/capabilities`
confirmed as the post-deploy health surfaces.

**AC (Gherkin):**
```gherkin
Feature: Snapshot-before-promote with a verified auto-rollback
  Scenario: Every promotion is snapshotted first
    Given a candidate has passed pre-flight (H1)
    When harness.sh promotes it
    Then a pre-promotion snapshot (image tag retained + DB/schema dump) is taken and addressable
      before :latest / the DB are mutated
    And if the snapshot step fails, promotion is blocked
  Scenario: A failed post-deploy health check auto-rolls-back
    Given a promotion completed
    When a health check fails within the monitoring window
    Then harness.sh reverts to the snapshot with zero human action and re-verifies health
  Scenario: The control plane carries promote/rollback, not just restart
    Given the updater sidecar
    Then it accepts promote/rollback/snapshot requests and reports status the same way as update
```
**DoD:** `scripts/lib/harness-promote.sh` (snapshot → promote → health window → auto-rollback,
reusing `harness-common.sh`'s `snapshot`/`auto_rollback`/`restore_dump`/`heartbeat`); updater
control-plane extended with the new verbs; shell test + a scripted forced-failure proving rollback
fires; runnable against 10.0.1.11.
**Files:** `scripts/lib/harness-promote.sh` *(new)*, `scripts/updater-daemon.sh` *(edit: additive
promote/rollback/snapshot verbs)*, `docker/updater.Dockerfile` *(edit only if a new dep is needed)*,
`tests/scripts/` *(new promote/rollback shell test)*.
**Depends on:** F4, H1.

### AE3 — Canary stage
Maps to: story-doc AE3. Thin Python driver over H1.

**DoR:** AE2 merged (only gate-passed changes reach canary); H1 merged (the canary executor exists).

**AC (Gherkin):**
```gherkin
Feature: AE canaries every change before promotion
  Scenario: A gate-passed change is canaried, prod untouched
    Given a change passed the TDD/BDD gate (AE2)
    When AE attempts to promote it
    Then the canary stage runs harness.sh pre-flight (H1) on a disposable instance first and does
      not touch prod
  Scenario: A canary failure blocks promotion and is reported
    Given the suite or monkey-crawl fails on the canary
    Then the change is not promoted, the failure detail is audited, and the user is proactively
      notified
```
**DoD:** `ae_pipeline/canary.py` invokes H1, parses result, audits, notifies on failure (reuses
AE6's kinds); TDD + BDD green; verified on 10.0.1.11 (a real change canaried end-to-end with both
checks actually executing, not stubbed); fresh-install safe (disposable-instance lifecycle is
self-contained).
**Files:** `src/applicant/application/services/ae_pipeline/canary.py` *(new)*,
`tests/unit/test_ae_canary.py` *(new)*, BDD steps *(extend, wire `ae3_*.feature`)*.
**Depends on:** AE2, H1.

### AE4 — Snapshot + promote stage + GATE-1 flag (propose-only default)
Maps to: story-doc AE4 + the Q10 responsible-gate flag. **Ships auto-promote OFF.**

**DoR:** AE3 merged (only canary-passed changes reach promote); H2 merged (the promote/snapshot
executor exists); the auto-promote flag's home confirmed on the AE1 bridge/pipeline (flippable
without redesign, ADR-0009 Decision).

**AC (Gherkin):**
```gherkin
Feature: AE snapshots before promotion and stays propose-only until GATE-1
  Scenario: Auto-promote is OFF by default
    Given a canary-passed, snapshot-ready change and GATE-1 not yet confirmed
    Then AE proposes the promotion for a human to approve and does not promote automatically
  Scenario: A snapshot precedes every promotion
    Given a promotion proceeds (human-approved while gated)
    Then H2 takes a retained, addressable pre-promotion snapshot first; if it fails, promotion is
      blocked and the user is notified
```
**DoD:** `ae_pipeline/promote.py` drives H2 with snapshot; the auto-promote **config flag defaults
to propose-only**; in propose-only mode a human approval is required for the production promote; TDD
+ BDD green; verified on 10.0.1.11 (a real promotion produces a retained snapshot before containers
are recreated; auto-promote provably OFF); fresh-install safe (first promotion still snapshots — no
"assumes prior snapshot" bug).
**Files:** `src/applicant/application/services/ae_pipeline/promote.py` *(new)*,
`src/applicant/app/config.py` *(additive: auto-promote flag, default OFF)*,
`tests/unit/test_ae_promote.py` *(new)*, BDD steps *(extend, wire `ae4_*.feature`)*.
**Depends on:** AE3, H2.

---

## WAVE 4 — Auto-rollback drill, oversight completion, and the responsible gate

*Everything the auto-deploy flip depends on. `GATE-1` is the last thing done and the only thing that
authorizes flipping AE4's flag.*

### AE5 — Health-gated auto-rollback stage + forced-failure drill
Maps to: story-doc AE5. **Its forced-failure drill is `GATE-1` precondition (b).**

**DoR:** AE4 merged (rollback needs a snapshot to target); H2 merged; post-deploy window + failure
criteria defined (which checks, how long, how many consecutive failures).

**AC (Gherkin):**
```gherkin
Feature: AE auto-rolls-back a failed promotion
  Scenario: A healthy promotion stands
    Given a promotion completes and health checks pass through the window
    Then the promotion stands and no rollback occurs
  Scenario: A failed health check triggers automatic rollback
    Given a promotion completes and a health check fails within the window
    Then AE reverts to the pre-promotion snapshot with zero human action, audits it, and notifies
  Scenario: Rollback is verified, not assumed
    Given an automatic rollback completed
    Then the restored instance's health checks pass again
```
**DoD:** `ae_pipeline/rollback.py` polls `/healthz` + `/api/health/capabilities` for the window and
triggers H2's rollback on failure; TDD + BDD green; **verified on 10.0.1.11 by fault injection** —
promote a deliberately-broken build behind a test flag and confirm auto-rollback actually fires and
restores health (this is the drill `GATE-1` (b) requires); fresh-install safe (rollback assumes only
the one AE4 snapshot).
**Files:** `src/applicant/application/services/ae_pipeline/rollback.py` *(new)*,
`tests/unit/test_ae_rollback.py` *(new)*, BDD steps *(extend, wire `ae5_*.feature`)*.
**Depends on:** AE4, H2.

### SH1b — Revert buttons + daily digest
Maps to: story-doc SH1 (its dependency-bearing half).

**DoR:** RC2 merged (RC revert = `CriteriaService.edit_criteria(clear_learned=True)`); AE4/AE5
merged (AE revert = the H2 snapshot-restore primitive); the audit panel confirmed read-only today
(`routers/audit.py` has no undo endpoint — slice-doc Gap 3).

**AC (Gherkin):**
```gherkin
Feature: Working reverts and a combined daily digest
  Scenario: The activity feed offers a working revert per reversible action
    Given a recorded RC tweak or AE-shipped change
    When the user clicks revert
    Then RC reverts via clear_learned and AE reverts via the snapshot-restore primitive, each
      audited
  Scenario: A daily digest summarizes both agents
    Given a day of RC and AE activity
    Then the digest includes tweaks applied, tasks built/shipped, and anything vetoed or rolled back
```
**DoD:** new revert endpoints on the audit/agents surface wired to the two existing/new reversal
primitives; a combined RC+AE daily digest section (reuses the existing digest cadence); TDD + BDD
green; verified on 10.0.1.11 (a real RC tweak and a real AE change both revert from the feed);
fresh-install safe.
**Files:** `src/applicant/app/routers/audit.py` *(edit: additive revert endpoints)* **or**
`src/applicant/app/routers/agents.py` *(edit: extend SH1a's router — same owner, so no cross-story
conflict)*, `src/applicant/application/services/digest_service.py` *(edit: additive RC/AE section)*,
`tests/unit/test_sh1b_revert_digest.py` *(new)*, BDD steps *(extend, wire the remaining
`sh1_oversight.feature` scenarios)*.
**Depends on:** RC2, AE4, AE5.

### GATE-1 — Autonomous-deploy responsible gate (verify → authorize flip)
Maps to: story-doc GATE-1; backlog Q10. **Not a feature — the verification + authorization that
enables auto-promote.** This is the concrete "base proven" gate Kevin's directive requires.

**DoR:** AE2, AE3, AE4, AE5 all built and merged; the auto-promote flag (AE4) is in place and OFF.

**Preconditions (BOTH required before the flag may be flipped):**
- **(a) Base proven:** RC1's funnel signals (discovered→drafted→submitted→responded→interview→
  offer) show **sustained** healthy throughput — a full, relevant review queue over a defined
  window, not a one-off good day.
- **(b) Harness independently verified:** AE5's forced-failure drill has actually run and confirmed
  the rollback path fires and restores health — not merely unit-tested in isolation.

**Recommended additional validation (ADR-0009 Consequences — risk mitigation, not a hard blocker):**
before flipping, run AE in propose-only against a representative slice of real backlog items and
compare its output to the bar Claude-piloted commits clear (full suite passes untouched, its own
BDD AC holds, a `reviewer`/`security-auditor` pass catches what a human would). If local-Qwen +
DeepSeek quality is insufficient, add a stronger optional rung via the **existing** env-gated pattern
MODEL-RESILIENCY established (off without a key) — not a new mechanism.

**AC (Gherkin):**
```gherkin
Feature: Autonomous deploy stays gated until product and harness are both proven
  Scenario: Auto-promote is off until both preconditions are confirmed
    Given a canary-passed, snapshot-ready change and GATE-1's preconditions not both confirmed
    Then the change is proposed for a human to approve, not promoted automatically
  Scenario: Auto-promote activates only after both preconditions are confirmed
    Given base-proven (a) and independently-verified-harness (b) are both confirmed
    When the responsible gate is flipped
    Then subsequent canary-passed, snapshot-ready changes may be promoted automatically
    And every such automatic promotion still passes through AE2–AE5 unchanged
```
**DoD:** the two preconditions are checked and recorded; the AE5 forced-failure drill is run and
its evidence captured; only then is AE4's flag flipped; TDD + BDD green (`gate1_responsible_gate.
feature`); verified on 10.0.1.11 (with the gate OFF a change is proposed not promoted; after the
documented flip, a change promotes automatically and still passes AE2–AE5). **Flipping the flag is
the final act of the epic — nothing before it grants auto-deploy.**
**Files:** `src/applicant/app/config.py` *(the flag lives here / on the bridge — flipped, not
newly-authored)*, `docs/agents-epic-build-plan.md` *(this file — record the drill evidence +
authorization)*, BDD steps *(extend, wire `gate1_*.feature`)*.
**Depends on:** RC1 (signals), AE2, AE3, AE4, AE5 (all built + AE5 drill run).

---

## Why this order honors the directive

- **Both agents build in parallel from Wave 1** (RC1 ‖ AE1), satisfying backlog Q10 "start both now."
- **The full 4-layer harness lands and is verified before auto-deploy:** layers 1+2 (`H1`, Wave 1),
  layers 3+4 (`H2`, Wave 3), the AE stages that drive them (`AE2`–`AE5`, Waves 2–4), and the
  forced-failure rollback drill (`AE5`, Wave 4) all precede any auto-promote.
- **Auto-deploy is inert until the very end:** AE4 ships the flag OFF (propose-only) in Wave 3; only
  `GATE-1` in Wave 4 — after base-proven (a) and harness-verified (b) both hold — authorizes the
  flip. There is no wave in which a self-deploying agent is loose on an unstable base.
- **Guardrails are structural, not procedural:** the never-auto-submit boundary
  (`FinalApprovalService` is never granted an AE caller) and never-destroy-user-data
  (snapshot-before-promote) hold in every wave, per ADR-0009 Guardrails + the epic-wide BDD in
  `tests/bdd/features/agents/epic_self_improving_agents.feature`.
- **Every slice keeps the standing conventions:** DoR + AC-as-BDD + DoD, full TDD+BDD (red before
  green), verified on the running 10.0.1.11 instance, resilient to a fresh install.
