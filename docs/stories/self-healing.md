# Epic — Autonomous Self-Healing (deterministic detection → agentic remediation)

**Epic ID:** EPIC SELF-HEAL (`docs/APPLICANT-BACKLOG.md`)
**Status:** Sliced, ready for build (pending Kevin sign-off on slice order)
**Created:** 2026-08-10
**Architecture:** [`docs/adr/0008-autonomous-self-healing.md`](../adr/0008-autonomous-self-healing.md)
**BDD runner:** `pytest-bdd` (already in `pyproject.toml`); scaffold status — see [BDD framework](#bdd-framework--scaffold-status) below.

---

## Story

**As** the product owner running Applicant unattended 24/7,
**I want** the engine to detect its own runtime failures deterministically and dispatch an AI
agent with full tool access to diagnose and correct them — including having the remote/cloud
LLM repair the local LLM when the local model is degraded or wedged —
**So that** I never have to open a terminal, SSH in, or manually restart anything to keep the
job-search pipeline running; the product heals itself the way a senior on-call engineer would,
minus the human.

Product owner's principle (verbatim, `docs/APPLICANT-BACKLOG.md` line 23; see ADR-0008 Context
for the full quote): *"The human must NEVER have to step in to fix the product — the AI does
ALL the fixing because it has ALL the tools."*

---

## Epic-wide DoR

- [x] ADR-0008 accepted-in-draft — detection signals catalogued and file-cited; remediator
      authority + guardrails defined; remote→local repair path specified; audit + fail-safe
      defined (see ADR-0008 §Decision, layers 1-5).
- [x] Each slice below scoped with BDD AC and a fault-injection approach.
- [ ] Kevin sign-off on slice order (S1 first is recommended — it's the only slice with a
      live incident precedent already root-caused, SCORE-P0/MODEL-RESILIENCY).
- [ ] Per-slice DoR items (below) satisfied before that slice starts.

## Epic-wide AC — BDD (executable spec, epic-level)

These five scenarios are the same five named in `docs/APPLICANT-BACKLOG.md`'s EPIC SELF-HEAL
AC block; they are restated here as complete Gherkin (the backlog gives the prose, this is the
executable form) and scaffolded at
[`tests/bdd/features/self_healing/epic_self_healing.feature`](../../tests/bdd/features/self_healing/epic_self_healing.feature).

```gherkin
Feature: Autonomous self-healing — the product never needs a human to fix it

  Scenario: The remote LLM repairs the local LLM
    Given the local LLM is wedged or unreachable
    When an inference or scoring call fails deterministically
    Then the system escalates inference to the remote LLM
    And a remediation action is triggered that restores the local LLM
    And zero human action was required
    And an audit entry records the detection, the action, and the outcome

  Scenario: A deterministic failure signature triggers the detect-remediate-audit loop
    Given a deterministic error signature fires (panel JS error, migration failure, endpoint
      5xx, a stuck or starved queue, scorer degrade-to-embeddings, or an open discovery
      circuit breaker)
    When the signature is detected
    Then an AI remediator is invoked with tool access to diagnose and correct it
    And the action taken and its outcome are recorded in the audit trail

  Scenario: Remediation is bounded and fails safe
    Given a remediation attempt is in progress
    When its bounded retry budget is exhausted
    Then the system fails safe — it degrades gracefully and alerts
    And it never loops infinitely
    And it never loses data as a result of the failed remediation

  Scenario: Guardrails hold even inside self-repair
    Given any remediation action, successful or not
    Then no user application is ever auto-submitted as a side effect
    And no user data is ever deleted as a side effect

  Scenario: No human is required overnight
    Given a failure class covered by a detector occurs while unattended overnight
    When the failure occurs
    Then the product returns to a healthy state with no human intervention
    And the audit trail evidences the full detect-remediate-recover sequence
```

---

## Gaps this epic must account for (do not assume covered)

Grounded in ADR-0008's detector catalogue; carried here so no slice silently assumes a
mechanism that doesn't exist yet:

1. **Local-service restart channel** — nothing in the stack today can restart a single service
   (e.g. the vLLM box) short of the updater sidecar's full-stack `update.sh --apply`
   (`scripts/updater-daemon.sh`). S1 needs a new, narrow, bounded sibling of that control-plane
   pattern. This is a genuine new build, not reuse.
2. **Idle-in-transaction DB probe** — no existing detector (grepped `idle_in_transaction` /
   `statement_timeout` / `pool_timeout` across `src/`: zero hits). S5 needs this built from
   scratch (a scheduled `pg_stat_activity` query).
3. **Migration-failure runtime signal** — `scripts/install.sh` catches a failed
   `alembic upgrade head` at install/update time only; nothing surfaces a live "schema behind /
   half-applied" signal to the running engine's health panel. Not owned by any single slice
   below; flagged for whoever picks up detector #6 in a future slice.
4. **`monkey_crawl.py` is offline-only** — it's a manually-invoked Playwright QA tool, not a
   live/periodic detector. S4 must decide between (a) running it on a schedule against the live
   instance, or (b) a lighter client-side error beacon, before panel-error detection can be
   "live."
5. **Remediating a code-level bug is out of scope for this epic.** A remediator that can
   restart services, re-score data, and reset counters cannot fix a JS logic bug at runtime —
   that requires a code change + redeploy. S4's scope is therefore detect + audit + safe
   mitigation (e.g. disable the one broken gadget) + alert, never a claimed "fix" of code. A
   future "AI writes the patch, updater sidecar redeploys it" loop is a materially bigger,
   separate capability and is explicitly not part of this epic.

---

## Slices

### S1 — Remote-repairs-local LLM

**Summary:** The remote/cloud LLM tier both serves inference as fallback (MODEL-RESILIENCY,
already in flight per `docs/APPLICANT-BACKLOG.md` line 54) and drives remediation of the local
model service when it's degraded, wedged, or unreachable.

**DoR:**
- [ ] MODEL-RESILIENCY fallback tier merged (`TierLadder` holds an optional cloud rung, env
      `LLM_FALLBACK_BASE_URL`/`_MODEL`/`_API_KEY`/`_PROVIDER`, off without a key).
- [ ] `ModelEndpointService`'s online/ping signal (`_fetch_models`/`_humanize_ping_error`,
      `src/applicant/application/services/model_endpoint_service.py`) confirmed reachable from
      the remediator.
- [ ] The scoped single-service-restart control-plane channel (Gap 1, above) designed: request/
      status handshake modeled on `scripts/updater-daemon.sh`, narrowed to "restart one named
      service" rather than a full-stack update.

**AC (Gherkin):**

```gherkin
Feature: Remote LLM repairs the local LLM

  Scenario: Inference escalates to remote when local is unreachable
    Given the local vLLM endpoint is unreachable
    When a scoring or chat call is dispatched through the tier ladder
    Then the call escalates to the remote fallback tier
    And the caller receives a valid result without LLMLadderExhausted being raised

  Scenario: The remote-tier remediator restarts the wedged local model
    Given the local vLLM endpoint has been reported unreachable for more than one detector cycle
    When the remediator (itself running on the remote tier, since local is down) diagnoses the endpoint
    Then it issues a bounded restart request against the local model service
    And the local endpoint eventually reports online again
    And zero human action was required
    And an audit entry links the detection, the restart action, and the recovery

  Scenario: Restart attempts are bounded and fail safe
    Given the local model restart action has failed its bounded retry budget
    When the budget is exhausted
    Then the system stops attempting restarts
    And it alerts via the existing notification path
    And it continues serving inference from the remote fallback tier in the meantime
```

**DoD:**
- [ ] TDD unit tests: tier-ladder escalation to the fallback tier (extends existing coverage
      around `openai_compatible.py`'s `complete()`), and the new bounded restart-action tool.
- [ ] BDD scenarios above green.
- [ ] Verified on 10.0.1.11 by fault injection (below).
- [ ] Resilient to a fresh install: fallback tier stays OFF (byte-identical to today) without a
      cloud key configured; the restart-action channel is inert with no local model wedged.

**Fault injection:** Pause or kill the vLLM container (or block network reachability to
`10.0.1.225:8000`). Assert: (a) the next scoring/chat call escalates to the remote tier and
completes; (b) the remediator issues a restart request against the local endpoint; (c) once the
container is restored, `ModelEndpointService` reports it online again and the tier ladder
resumes preferring local; (d) zero human action, verified entirely from the audit log.

---

### S2 — Detector event bus + audit store

**Summary:** Wire detector output onto the **existing** `DomainEventBus`
(`src/applicant/core/events.py`) and **existing** `AuditLogService`
(`src/applicant/application/services/audit_log_service.py`) — new `DomainEvent` subclasses and
`_ACTION_MAP` entries, not a new bus or store. Extend `BootHealth`
(`src/applicant/app/lifespan.py`) from boot-once to a periodic watchdog tick.

**DoR:**
- [ ] ADR-0008's detector catalogue (10 classes) reviewed; which classes S2 wires first agreed
      (recommend: the ones already emitting a typed signal — #1, #2, #5, #8 — before the two
      gaps, #9/#10).
- [ ] `event_bus`/`AuditLogService`/`ActionEvent` schema confirmed generic enough for new event
      types with no migration (it is — `ActionEvent` is keyed by an `action` string + payload).

**AC (Gherkin):**

```gherkin
Feature: Detector events flow onto the audit trail

  Scenario: A detector event is persisted as an audit entry
    Given a ScorerDegradedDetected event is emitted on the domain event bus
    When AuditLogService processes it
    Then an ActionEvent with action "detector_fired" appears in the audit trail
    And it is visible on the existing audit panel

  Scenario: Runtime invariants are checked continuously, not just at boot
    Given a runtime invariant already checked once at boot (e.g. a model endpoint's reachability)
    When the periodic watchdog tick runs
    Then its BootHealth-style status is refreshed
    And a status change (healthy to degraded, or back) emits a detector event

  Scenario: A remediation outcome is audited and linked to its trigger
    Given a remediation action completes, successfully or not
    When its outcome is recorded
    Then a paired ActionEvent captures the outcome
    And it references the originating detector event
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11: forcing one existing detector (e.g. the discovery circuit breaker)
      produces a visible audit-panel entry with no human polling required to notice it.
- [ ] Resilient to a fresh install: new event types register cleanly on an empty audit log, no
      migration required.

**Fault injection:** Force three consecutive discovery-source failures
(`SourceCircuitBreaker.record(key, ok=False)` × `failure_threshold`) so the breaker opens.
Assert an `ActionEvent` lands in the audit trail identifying the source and the open state,
with no human action needed to observe it.

---

### S3 — Scorer-degrade auto-heal / auto-rescore

**Summary:** Builds directly on SCORE-P0's bounded-retry mechanism
(`src/applicant/application/services/scoring_service.py`, `_persist_or_defer`). Today a single
posting retries up to `DEFAULT_MAX_TRANSIENT_RETRIES` times and then accepts the degraded
score. S3 adds a remediator that (a) recognizes the *systemic* pattern (many postings degrading
in the same tick — the LLM itself is down, not one flaky posting) and diagnoses proactively
instead of waiting for each posting to individually exhaust its budget, and (b) re-sweeps
already-degraded postings once the LLM is confirmed healthy again.

**DoR:**
- [ ] SCORE-P0 merged (bounded-retry-then-persist-degraded fix; currently uncommitted on this
      branch per `git status` at ADR-0008 authoring time).
- [ ] S1 (or at minimum `ModelEndpointService`'s online signal) available so the remediator can
      distinguish "the LLM is down" from "one posting is pathological."

**AC (Gherkin):**

```gherkin
Feature: Scorer degrade-to-embeddings self-heals

  Scenario: A systemic degrade pattern is diagnosed, not treated as isolated noise
    Given multiple postings degrade to the embedding fallback within the same scoring tick
    When the remediator observes the pattern
    Then it checks whether the LLM tier is actually down (not just one posting misbehaving)
    And it records its diagnosis in the audit trail

  Scenario: A recovered LLM triggers an automatic re-score sweep
    Given the LLM was unreachable and has since recovered
    When the remediator detects the recovery
    Then it triggers a bounded re-score sweep of postings still sitting at a degraded score
    And no human re-triggers the sweep

  Scenario: Zero viable postings after a scoring sweep is treated as a self-heal target
    Given a scoring sweep leaves the campaign with zero viable postings
    When this is detected
    Then remediation runs
    And, assuming real viable roles exist in the backlog, viable_count is restored above zero
    And an audit trail records the detection and the recovery
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11 by fault injection (below): the SCORE-P0 incident, replayed and
      auto-resolved.
- [ ] Resilient to a fresh install.

**Fault injection:** Reproduce the SCORE-P0 root cause — throttle or kill vLLM reachability
mid-scoring-tick so several postings degrade, then restore vLLM reachability. Assert the
remediator (not merely the ordinary next-tick retry of one unrelated posting) proactively
re-sweeps the degraded backlog and `viable_count` recovers within N ticks, with the review
queue growing again — zero human action.

---

### S4 — Panel-error auto-heal

**Summary:** Wire `scripts/monkey_crawl.py`'s error-detection surface (console errors,
`pageerror`, failed requests, HTTP≥400, the `RENDER_ERR` regex) into a live/periodic detector.
Scope is deliberately narrow (see Gap 5, above): detect, audit, apply safe mitigations (disable
the one broken gadget so the rest of the panel still renders), and alert — never claim to "fix"
a JS logic bug at runtime.

**DoR:**
- [ ] Decision made on live-wiring approach: scheduled `monkey_crawl.py` run against the live
      instance vs. a client-side error beacon posted to a health endpoint (Gap 4, above).
- [ ] The panel error taxonomy from `RENDER_ERR` (`not found`, `failed to load`,
      `is not defined`, `cannot read`, `500 internal`, etc.) reused, not reinvented.

**AC (Gherkin):**

```gherkin
Feature: Panel JS/Alpine errors self-heal within their real limits

  Scenario: A live panel error is detected and audited
    Given a panel throws a console error or an uncaught exception in production
    When the live detector's next cycle runs
    Then a PanelErrorDetected event is emitted naming the panel and the error text
    And it is recorded in the audit trail

  Scenario: A known regression is safely mitigated
    Given a panel error matches a previously-fixed regression class
    When it is detected again
    Then the remediator disables or reloads only the affected gadget
    And the rest of the panel remains usable
    And an alert is raised because a code-level regression requires a human-authored fix

  Scenario: The remediator never claims to fix what requires a code change
    Given a panel error is a genuine code-level bug (not config, not data)
    When the remediator cannot resolve it through a bounded operational action
    Then it fails safe — it audits and alerts
    And it does not report the error as resolved
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11 by fault injection (below).
- [ ] Resilient to a fresh install.

**Fault injection:** Reintroduce one of the historically-fixed panel bugs
(`docs/APPLICANT-BACKLOG.md`: "UI monkey crawl — 23 broken panels → 0") behind a test flag, or
inject a synthetic `console.error` via a test harness. Assert the live detector catches it
within one cycle, an audit entry is created, and — because this is a code-level class — the
fail-safe alert fires rather than a false "fixed" claim.

---

### S5 — Stuck-queue / idle-txn auto-heal

**Summary:** Extends the two existing bounded-retry-then-notify-human paths in `agent_loop.py`
(`_record_approval_start_failure`, `_record_resume_failure`) with an AI-remediation step before
the cap is reached, and builds the missing idle-in-transaction DB probe (Gap 2, above) from
scratch.

**DoR:**
- [ ] Idle-in-transaction probe built (new: scheduled `pg_stat_activity` query for
      `state = 'idle in transaction'` past an age threshold).
- [ ] `_APPROVAL_START_FAILURE_CAP`/`_RESUME_FAILURE_CAP` hook points confirmed as the
      pre-cap insertion point for a remediation attempt (`agent_loop.py` ~L1050-1195).

**AC (Gherkin):**

```gherkin
Feature: Stuck applications and idle DB sessions self-heal

  Scenario: A stuck application start is remediated before the human-notify cap
    Given an application has failed to start on consecutive ticks, short of the failure cap
    When the remediator diagnoses the failure (sandbox capacity, orchestrator health, workflow logs)
    Then it applies a bounded corrective action (e.g. release-and-retry the sandbox slot)
    And only falls through to the existing human notification if that action doesn't clear the streak

  Scenario: An idle-in-transaction session is detected and safely terminated
    Given a database session has been idle-in-transaction past the configured age threshold
    When the probe detects it
    Then the remediator terminates the offending session
    And it never terminates a session with in-flight, uncommitted user-authored work
    And the action is recorded in the audit trail

  Scenario: Exhausted remediation still fails safe exactly as today
    Given a stuck application's remediation attempts are exhausted
    When the existing failure cap is reached
    Then the existing deduped notify_error alert fires, unchanged
    And no infinite retry loop occurs
```

**DoD:**
- [ ] TDD unit + BDD scenarios green.
- [ ] Verified on 10.0.1.11 by fault injection (below).
- [ ] Resilient to a fresh install.

**Fault injection:** (a) Open a raw idle-in-transaction session against the prod Postgres via a
throwaway script; assert the probe detects it and the remediator terminates it within one check
interval. (b) Force `_record_resume_failure`'s cap by making a fake application's workflow
always raise; assert bounded remediation attempts occur, then the existing fail-safe alert
fires — never an infinite retry.

---

## BDD framework + scaffold status

The repo already runs **`pytest-bdd`** (`pyproject.toml` `[tool.pytest.ini_options]`:
`bdd_features_base_dir = "tests/bdd/features"`; markers include `bdd` and `pending`, the latter
mapped to a non-strict `xfail` by `tests/bdd/conftest.py::pytest_bdd_apply_tag` — the repo's
established TDD-red convention for "specified but not yet built").

Per this task's scope (**docs + scaffolds only, no step definitions, no product code**), six
`.feature` files were added under `tests/bdd/features/self_healing/` — the epic-wide scenarios
plus one file per slice, all scenarios tagged `@pending`:

- `tests/bdd/features/self_healing/epic_self_healing.feature`
- `tests/bdd/features/self_healing/s1_remote_repairs_local.feature`
- `tests/bdd/features/self_healing/s2_detector_bus_audit.feature`
- `tests/bdd/features/self_healing/s3_scorer_degrade_autoheal.feature`
- `tests/bdd/features/self_healing/s4_panel_error_autoheal.feature`
- `tests/bdd/features/self_healing/s5_stuck_queue_idle_txn.feature`

**Important — these are intentionally NOT wired yet.** `pytest-bdd` only collects a `.feature`
file's scenarios when a step module calls `scenarios("path/to/file.feature")` (see the existing
convention: every file under `tests/bdd/features/enhancements/` is bound from a
`tests/bdd/steps/test_enh_*_steps.py` module, e.g. `enh_144_*.feature` ←
`test_enh_t12_cua_steps.py`'s `scenarios(...)` call). Since step definitions are out of scope
here, these six files exist as **documentation-grade Gherkin only** — pytest will not run or
report them at all until a step module wires them, so they cannot break CI in their current
state (stronger than "skipped" — currently uncollected).

**When TDD build begins on a slice:** create `tests/bdd/steps/test_self_healing_steps.py`
following the established pattern (see `tests/bdd/steps/test_enh_t12_cua_steps.py`'s docstring:
untagged scenarios are real regression coverage that must pass; `@pending`-tagged scenarios get
an HONEST probe at the real target — a speculative import or an assertion against not-yet-built
code — so they're a genuine red, never `assert True`), call `scenarios(...)` for that slice's
feature file, and drop the `@pending` tag from each scenario as its behavior actually ships.

## Notes / dependencies

- S1 depends on MODEL-RESILIENCY (fallback tier) landing first — it is "folded into" SCORE-P0
  per `docs/APPLICANT-BACKLOG.md` line 54 and is already in progress.
- S3 depends on SCORE-P0's bounded-retry fix (`scoring_service.py`) being merged — it is
  present but **uncommitted** on this branch as of this document (`git status` shows
  `scoring_service.py` and `viability_scoring.py` modified, not staged).
- S2 is infrastructural and unblocks clean audit coverage for every other slice; doing it before
  or alongside S1 (rather than last) is recommended even though it's numbered after S1 in the
  backlog's candidate list.
- None of these slices may be started as "done" without satisfying `docs/APPLICANT-BACKLOG.md`'s
  standing conventions: DoR + AC-as-BDD + DoD, full TDD+BDD (red before green), verified on the
  running 10.0.1.11 instance, resilient to a fresh install.
