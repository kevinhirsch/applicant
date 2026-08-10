# ADR-0008: Autonomous self-healing — deterministic detection → agentic remediation, remote repairs local

**Status:** Proposed (grounds `docs/APPLICANT-BACKLOG.md` § EPIC SELF-HEAL).
**Numbering note:** the backlog's EPIC SELF-HEAL section cross-references "ADR-0001" three
times ("see ADR-0001", "DoR: ADR-0001 accepted") — that reference predates this document and
points at the wrong slot. `docs/adr/0001-hexagonal.md` already occupies ADR-0001 (hexagonal
architecture, accepted 2026-07). This document is the actual self-healing ADR; it is numbered
**ADR-0008**, the next free number in the existing `docs/adr/0001`–`0007` sequence. Until the
backlog owner corrects those three references, read every "ADR-0001" self-heal cross-reference
in `docs/APPLICANT-BACKLOG.md` as meaning this document.

## Context

Applicant's north star (`docs/APPLICANT-BACKLOG.md` line 3) is that Kevin wakes to a
review-ready queue of drafted applications, produced automatically, with **no manual
babysitting**. The product owner's standing principle (verbatim, backlog line 11 and the
EPIC SELF-HEAL block, lines 22-23):

> "We need deterministic error detection that calls AI to perform dynamic error
> troubleshooting and correction. The human must NEVER have to step in to fix the product —
> the AI does ALL the fixing because it has ALL the tools. The remote LLM should come in and
> fix the local LLM when needed. This is a fully agentic product."

Officially this is a **self-healing system / autonomous closed-loop remediation / agentic
auto-remediation (AIOps)**. The requirement is architectural, not a single bug fix: every class
of runtime failure the engine can already detect must eventually resolve itself without a
human opening a terminal, and the mechanism for "eventually resolve itself" is an AI agent with
tool access, not a fixed script.

The codebase already runs 24/7 unattended (DBOS durable execution, ADR-0002) and already
contains a working example of exactly this failure mode: **SCORE-P0** (`docs/APPLICANT-BACKLOG.md`
line 53) — a transient LLM timeout degraded viability scoring to embedding similarity, which
then persisted below threshold, starving the auto-draft queue to zero viable postings, with no
automatic recovery. That incident is the concrete proof this ADR generalizes from, not a
hypothetical.

**What already exists to build on** (grounded by file, so this decision reuses rather than
reinvents — per the STANDING reuse-first/no-redundancy principle, `docs/APPLICANT-BACKLOG.md`
line 13):

- A **typed boot-health registry**: `src/applicant/app/lifespan.py`, `BootHealth` (L31-84,
  singleton `_boot_health`) — `.record(step, ok, detail)` / `.snapshot()`, already used for
  `capability_report`, `durable_recovery`, `db_healthcheck`, `dormant_surfaces`, `audit_log`.
  Boot-time only today; the natural registry to extend to continuous runtime watchdogs.
- A **domain event bus + durable audit trail**: `src/applicant/core/events.py`
  (`DomainEventBus`, `DomainEvent` subclasses: `JobDiscovered`, `ViabilityScored`,
  `ApplicationStateChanged`, `PendingActionRaised`, `MaterialApproved`, `OutcomeRecorded`) and
  `src/applicant/application/services/audit_log_service.py` — `AuditLogService.start()`
  subscribes to the bus and persists one `ActionEvent` per emission (per-event session
  isolation so the trail survives rollbacks; bounded write-retry). Surfaced via
  `src/applicant/app/routers/audit.py` and the existing "audit" webui panel.
- An **orchestrator to run bounded work durably**: `src/applicant/app/container.py`,
  `_build_orchestrator()` (L470-511) — builds a `DbosOrchestrator` (Postgres-backed durable
  workflows, ADR-0002) or a `CheckpointShimOrchestrator`.
- A **scheduled-closed-loop precedent to mirror, not duplicate**:
  `src/applicant/application/services/curation_service.py`, `CurationService` (FR-MIND-7,
  ADR-0006) — "the scheduled closed learning loop," driven by the same scheduler tick, with a
  documented per-tick-safety contract (FR-MIND-10: state never lives on the per-tick loop
  instance). The remediator should be this service's sibling, not a new agent runtime.
- A **tool-access substrate**: `src/applicant/adapters/tools/tool_registry.py` /
  `src/applicant/ports/driven/tool_registry.py` (`ToolRegistry`/`ToolRegistryPort`, FR-UI-4) for
  per-tool enable/disable at dispatch, and the vendored **Agent-Zero substrate** at
  `agent-zero/` (`agent.py`, `python/`, `tools/` — `call_subordinate.py`, `scheduler.py`,
  `notify_user.py`, etc.) that Applicant's application layer (`src/applicant`) is built
  alongside, per ADR-0006's "port the learning/looping/intelligence core" precedent.
- A **human-alert channel to reuse as the fail-safe**:
  `src/applicant/application/services/notification_service.py`,
  `NotificationService.notify_error(title, body, dedup_key)` (L156-167) — already the mechanism
  `agent_loop.py` uses for the two bounded-retry-then-give-up patterns below.
- An **updater sidecar with privileged (Docker-socket) access**: `scripts/updater-daemon.sh` +
  `docker/updater.Dockerfile` — a small sidecar, separate from `api`, holding the host Docker
  socket + a bind-mounted repo checkout, driven by a file-based control plane
  (`UPDATE_CONTROL_DIR`: `request` in, `status.json`/`update.log`/`updater.alive` out). Today it
  only runs the full-stack `scripts/update.sh --apply`; it is the only place in the stack that
  can restart a container, and is the shape a bounded "restart one wedged service" remediation
  action should follow (same control-plane pattern, narrower scope) — not a new privileged
  channel from `api`.

## Decision

Adopt a **closed-loop, four-layer self-healing architecture**: deterministic detection →
agentic remediation → remote-repairs-local escalation → inviolable guardrails, with every step
audited. Each layer is additive onto the substrate above; none of it is a parallel runtime.

### 1. Deterministic detection layer

Typed health checks / invariants / error signatures / watchdogs — no LLM judgment in the
detection step itself, only in the remediation step. The following failure classes are
**already detectable today** (grounded, file-cited); each is a candidate detector event
source, several with an existing bounded-retry-then-human-notify shape that S1-S5 (below)
extend to bounded-retry-then-**AI-remediate**:

| # | Failure class | Where it's detected today |
|---|---|---|
| 1 | **LLM tier-ladder exhaustion** | `src/applicant/adapters/llm/openai_compatible.py`, `complete()` (~L473-570): walks each `TierLadder` rung, catches `httpx.HTTPError`/`LLMNotConfigured`/`LLMRateLimited`/`ValueError`/context-overflow, logs `llm_tier_failed`/`llm_escalate_low_confidence`, raises typed `LLMLadderExhausted` when both the upward climb and the downward fallback pass are spent. |
| 2 | **Scorer degrade-to-embeddings** | `src/applicant/application/services/scoring_service.py`, `_persist_or_defer`/`_bump_transient_failures`/`_transient_failure_count` (L157-274, the SCORE-P0 fix — uncommitted on this branch as of this ADR): `scoring.degraded` flag, a consecutive-failure counter durably stored in `JobPosting.rationale["transient_llm_failures"]`, bounded by `DEFAULT_MAX_TRANSIENT_RETRIES=3` / env `SCORING_MAX_TRANSIENT_RETRIES`. |
| 3 | **Local vLLM wedged / model endpoint unreachable** | `src/applicant/application/services/model_endpoint_service.py`, `_fetch_models()`/`_humanize_ping_error()` (~L79, 280-330): live-pings each configured endpoint and reports a humanized error; `list_endpoints()` (L136-161) reports `online: bool` per endpoint. Backlog B3 documents the live incident ("vLLM stops wedging — router is qwen-only"). |
| 4 | **Model-endpoint offline** | Same `model_endpoint_service.py`, plus the "honest health panel" `src/applicant/app/routers/health.py` (`/api/health/capabilities`) — postgres / résumé renderer / browser / orchestrator, each real-vs-stub with fix copy. |
| 5 | **Discovery circuit-breaker open** | `src/applicant/adapters/discovery/jobspy_searxng.py`, `SourceCircuitBreaker` (~L88-143): `consecutive_failures` vs. `failure_threshold=3`, `cooldown_seconds=1800`, `is_open()`/`allow()`/`record()`, logs `circuit_breaker_skip`. |
| 6 | **Migration failure** | `scripts/install.sh` L849-873, `run_retry "Alembic migrate" ... alembic upgrade head`, gated behind a pre-migration DB snapshot. **Gap:** install/update-script-time only — no live signal reaches the running engine's health surface if a migration is behind or half-applied post-boot. |
| 7 | **Endpoint 5xx** | `src/applicant/app/main.py`, `register_exception_handlers()` (L67-120): global `DomainError`→4xx handler plus a catch-all `Exception`→500 handler that logs `unhandled_exception` (path, request-id, exc type, traceback) and offers the crash to the opt-in telemetry reporter; `/healthz` (~L240-264) aggregates `checks["boot"]`/`checks["boot_degraded"]` and returns 503 when degraded. |
| 8 | **Stuck / starved auto-draft queue** | `src/applicant/application/services/agent_loop.py`: `_viable_count()` (~L2153) feeds `_auto_draft_top_viable()` (~L833-880); `_record_approval_start_failure()` (~L1050-1088, capped by `_APPROVAL_START_FAILURE_CAP`, then `notify_error(dedup_key="stuck_approval_start:{key}")`); `_record_resume_failure()` (~L1162-1195, capped by `_RESUME_FAILURE_CAP`, then `notify_error(dedup_key="stuck_application:{key}")`). Today both cap out at **notify a human**, not remediate. |
| 9 | **Idle-in-transaction DB sessions** | **Gap — no existing detector.** Grepped for `idle_in_transaction`/`statement_timeout`/`pool_timeout` across `src/`: no hits. Needs a new probe (e.g. a scheduled `pg_stat_activity` query for `state = 'idle in transaction'` past an age threshold) before this class can be detected at all. |
| 10 | **Panel JS / Alpine errors** | `scripts/monkey_crawl.py`: a Playwright crawl across every plugin panel capturing `console.error`/`warning`, `pageerror`, `requestfailed`, HTTP≥400, and a `RENDER_ERR` regex over visible text. **Gap:** this is a manually-invoked, offline QA tool (per-panel subprocess, hard-killed on freeze) — not wired into the running product as a live/periodic detector the closed loop can consume. |

Detectors emit a typed event onto the **existing** `DomainEventBus` (`core/events.py`) — a new
`DomainEvent` subclass per failure class (e.g. `LlmLadderExhaustedDetected`,
`ScorerDegradedDetected`, `QueueStarvedDetected`) — rather than a bespoke bus. The existing
`BootHealth` pattern (`lifespan.py`) extends from boot-once to a periodic re-run (mirroring how
`CurationService`/`Scheduler` already run periodic ticks) so items 3, 4, 6, and 9 above become
continuously-checked invariants, not just boot-time facts.

### 2. Agentic remediation layer

An AI remediator, architected as **the sibling of `CurationService`** (a scheduled service
consuming events off the same bus, not a new agent runtime), with tool access via the
**existing** `ToolRegistry`/Agent-Zero substrate (`agent-zero/tools/`) — reused per the
standing "product already has an Agent-Zero substrate + tools + an orchestrator" note. It:

- Consumes detector events (layer 1) as they land on the bus.
- Diagnoses using the same context a human on-call engineer would reach for: the failing
  detector's payload, the relevant `BootHealth`/`/api/health/capabilities` snapshot, and recent
  `ActionEvent` audit history for the affected entity.
- Applies **bounded** corrective actions through existing seams wherever one already exists:
  re-scoring a poisoned posting (calls `ScoringService.score_viability` again — same seam
  SCORE-P0's retry uses), re-registering a model endpoint (`ModelEndpointService.add_endpoint`/
  `test_endpoint`), clearing a stuck approval/resume streak (`_clear_approval_start_failure`-style
  reset once the underlying cause is fixed), closing/half-opening a discovery circuit breaker
  (`SourceCircuitBreaker.record`), or requesting a scoped service restart through the
  **updater sidecar's control-plane pattern** (new, narrower sibling of
  `scripts/updater-daemon.sh`'s `request`/`status.json` handshake — see Consequences: this one
  channel is a genuine new build, not a reuse, because nothing in the stack today can restart a
  single service short of the sidecar's full-stack `update.sh --apply`).
- Runs `start_workflow`-style through the **existing** `_build_orchestrator()` (`DbosOrchestrator`)
  so a remediation is itself durable/resumable, exactly like an application pipeline.

### 3. Remote-repairs-local escalation

Two distinct jobs the remote/cloud LLM does when the local model is degraded, both concrete:

- **(a) Serves inference as fallback** — this is the **MODEL-RESILIENCY** fallback tier
  already in flight (`docs/APPLICANT-BACKLOG.md` line 54): the `TierLadder` gains an optional
  cloud rung (env `LLM_FALLBACK_BASE_URL`/`_MODEL`/`_API_KEY`/`_PROVIDER`, default DeepSeek),
  appended so `openai_compatible.py`'s existing escalation walk (layer-1 detector #1 above)
  reaches it automatically instead of raising `LLMLadderExhausted`. **This half already has a
  landing spot in the existing ladder mechanism — no new escalation code path needed, only the
  new tier.**
- **(b) Drives remediation of the local LLM itself** — when detector #3 (local vLLM
  wedged/unreachable) fires, the remediator (layer 2), now running on the **remote** tier
  because the local one is the thing that's broken, diagnoses (ping/model-list against
  `ModelEndpointService`, inspect recent `llm_tier_failed` audit entries) and issues a bounded
  restart/reload/reconfigure action against the local model service through the updater
  sidecar's control-plane pattern (above). **This half is a genuine gap today** — nothing
  currently restarts the local vLLM automatically; B3's fix (backlog) was a static config
  change applied by an operator, not a live agentic action. Recorded as a prerequisite in the
  story doc (S1).

### 4. Guardrails (inviolable, even inside self-repair)

These hold **unconditionally**, enforced in the core exactly like the existing stop-boundary
rules (truthfulness, pre-fill-stop, sensitive-field policy — `docs/adr/0001-hexagonal.md`), not
as remediator-side discipline:

- **Never auto-submit a user's job application.** A remediation action may re-score, re-draft,
  restart a service, or re-register an endpoint — it may never call the submit path. Drafts
  stay review-gated exactly as today (`docs/APPLICANT-BACKLOG.md`: "Review-gated, never
  auto-submitted").
- **Never delete user data as a side effect of healing.** A remediation action may clear a
  bookkeeping counter (e.g. `_TRANSIENT_FAILURES_KEY`) or reset a circuit breaker; it may never
  drop an `Application`, `JobPosting`, credential, or document.
- **Bounded retries with backoff, no infinite loops.** Every remediation attempt is capped
  (mirrors `_APPROVAL_START_FAILURE_CAP`/`_RESUME_FAILURE_CAP`/`DEFAULT_MAX_TRANSIENT_RETRIES`
  already in the codebase) — a remediator that keeps failing must give up, not spin.
- **Full audit trail of every detection + action + outcome** (layer 5, below) — a remediation
  attempt with no record is treated as a bug, same bar as an unaudited domain action today.
- **Fail-safe degradation + alert when remediation is exhausted.** At the retry cap, the
  remediator's last resort is the **existing** `NotificationService.notify_error(dedup_key=...)`
  path — the same one `_record_resume_failure`/`_record_approval_start_failure` already use.
  Self-healing narrows how often a human is paged; it does not remove the page as a backstop.

### 5. Auditability & observability

Every heal attempt — what detector fired, what the remediator diagnosed, what action it took,
the outcome — is recorded as an `ActionEvent` through the **existing**
`AuditLogService`/`DomainEventBus` (new event types added to `audit_log_service._ACTION_MAP`,
not a new store) and surfaced in the **existing** ops/health surfaces: the "audit" webui panel
(`src/applicant/app/routers/audit.py`) and `/api/health/capabilities`
(`src/applicant/app/routers/health.py`). No new dashboard is built; both are thin extensions of
what already ships.

**Alternatives considered:**

- **Pure static retries (no AI in the loop)** — rejected as insufficient on its own: a fixed
  retry/backoff handles *transient* failures (and several already do — the ladder walk, the
  scorer's bounded-retry) but cannot *diagnose* a novel failure mode (a new ATS 403 pattern, an
  unfamiliar vLLM stack trace) or choose among several plausible corrective actions. Static
  retries remain layer 1's bounded-retry primitive; they are necessary but not sufficient for
  "the human never has to fix the product."
- **Human-on-call (notify and wait)** — this is the *status quo* for detectors #8's two capped
  paths today, and is explicitly what the product owner's principle rejects ("the human must
  NEVER have to step in"). Kept only as the guardrail-4 fail-safe floor, never the primary
  response.
- **Existing per-call fallback only (today's ladder escalation, no remediation layer)** —
  covers layer-3(a) (remote serves inference) but stops there: a wedged local vLLM stays wedged
  forever behind a working cloud fallback, silently paying cloud-inference cost with no path
  back to local-primary. Rejected as a half-measure; layer-3(b) (remote *repairs* local) closes
  that gap.

## Consequences

**Positive:**

- Closes the exact incident class SCORE-P0 already proved happens in production (zero viable
  postings, frozen review queue) with a general mechanism instead of a one-off fix.
- Every new piece reuses an existing seam (event bus, audit service, orchestrator, tool
  registry, notification ladder, updater control-plane pattern) — no parallel runtime, matching
  the standing reuse-first principle and keeping the surface area a genuinely new build has to
  cover small: essentially the scoped single-service-restart control-plane sibling (layer 2/3b)
  and the remediator service itself.
- Detectors 1, 2, 3, 4, 5, 7, 8 need **no new detection code** — only a bus-emission wrapper
  around mechanisms that already exist and already carry bounded-retry counters.
- The audit trail is a natural byproduct of reusing `AuditLogService`, so "every heal attempt
  recorded" is close to free rather than a second logging system to build and keep in sync.

**Negative / risks:**

- **An over-eager remediator is itself a reliability risk** — an AI that restarts a healthy
  service because it misdiagnosed a transient blip, or thrashes between two "corrective"
  actions, is worse than the failure it's fixing. Mitigated by guardrail-4's hard retry caps and
  by scoping remediation actions to the same narrow, already-reviewed operations the codebase
  already performs deterministically (re-score, re-register, reset-a-counter) rather than
  open-ended shell access.
- **Cost of cloud calls** — layer-3(a)'s fallback tier and the remediator's own diagnosis calls
  both spend cloud-LLM tokens on every escalation; unlike the deterministic detectors, this is
  ongoing operational cost, not a one-time build. `docs/APPLICANT-BACKLOG.md`'s
  MODEL-RESILIENCY entry already frames the fallback tier as env-gated / off without a key for
  exactly this reason.
- **The healer needs its own circuit-breaker.** A remediator that repeatedly "fixes" the same
  detector without the underlying cause actually clearing must itself back off and fall through
  to guardrail-4's alert path — this needs the same bounded-counter discipline the codebase
  already applies to LLM retries and resume attempts, applied one level up (to remediation
  attempts, not just the underlying operation).
- **Two genuine new-build items, not reuse** — the scoped single-service-restart control-plane
  channel (layer 2/3b) and the idle-in-transaction DB probe (detector #9) have no existing seam
  to extend; they are real, if narrow, new components and are called out explicitly rather than
  assumed away. The live wiring of `scripts/monkey_crawl.py` into a runtime signal (detector
  #10) is a smaller version of the same problem.
- **Migration-failure and monkey-crawl detectors are currently offline-only** (detector #6,
  #10) — until they're wired into the runtime bus, the closed loop cannot react to either class
  unattended; both are recorded as prerequisites in the story doc rather than assumed covered.
