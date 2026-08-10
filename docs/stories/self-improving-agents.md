# Epic — Self-Improving Product (Reflection Coach + Automation Engineer)

**Epic ID:** EPIC AGENTS (`docs/APPLICANT-BACKLOG.md`)
**Status:** Sliced, ready for build (RC + AE in parallel per Q10; AE auto-promote OFF until the
responsible gate clears — see GATE-1)
**Created:** 2026-08-10
**Architecture:** [`docs/adr/0009-self-improving-agents.md`](../adr/0009-self-improving-agents.md)
**Extends:** [`docs/stories/self-healing.md`](self-healing.md) (EPIC SELF-HEAL) — see that ADR's
"Relation to ADR-0008" section for the slice-by-slice mapping; this doc does not re-slice
anything SELF-HEAL already owns.
**BDD runner:** `pytest-bdd` (`pyproject.toml`; `bdd_features_base_dir = "tests/bdd/features"`,
markers `bdd`/`pending`, the latter mapped to non-strict `xfail` by
`tests/bdd/conftest.py::pytest_bdd_apply_tag`).

---

## Story

**As** the product owner running Applicant unattended,
**I want** the product to evaluate whether it's actually getting me hired — not just producing
volume — and to autonomously build and ship the fixes/features that keep it working and
improving,
**So that** the product gets better at its job over time without me manually tuning criteria,
babysitting a backlog, or hand-holding a coding agent through every change.

Product owner's framing (verbatim, `docs/APPLICANT-BACKLOG.md` line 48): *"Applicant
continuously evaluates its own effectiveness and improves itself — extending SELF-HEAL from
detect→remediate to reflect→strategize and build→ship."*

---

## Epic-wide DoR

- [x] ADR-0009 accepted-in-draft — two-agent architecture designed to the product owner's 10
      confirmed decisions; existing seams grounded by file; ADR-0008 relationship mapped
      slice-by-slice; guardrails + responsible gate defined.
- [x] Each slice below scoped with BDD AC.
- [ ] Kevin sign-off on slice order within RC and within AE (RC1/AE1 recommended first in each
      track — RC1 is the only RC slice with no dependency on anything else in this epic; AE1 is
      the bridge every other AE slice needs).
- [ ] Per-slice DoR items (below) satisfied before that slice starts.
- [ ] GATE-1's preconditions tracked explicitly — AE2-AE5 may build/canary/propose from the
      start, but AE's auto-promote step stays behind GATE-1 regardless of which AE slices are
      individually done (see GATE-1).

## Epic-wide AC — BDD (executable spec, epic-level guardrails)

These six scenarios are the guardrail spec every RC/AE slice must hold, restated here as
complete Gherkin and scaffolded at
[`tests/bdd/features/agents/epic_self_improving_agents.feature`](../../tests/bdd/features/agents/epic_self_improving_agents.feature).

```gherkin
Feature: The product improves itself without a human tuning it or babysitting deploys

  Scenario: The Automation Engineer never auto-submits a user's application
    Given any action the Automation Engineer takes, in development, canary, or production
    Then it never calls the final-approval submit path on the user's behalf
    And a user's application is only ever submitted by an explicit user decision or an explicit
      per-application auto-submit opt-in the user set themselves

  Scenario: Neither agent ever destroys user data
    Given any action the Reflection Coach or the Automation Engineer takes
    Then no Application, JobPosting, credential, or document is ever deleted as a side effect
    And any data-affecting change the Automation Engineer ships is reversible by a snapshot taken
      before it was applied

  Scenario: A global kill switch halts both agents immediately
    Given the global kill switch is engaged
    When the Reflection Coach's next evaluation cycle or the Automation Engineer's next pipeline
      stage would run
    Then it does not run
    And the halt is visible on the activity feed

  Scenario: A single proposed action can be vetoed without killing everything else
    Given a specific action is pending on the shared backlog queue or the activity feed
    When the user vetoes that one action
    Then only that action is blocked
    And every other in-flight or queued action continues unaffected

  Scenario: Every new piece of functionality is communicated proactively as it is built
    Given the Automation Engineer starts building a new capability
    When it begins the build (not after it ships)
    Then the user receives a proactive notification describing what is being built and why
    And the notification is visible on the activity feed with an audit entry

  Scenario: A build is canaried before it is ever promoted to production
    Given the Automation Engineer has a change ready to ship
    When it attempts to promote the change
    Then it first deploys to the disposable e2e test instance
    And the full test suite and a browser monkey-crawl both pass against that instance
    And only then is the change promoted to production, with a pre-promotion snapshot taken
    And a failed post-promotion health check triggers an automatic rollback to that snapshot
```

---

## Gaps this epic must account for (do not assume covered)

Grounded by absence (grepped/read, not assumed); carried here so no slice silently assumes a
mechanism that doesn't exist yet:

1. **No programmatic bridge into the vendored coding stack.** `a0-applicant/agents/{agent0,
   coder,coder-cloud,explorer,explorer-cloud,reviewer,security-auditor,debugger,
   test-engineer}/` and `config/intel_tiers.yaml`/`intel_orchestration.yaml` already exist and
   are contract-tested, but nothing under `src/applicant/` calls into them
   (`grep -rl "automation_engineer\|reflection_coach" src/` → zero hits). AE1 builds this bridge
   from scratch — it is the epic's single biggest new-build item.
2. **No snapshot/auto-rollback control plane.** `scripts/updater-daemon.sh` only runs
   `scripts/update.sh --apply` forward; nothing today snapshots before a deploy or reverts one
   automatically. AE4/AE5 build this as a new, narrow sibling of the updater's existing
   request/status control-plane pattern.
3. **The audit panel is read-only.** `src/applicant/app/routers/audit.py` has no "revert this
   action" endpoint. RC's revert is nearly free (it's `CriteriaService.edit_criteria(
   clear_learned=True)` behind a button); AE's revert needs the new snapshot-restore primitive
   from Gap 2 wired to a button. Both need new API surface either way.
4. **No shared backlog queue exists.** RC→AE's "routine" handoff (Q4) needs a new durable queue;
   the closest existing shape is `CurationService`'s `MemoryProposal`/`SkillProposal`
   staged-for-approval pattern, which RC3 follows but does not literally reuse (different
   payload, different consumer).
5. **No global kill switch or per-action veto exists at this scope.** The automated-work gate
   (`agent_loop.py`/`scheduler.py`) is real but scoped to campaign automation
   (discovery/scoring/drafting), not to RC's tweaks or AE's build/deploy pipeline. SH-1 builds
   the broader switch new, modeled on that gate's shape.
6. **`monkey_crawl.py` is still not a live detector** (ADR-0008's own gap, restated in
   `docs/stories/self-healing.md` Gap 4) — AE4 depends only on it being *invocable
   non-interactively against a disposable instance*, which already works
   (`HANDOFF.md` §5.4's `docker exec` recipe); AE4 does not need or attempt the live-detector
   wiring ADR-0008 left open.
7. **AE's coding tier is unvalidated for autonomous production changes.** Local `Qwen3.6-27B`
   with DeepSeek-Flash/Pro escalation (R7) is meaningfully weaker than the Claude-piloted
   development this codebase is built with today. GATE-1 exists precisely because this is
   unproven, not as a formality — see ADR-0009 Consequences for the recommended validation
   approach and the stronger-tier fallback option.

---

## Slices — Agent A (Reflection Coach)

### RC1 — Effectiveness assessment (signals + cadence)

**Summary:** The daily + event-driven evaluation core. Aggregates response/interview rate,
velocity + time-in-stage, fit-score trend + approve/discard/edit feedback, and funnel-vs-deadline
progress per campaign, then produces a scored semantic assessment via one LLM call over the
aggregated (deterministic) signals — mirroring `CriteriaService._summarize`'s token-frugal split
(LLM only for the human-readable judgment). Read-only: RC1 assesses, it does not yet act (RC2).

**DoR:**
- [ ] Confirm the four new event-driven trigger conditions (rejection, response-rate/velocity
      stall, N-apps-sent, fit-score trend shift) map to existing emission points
      (`ApplicationStateChanged`, `OutcomeRecorded`) with no new instrumentation beyond the
      trigger check itself.
- [ ] `Scheduler`'s "once per campaign per UTC day" idiom (the digest/curation-nudge pattern)
      confirmed as RC1's daily-cadence template.

**AC (Gherkin):**

```gherkin
Feature: Reflection Coach effectiveness assessment

  Scenario: A daily evaluation runs once per campaign per day
    Given a campaign has been active for at least one day
    When the scheduler's daily tick fires
    Then the Reflection Coach produces one scored effectiveness assessment for that campaign
    And re-ticking the same day does not produce a second assessment

  Scenario: An event-driven trigger fires an out-of-cadence evaluation
    Given a rejection, a response-rate/velocity stall, N applications sent, or a fit-score trend
      shift occurs
    When that event is detected
    Then the Reflection Coach evaluates immediately, independent of the daily cadence

  Scenario: The assessment covers every required signal
    Given an effectiveness assessment runs
    Then it includes response/interview rate, velocity and time-in-stage, fit-score trend with
      user approve/discard/edit feedback, and funnel progress against the deadline
    And the result is recorded in the audit trail
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a forced daily tick + a forced event trigger both produce a visible,
      audited assessment for a real campaign.
- [ ] Resilient to a fresh install: with no campaign history, the assessment degrades gracefully
      (no crash, an honest "insufficient data" result) rather than asserting a false signal.

---

### RC2 — Auto-apply reversible tweaks

**Summary:** RC1's assessment becomes action. Non-integral criteria/strategy tweaks auto-apply
via `CriteriaService.apply_learned_adjustment` (existing seam, L66-89); integral fields
(`titles`/`locations`/`salary_floor`) are staged via the existing `proposed_integral` path in
`learned_adjustments`, needing the existing confirmation gate — RC2 never bypasses it.

**DoR:**
- [ ] RC1 merged (produces the assessment RC2 acts on).
- [ ] Confirmed which "strategy tweaks" (sources/thresholds/pacing/throughput) route through
      `CriteriaService` vs. an existing per-campaign settings surface — no new config store
      either way (per ADR-0009 Decision, Agent A "Authority").

**AC (Gherkin):**

```gherkin
Feature: Reflection Coach auto-applies transparent, reversible tweaks

  Scenario: A non-integral learned tweak auto-applies and is visible
    Given the effectiveness assessment recommends a non-integral criteria adjustment
    When the Reflection Coach applies it
    Then CriteriaService.apply_learned_adjustment records the delta and a human-readable summary
      in learned_adjustments
    And the change is visible to the user without them having to ask

  Scenario: An integral-field tweak is proposed, not silently applied
    Given the effectiveness assessment recommends changing titles, locations, or salary_floor
    When the Reflection Coach files the recommendation
    Then it is staged as a proposed_integral learned adjustment
    And it requires explicit user confirmation before it takes effect

  Scenario: Any auto-applied tweak is one-click reversible
    Given a tweak the Reflection Coach auto-applied
    When the user reverts it
    Then CriteriaService.edit_criteria(clear_learned=True) restores the prior state
    And the reversal is itself audited
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a real auto-applied tweak is visible in `learned_adjustments` and
      reversible via the existing clear-learned path (button wiring may lag; the service call
      must work end-to-end).
- [ ] Resilient to a fresh install: with automation off (kill switch or automated-work gate
      closed), RC2 proposes nothing and applies nothing.

---

### RC3 — Programmatic-need handoff to the Automation Engineer

**Summary:** When RC's assessment surfaces a need only a code/config change can fix (not a
criteria/strategy tweak), it's filed to AE — routine work onto a new shared backlog queue,
urgent work as a direct handoff bypassing the queue (mirrors `NotificationService.notify_error`'s
IMMEDIATE-bypasses-queuing precedent).

**DoR:**
- [ ] RC1 merged (the assessment is the source of programmatic needs).
- [ ] AE1's task-intake shape agreed (RC3's handoff is one of AE1's three trigger sources — see
      AE1) so the queue schema and the direct-handoff call shape aren't designed twice.

**AC (Gherkin):**

```gherkin
Feature: Reflection Coach files programmatic needs to the Automation Engineer

  Scenario: A routine programmatic need is queued
    Given the effectiveness assessment identifies a need only a code or config change can fix
    When it is not marked urgent
    Then a ProgrammaticNeedRaised event is filed onto the shared backlog queue
    And it is visible to the Automation Engineer's task intake without further action

  Scenario: An urgent programmatic need bypasses the queue
    Given the effectiveness assessment identifies an urgent programmatic need (e.g. a source
      newly broken, blocking the whole funnel)
    When it is marked urgent
    Then it is handed directly to the Automation Engineer's task intake
    And it does not wait for a queue poll cycle
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a forced routine need lands on the queue and is later picked up by
      AE1's intake; a forced urgent need reaches intake immediately.
- [ ] Resilient to a fresh install: an empty queue and zero programmatic needs is a normal,
      non-error state.

---

## Slices — Agent B (Automation Engineer)

### AE1 — Task intake + vendored coding-stack bridge

**Summary:** The epic's central new-build (Gap 1). A `src/applicant` service that (a) accepts a
task from three sources — user-initiated, RC (queue or direct handoff, RC3), or self-detected
(subscribing to ADR-0008's `RemediationRequested` and any AE-specific detector) — and (b) hands
it to the **existing** `a0-applicant` `agent0` overseer profile via the same
`call_subordinate`/`orchestrate`/`subagent` mechanism a human operator uses today, targeting the
**existing** Plane A tier topology (`config/intel_tiers.yaml`/`intel_orchestration.yaml`) —
local `coder`/`explorer`/`test-engineer` for the bulk work, cloud `reviewer`/`security-auditor`/
`debugger` per the existing R1-R9 escalation rules. No new model plane, no new agent framework.

**DoR:**
- [ ] Confirmed callable entry point into the `agent0` overseer from outside its own chat UI
      (task-scoped invocation, not an interactive session) — this is the one piece of the bridge
      that is genuinely unproven and must be spiked before the slice is built out.
- [ ] Task schema agreed across all three intake sources (user/RC/self) so AE2-AE5 build against
      one shape.

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer task intake and coding-stack bridge

  Scenario: A user-initiated task reaches the bridge
    Given the user requests a change through the product
    When the request is submitted
    Then it is accepted as an Automation Engineer task
    And it is routed to the vendored agent0 overseer with a self-contained instruction

  Scenario: A Reflection-Coach-filed task reaches the bridge
    Given a ProgrammaticNeedRaised event (queued or direct-handoff, RC3)
    When the Automation Engineer's intake consumes it
    Then it is accepted as an Automation Engineer task with the same shape as a user-initiated one

  Scenario: A self-detected task reaches the bridge
    Given a RemediationRequested event (ADR-0008) or an Automation-Engineer-specific detector fires
    When the Automation Engineer's intake consumes it
    Then it is accepted as an Automation Engineer task

  Scenario: The bridge delegates to the existing local/cloud tier roster, not a new one
    Given an accepted task requires implementation
    When the bridge dispatches it
    Then it uses the existing coder/explorer/test-engineer/reviewer/security-auditor/debugger
      profiles and the existing tier topology
    And no parallel coding-agent framework is instantiated
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: one task from each of the three intake sources reaches the bridge
      and dispatches to the vendored roster (propose-only outcome is fine at this slice — AE2-AE5
      add the gates around what the bridge returns).
- [ ] Resilient to a fresh install: with the vendored roster unreachable (e.g. `a0` shell not
      yet up), intake fails safe (queues/retries, does not crash the engine).

---

### AE2 — Hard TDD/BDD gate

**Summary:** No task the bridge (AE1) completes is eligible for canary/promote unless its own
unit tests AND its BDD scenarios pass — mirrors the standing project-wide convention
(`docs/APPLICANT-BACKLOG.md` "Delivery = full TDD + BDD") enforced specifically as a hard gate
on AE's own output.

**DoR:**
- [ ] AE1 merged (produces a completed task's diff/commit for the gate to check).

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer TDD/BDD hard gate

  Scenario: A change with failing tests is blocked from canary
    Given the Automation Engineer completes a task
    When its unit tests or its BDD scenarios fail
    Then the change is not eligible for canary or promotion
    And the failure is recorded in the audit trail with the specific failing check

  Scenario: A change with all green checks proceeds
    Given the Automation Engineer completes a task
    When its unit tests and its BDD scenarios both pass
    Then the change becomes eligible to enter the canary stage (AE3)
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a deliberately-broken AE-authored change is blocked; a
      genuinely-green one proceeds.
- [ ] Resilient to a fresh install: the gate runs against the project's real test runner
      (`.venv/bin/pytest`) with no special-cased AE exemption.

---

### AE3 — Canary harness (e2e instance + monkey-crawl)

**Summary:** A gate-passed change (AE2) is built and deployed to a disposable instance
(generalizing the documented `applicant-e2e` recipe, `HANDOFF.md` §5.2) and verified with the
full suite plus a browser monkey-crawl (`journey_via_sidebar.py` + `scripts/monkey_crawl.py`,
`HANDOFF.md` §5.4) before it is eligible for promotion.

**DoR:**
- [ ] AE2 merged (only gate-passed changes reach canary).
- [ ] The `applicant-e2e` build/run/poll-`/login`/teardown sequence scripted non-interactively
      (today it's a documented manual recipe).

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer canaries every change before promotion

  Scenario: A change deploys to the disposable e2e instance first
    Given a change has passed the TDD/BDD gate
    When the Automation Engineer attempts to promote it
    Then it first builds and deploys the change to a disposable e2e instance
    And it does not touch the production instance yet

  Scenario: The full suite and a monkey-crawl both gate promotion
    Given the change is running on the disposable e2e instance
    When the canary verification runs
    Then the full test suite runs against it
    And a browser monkey-crawl runs against it
    And promotion proceeds only if both are green

  Scenario: A canary failure blocks promotion and is reported
    Given the canary verification fails (suite or monkey-crawl)
    When the failure is detected
    Then the change is not promoted
    And the disposable instance's failure detail is recorded in the audit trail
    And the user is proactively notified
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a real AE-authored change is canaried end-to-end on a disposable
      instance with both checks actually executing (not stubbed).
- [ ] Resilient to a fresh install: canary infra (disposable instance lifecycle) is self-
      contained and does not require a pre-existing manually-run instance.

---

### AE4 — Snapshot + promote

**Summary:** A canary-passed change (AE3) is promoted to production, preceded by a snapshot
(image tag retained + a DB/schema snapshot mirroring `scripts/install.sh`'s existing
pre-migration snapshot step) so every promotion has an instant revert point.

**DoR:**
- [ ] AE3 merged (only canary-passed changes reach promote).
- [ ] Snapshot mechanism designed: image tag retention (already implicit in how
      `docker compose build a0` tags images) + a scripted DB/schema snapshot step, new.

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer snapshots before every promotion

  Scenario: A snapshot is taken immediately before promotion
    Given a change has passed canary
    When the Automation Engineer promotes it to production
    Then a snapshot of the pre-promotion image and database state is taken first
    And the snapshot is retained and addressable for a rollback

  Scenario: Promotion without a snapshot never happens
    Given the snapshot step fails for any reason
    When promotion would otherwise proceed
    Then promotion is blocked
    And the failure is recorded and the user is proactively notified
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a real promotion produces a retained, addressable snapshot before
      the production containers are recreated.
- [ ] Resilient to a fresh install: on a brand-new instance with no prior snapshot, the first
      promotion still snapshots correctly (no "assumes a prior snapshot exists" bug).

---

### AE5 — Health-gated auto-rollback

**Summary:** After promotion (AE4), post-deploy health checks (`/healthz`,
`/api/health/capabilities`) are polled for a defined window; a failure triggers an automatic
revert to the pre-promotion snapshot (AE4) with no human action required.

**DoR:**
- [ ] AE4 merged (auto-rollback needs a snapshot to roll back to).
- [ ] Post-deploy health-check window + failure criteria defined (which checks, how long, how
      many consecutive failures).

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer auto-rolls-back a failed promotion

  Scenario: A healthy promotion is left in place
    Given a promotion completes
    When the post-deploy health checks pass through the monitoring window
    Then the promotion stands
    And no rollback occurs

  Scenario: A failed health check triggers automatic rollback
    Given a promotion completes
    When a post-deploy health check fails within the monitoring window
    Then the Automation Engineer automatically reverts to the pre-promotion snapshot
    And zero human action was required
    And the rollback is recorded in the audit trail and the user is proactively notified

  Scenario: Rollback itself is verified, not assumed
    Given an automatic rollback has been triggered
    When the rollback completes
    Then the production instance's health checks pass again against the restored snapshot
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11 by fault injection: promote a deliberately-broken build (behind a
      test flag) and confirm auto-rollback actually fires and restores health — this specific
      drill is also GATE-1's independent-verification precondition (see GATE-1).
- [ ] Resilient to a fresh install: rollback path does not assume any state beyond the one
      snapshot taken at AE4.

---

### AE6 — Proactive communication

**Summary:** Every new piece of functionality is communicated to Kevin as it's being built, not
after (Q7 hard rule) — a new `NotificationService` kind fired at task-acceptance (AE1) and again
at ship (post-AE5), reusing the existing escalation ladder.

**DoR:**
- [ ] AE1 merged (task acceptance is the first proactive-comms trigger point).
- [ ] AE5 merged (successful promotion is the second).

**AC (Gherkin):**

```gherkin
Feature: Automation Engineer communicates proactively, not after the fact

  Scenario: Starting a build is announced immediately
    Given the Automation Engineer accepts a task and begins building it
    When the build starts
    Then a proactive notification is sent describing what is being built and why
    And this happens before the build completes, not after

  Scenario: A shipped feature is announced on promotion
    Given a change is successfully promoted and passes its health checks
    When the promotion is confirmed healthy
    Then a proactive notification confirms what shipped
    And it is visible on the activity feed with the linked audit entries
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a real AE task produces a start notification before completion and
      a ship notification after a healthy promotion.
- [ ] Resilient to a fresh install: notification delivery degrades exactly like existing
      `NotificationService` paths do when no channel is configured (no crash).

---

## Slice — Shared oversight

### SH1 — Activity feed, revert buttons, kill switch, per-action veto

**Summary:** The oversight surface both agents report through: a live activity feed over the
existing audit trail, revert buttons (RC: `clear_learned=True`; AE: the AE4/AE5 snapshot-restore
primitive), a global kill switch halting both agents, and a per-action veto blocking one queued/
pending action without affecting others.

**DoR:**
- [ ] RC2 merged (revert button needs `CriteriaService`'s existing reversal call to wire to).
- [ ] AE4/AE5 merged (AE's revert button needs the snapshot-restore primitive to wire to).
- [ ] Kill-switch scope confirmed as broader than the existing automated-work gate (campaign
      automation only) — SH1 builds a new switch, modeled on that gate's shape, not a repoint of
      it.

**AC (Gherkin):**

```gherkin
Feature: Shared oversight for the Reflection Coach and the Automation Engineer

  Scenario: The activity feed shows every RC/AE action with a working revert
    Given the Reflection Coach or the Automation Engineer has taken a recorded action
    When the user views the activity feed
    Then the action is listed with its audit detail
    And a revert control is available and functional for reversible actions

  Scenario: The kill switch halts both agents
    Given the global kill switch is engaged
    Then the Reflection Coach performs no further evaluations or auto-applies
    And the Automation Engineer performs no further build, canary, or promote steps
    And re-engaging the switch resumes normal operation without requiring a restart

  Scenario: A per-action veto blocks exactly one action
    Given multiple actions are queued or pending across both agents
    When the user vetoes one specific action
    Then that action does not proceed
    And every other action continues on its normal path

  Scenario: A daily digest summarizes both agents' activity
    Given a day of Reflection Coach and Automation Engineer activity
    When the daily digest is delivered
    Then it includes a summary of tweaks applied, tasks built/shipped, and anything vetoed or
      rolled back
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: a real RC tweak and a real AE-shipped change both appear on the
      activity feed with working reverts; the kill switch demonstrably halts both; a veto blocks
      one action without affecting a concurrent one.
- [ ] Resilient to a fresh install: kill switch defaults OFF-for-automation (safe default,
      mirrors the automated-work gate's closed-until-configured default) with both agents inert
      until explicitly enabled.

---

## GATE-1 — Autonomous-deploy responsible gate (Q10)

**Not a slice — a hard precondition on AE4/AE5's auto-promote path**, tracked separately because
it gates a capability rather than building one.

**Preconditions (both required):**
- [ ] **(a) Core pipeline stability:** the review queue is stably full and relevant — observable
      via RC1's own funnel signals (discovered→drafted→submitted→responded→interview→offer)
      showing sustained healthy throughput, not a one-off good day.
- [ ] **(b) Safety harness independently verified:** AE2 (TDD/BDD gate), AE3 (canary), AE4
      (snapshot), and AE5 (auto-rollback) are all built AND a real forced-failure drill (AE5's
      DoD) has been run and confirmed the rollback path actually fires and restores health — not
      just unit-tested in isolation.

**Until both hold:** AE builds, canaries, and proposes a promotion; a human approves the actual
production promote. This is a config flag on the AE1 bridge service, flippable without redesign
(ADR-0009 Decision, "Responsible gate").

**Recommended additional validation (ADR-0009 Consequences — not a hard blocker, a risk
mitigation):** before flipping the gate, run AE in propose-only mode against a representative
slice of real backlog items and compare its output against the bar Claude-piloted development
already clears (full suite passes untouched, its own BDD AC holds, a `reviewer`/
`security-auditor` pass catches what a human reviewer would). If local-`Qwen`-plus-DeepSeek
quality proves insufficient, the stronger-tier option is the same env-gated-optional-rung
pattern MODEL-RESILIENCY already established (off without a key) — not a new mechanism.

**AC (Gherkin):**

```gherkin
Feature: Autonomous deploy stays gated until the product and the harness are both proven

  Scenario: Auto-promote is off by default
    Given the Automation Engineer has a canary-passed, snapshot-ready change
    When GATE-1's preconditions have not both been confirmed
    Then the change is proposed for a human to approve
    And it is not promoted automatically

  Scenario: Auto-promote activates only after both preconditions are confirmed
    Given the core pipeline stability precondition and the independently-verified safety-harness
      precondition are both confirmed
    When the responsible gate is flipped
    Then subsequent canary-passed, snapshot-ready changes may be promoted automatically
    And every such automatic promotion still passes through AE2-AE5 unchanged
```

---

## BDD framework + scaffold status

Per this task's scope (**docs + scaffolds only, no step definitions, no product code**), eleven
`.feature` files were added under `tests/bdd/features/agents/` — the epic-wide guardrail
scenarios plus one file per slice (RC1-RC3, AE1-AE6, SH1) and one for GATE-1, all scenarios
tagged `@pending`, following the exact convention `docs/stories/self-healing.md` established:

- `tests/bdd/features/agents/epic_self_improving_agents.feature`
- `tests/bdd/features/agents/rc1_effectiveness_assessment.feature`
- `tests/bdd/features/agents/rc2_auto_apply_reversible_tweaks.feature`
- `tests/bdd/features/agents/rc3_programmatic_need_handoff.feature`
- `tests/bdd/features/agents/ae1_task_intake_bridge.feature`
- `tests/bdd/features/agents/ae2_tdd_bdd_gate.feature`
- `tests/bdd/features/agents/ae3_canary_harness.feature`
- `tests/bdd/features/agents/ae4_snapshot_promote.feature`
- `tests/bdd/features/agents/ae5_auto_rollback.feature`
- `tests/bdd/features/agents/ae6_proactive_comms.feature`
- `tests/bdd/features/agents/sh1_oversight.feature`
- `tests/bdd/features/agents/gate1_responsible_gate.feature`

**Important — these are intentionally NOT wired yet.** `pytest-bdd` only collects a `.feature`
file's scenarios when a step module calls `scenarios("path/to/file.feature")` (established
convention: every file under `tests/bdd/features/enhancements/` is bound from a
`tests/bdd/steps/test_enh_*_steps.py` module; `tests/bdd/features/self_healing/*.feature` remains
unbound for the same reason as of this doc). Since step definitions are out of scope here, these
twelve files exist as **documentation-grade Gherkin only** — pytest will not run or report them
at all until a step module wires them via `scenarios(...)`, so they cannot break CI in their
current state (stronger than "skipped" — currently uncollected).

**When TDD build begins on a slice:** create `tests/bdd/steps/test_self_improving_agents_steps.py`
following the established pattern (untagged scenarios are real regression coverage that must
pass; `@pending`-tagged scenarios get an honest probe at the real target, never `assert True`),
call `scenarios(...)` for that slice's feature file, and drop `@pending` scenario-by-scenario as
behavior actually ships.

## Notes / dependencies

- RC1 has no dependency within this epic; it is the natural first RC slice.
- RC2 depends on RC1; RC3 depends on RC1 and (for the queue schema) coordinates with AE1.
- AE1 is the dependency root for AE2-AE6 — it is the "genuine new build" ADR-0009 calls out as
  the epic's single biggest item, and should be prioritized accordingly even though slices can
  nominally build in parallel.
- AE3 depends on the `applicant-e2e` manual recipe (`HANDOFF.md` §5.2) being generalized into a
  script — today it is a human-run set of shell commands, not yet automatable as-is without that
  scripting step.
- AE4/AE5 depend on each other in sequence (snapshot before promote; rollback needs a snapshot to
  target) and both must exist before GATE-1's harness-verification precondition can be checked.
- SH1 depends on RC2 and AE4/AE5 for its revert buttons to have something real to call; the
  kill-switch and veto halves of SH1 have no such dependency and can be built first.
- GATE-1 is not a slice with independent value — it only matters once AE2-AE5 exist, and should
  not be treated as "done" until the forced-failure rollback drill in AE5's DoD has actually been
  run, not just coded.
- None of these slices may be started as "done" without satisfying `docs/APPLICANT-BACKLOG.md`'s
  standing conventions: DoR + AC-as-BDD + DoD, full TDD+BDD (red before green), verified on the
  running 10.0.1.11 instance, resilient to a fresh install.
