# Applicant — Working Backlog

**North star:** Kevin wakes to a review-ready queue of tailored, drafted job applications for high-fit roles — produced automatically, durable across a fresh install, no manual babysitting.

**Conventions (STANDING — every item MUST carry all three):**
- **DoR** (Definition of Ready): scoped, unblocked, testable; failing tests/scenarios can be written first.
- **AC** (Acceptance Criteria): written as **BDD** Gherkin `Given/When/Then` scenarios — these are the executable spec.
- **DoD** (Definition of Done): fixed *in source*, committed + pushed, **all AC scenarios green**, verified on the running 10.0.1.11 instance, resilient to a fresh install.
- **Delivery = full TDD + BDD (STANDING).** Write the failing unit test (TDD) and the failing BDD scenario (AC) BEFORE the implementation; red → green → refactor. No item is Done without both green.
- **Priorities:** P0 blocks the north star; P1 robustness; P2 polish.
- **Fully-agentic product (STANDING):** the human NEVER has to fix the product. Anything the system can detect deterministically, the system must be able to remediate agentically (see EPIC SELF-HEAL / ADR-0008).

**STANDING PRINCIPLE — reuse-first, no redundancy (ONGOING):** Never build a component, service, or endpoint that duplicates one that already exists — reuse it. A new UI view is a THIN layer over existing data/actions (e.g. landing-page gadgets read the same scored Digest data + reuse the same review actions; they do not re-derive them). Any new endpoint/service must justify why an existing one didn't suffice. Check for redundancy in EVERY review (use `/simplify`) — a component that re-implements or re-derives what another already provides is a defect, and features silently drift/drop between the copies (e.g. the match-score badge lost when Pending Reviews forked from the Digest).
Env: prod `10.0.1.11:8000` · model vLLM `10.0.1.225:8000` (qwen3.6:27b) · branch `claude/refactor-agent-zero-applicant-xn7xoc`.

_Last updated: 2026-08-11 (Fit Engine + Companion epics + story ladders, ADR-0011..0014; EPIC DISCOVERY + ADR-0015 verified-source wide-net discovery; EPIC MATERIAL-QUALITY (#44); SELF-HEAL/AGENTS/MIND-DURABLE decomposed into full story ladders; SCHEDULER campaign-pickup bug (SH-1) added)._

---

## 🧱 EPICS

### EPIC SELF-HEAL — Autonomous self-healing (deterministic detection → agentic remediation; human NEVER fixes) · see ADR-0008
**Principle:** The product detects its own failures **deterministically** (typed health checks / invariants / error signatures / watchdogs) and invokes an **AI agent with full tool access** to troubleshoot and correct them at runtime. The human is *never* required to fix the product — the AI does all the fixing because it has all the tools. Includes: **the remote/cloud LLM repairs the local LLM** when the local model is degraded/unavailable/wedged. This is a **fully agentic product**. (Officially: *self-healing system / autonomous closed-loop remediation / agentic auto-remediation*.)

- **DoR:** ADR-0008 accepted (detection signals catalogued; remediator authority + guardrails defined; remote→local repair path specified; audit + fail-safe defined); each slice scoped with BDD AC; fault-injection harness identified.
- **AC (BDD — executable spec):**
  - *Remote-repairs-local:* **Given** the local LLM is wedged/unreachable, **When** an inference/scoring call fails deterministically, **Then** the system escalates inference to the remote LLM **and** triggers a remediation action that restores the local LLM (e.g. restart/reload/reconfigure), with zero human action, and records an audit entry.
  - *Detect→remediate loop:* **Given** a deterministic error signature fires (panel JS error, migration failure, endpoint 5xx, stuck/starved queue, scorer degrade-to-embeddings, discovery circuit-open), **When** it is detected, **Then** an AI remediator is invoked with tools to diagnose + correct, and the action + outcome are audited.
  - *Bounded + fail-safe:* **Given** remediation is attempted, **When** N bounded retries are exhausted, **Then** it fails safe (degrade + alert), never loops infinitely, never loses data.
  - *Guardrails inviolable:* **Given** any remediation, **Then** no user application is ever auto-submitted and no user data is ever deleted as a side effect (the safety rails hold even inside self-repair).
  - *No-human-required:* **Given** any failure class covered by a detector, **When** it occurs unattended overnight, **Then** the product returns to a healthy state with no human intervention, evidenced by the audit trail.
- **DoD:** deterministic detectors for the known failure classes emit typed events; an agentic remediator consumes them and applies bounded, audited corrective actions via available tools; remote LLM can repair the local LLM; all guardrails enforced; **TDD unit + BDD scenario coverage green**; verified on 10.0.1.11 by **fault injection** (e.g. kill vLLM → system self-recovers, drafting resumes, zero human action); resilient across a fresh install. Delivered in slices, each independently meeting DoR/AC/DoD.
- **First slices (candidates):** S1 remote-repairs-local LLM (compose w/ MODEL-RESILIENCY fallback tier already in flight); S2 detector bus + audit store; S3 scorer-degrade self-heal (re-score poisoned postings automatically); S4 panel-error self-heal; S5 stuck-queue / idle-txn self-heal.

**Story ladder (current state → fully implemented; decomposes the "First slices" list above into shippable, DoR/AC/DoD-bearing stories):**

- **SH-1 — Scheduler autonomously drives active-campaign discovery/scoring (P0, live bug).**
  - **DoR:** root-caused to `Scheduler.tick()` → `_active_campaigns(storage)` (`scheduler.py` L1025-1027, `[c for c in store.campaigns.list() if getattr(c, "active", True)]`) returning zero campaigns even with an active campaign configured, so `AgentLoop.tick` (which DOES drive discovery via `_run_discovery` at L788/854-859) is never invoked autonomously — discovery/scoring only ran via an explicit run trigger, not the 24/7 tick. `campaigns=len(ticked)` (L388/395) reports 0 as the live symptom.
  - **AC:**
    - *Given* an active campaign exists in storage, *When* a scheduler tick fires, *Then* `_active_campaigns` returns it, `AgentLoop.tick` runs for it, and the tick's `campaigns` count is >= 1.
    - *Given* the per-tick session factory is configured (CONC-2 isolation), *When* a tick runs, *Then* `_active_campaigns(storage)` reads the SAME committed campaign row the request path wrote (no stale/isolated-session mismatch).
    - *Given* a tick where campaigns>=1, *Then* discovery + scoring advance at least one step (verified via `ticked` + a scored-posting-count delta across ticks), not just an incremented counter.
  - **DoD:** root cause fixed in `scheduler.py`/`_active_campaigns` (or its storage/session wiring); regression test asserting a tick against a real active campaign yields `campaigns>=1` and posting/score counts advance; committed; verified live on 10.0.1.11 (a scheduled tick against the real campaign moves the queue with zero manual trigger).
  - **Reuse:** `Scheduler.tick`/`_active_campaigns`, `AgentLoop.tick`/`_run_discovery` — fix the wiring, do not add a second autonomy loop.

- **SH-2 — Local-LLM-wedge detection + remediation signal.** ✅ (`52b3f6c2a`)
  - **DoR:** detector #3 (local vLLM wedged/unreachable) catalogued; `RemediationRequested` defined as the escalation signal.
  - **AC:** *Given* the local LLM is wedged/unreachable, *When* detected, *Then* `LocalLlmWedgeDetected` and `RemediationRequested` land on `DomainEventBus` and are audited (`detector_fired`/`remediation_requested` in `audit_log_service._ACTION_MAP`).
  - **DoD:** `llm_wedge_detector.py` emits both events; `_ACTION_MAP` extended; committed. **Known gap (tracked as SH-3, not a regression):** `RemediationRequested` is emitted but has no consumer yet — nothing restarts the local service automatically.
  - **Reuse:** `core/events.py`, `audit_log_service.py` — the precedent every later SELF-HEAL/AGENTS event type follows.

- **SH-3 — Scoped single-service-restart control-plane (remote-repairs-local, consumes `RemediationRequested`).**
  - **DoR:** SH-2's `RemediationRequested` is emitted but unconsumed (grounded gap, `core/events.py` L157-166: "a separate vLLM-host watchdog is the intended consumer"); `scripts/updater-daemon.sh`'s request/`status.json` control-plane pattern identified as the shape to narrow, not duplicate.
  - **AC:**
    - *Given* `RemediationRequested` fires for a wedged local LLM, *When* the (remote-tier, since local is down) remediator consumes it, *Then* it issues a bounded restart/reload/reconfigure action against the local model service through a new, narrow sibling of the updater sidecar's control-plane handshake.
    - *Given* the action succeeds, *Then* the local LLM comes back online and an audit entry records detection→action→outcome.
    - *Given* N bounded retries are exhausted, *Then* it fails safe to `NotificationService.notify_error` (the existing fail-safe path), never loops infinitely.
  - **DoD:** new narrow control-plane channel (request/status handshake, scoped to one service restart, not the full-stack `update.sh --apply`); consumes `RemediationRequested`; bounded + audited; TDD+BDD; verified by fault injection (kill local vLLM → auto-recovers, zero human action) on 10.0.1.11.
  - **Reuse:** `scripts/updater-daemon.sh`'s control-plane *pattern* (new, narrower implementation — this is a genuine new build per ADR-0008 Consequences, not reuse of the sidecar itself).

- **SH-4 — Scorer-degrade bounded-retry guard (never persist a poisoned embedding score).** ✅
  - **DoR:** SCORE-P0 incident root-caused (a transient LLM failure degraded scoring to embedding similarity, which then persisted below-viable permanently).
  - **AC:** *Given* a transient LLM failure during scoring, *When* an LLM tier IS configured, *Then* the posting is left UNSCORED/retryable (never persists the degraded embedding score) up to `DEFAULT_MAX_TRANSIENT_RETRIES`/`SCORING_MAX_TRANSIENT_RETRIES`; *Given* retries are exhausted, *Then* it degrades explicitly (`scoring.degraded=True`), never silently.
  - **DoD:** `ScoringService._persist_or_defer`/`_bump_transient_failures`/`_transient_failure_count` (`scoring_service.py`) shipped; committed. **Open (tracked separately, ADR-0009 S3 relation):** an AI-diagnosed remediation for a *systemic* pattern (vs. this deterministic per-posting retry) is deferred to EPIC AGENTS/AE if RC's effectiveness assessment ever surfaces one.
  - **Reuse:** `scoring_service.py` (the deterministic bounded-retry cure; no AI remediator needed to close THIS loop).

- **SH-5 — Detector bus extended: idle-in-transaction probe + live migration-failure signal + monkey-crawl as a runtime detector.**
  - **DoR:** three grounded gaps from ADR-0008's detector table: #9 (idle-in-transaction DB sessions — no existing probe, grepped `idle_in_transaction`/`statement_timeout`/`pool_timeout` across `src/`, no hits), #6 (migration failure is install/update-script-time only, no live post-boot signal), #10 (`scripts/monkey_crawl.py` is a manually-invoked offline QA tool, not wired into a runtime detector).
  - **AC:**
    - *Given* a DB session sits idle-in-transaction past an age threshold, *When* a scheduled probe runs, *Then* it emits a typed detector event (new `DomainEvent` subclass) onto the bus.
    - *Given* the engine boots with the DB schema behind `alembic heads`, *When* a live post-boot check runs, *Then* it emits a detector event instead of staying silent until a query fails.
    - *Given* `monkey_crawl.py` is invocable non-interactively against a disposable instance (already true per `HANDOFF.md` §5.4), *When* scheduled periodically, *Then* its findings (console errors/failed requests) land on the bus as detector events, not only a manual report.
  - **DoD:** three new detector event types + emission sites; each audited via the existing `_ACTION_MAP` pattern; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `DomainEventBus`/`AuditLogService` (SH-2's precedent); `scripts/monkey_crawl.py` (scheduled invocation, no rewrite).

- **SH-6 — Panel-error detect + safe-mitigate + alert.**
  - **DoR:** scope explicitly bounded by ADR-0008 Gap 5 ("remediating a code-level bug is out of scope for this epic... a future 'AI writes the patch, updater sidecar redeploys it' loop... is explicitly not part of this epic" — that loop is EPIC AGENTS/AE, not this story).
  - **AC:** *Given* a panel JS/Alpine error is detected (via the SH-5 runtime monkey-crawl wiring), *When* it is a KNOWN safe-mitigate pattern (e.g. disable the broken gadget), *Then* the mitigation applies automatically and Kevin is alerted; *Given* it is NOT a known-safe pattern, *Then* it only alerts (never guesses a code fix — that is AE's job, not this detector's).
  - **DoD:** detect (SH-5) → classify (known-safe-mitigate vs. alert-only) → apply-or-alert, audited; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** SH-5's monkey-crawl detector event; `NotificationService.notify_error`.

- **SH-7 — Stuck-queue / idle-txn bounded remediation (beyond notify-only cap).**
  - **DoR:** detector #8 (stuck/starved auto-draft queue, `agent_loop.py` `_record_approval_start_failure`/`_record_resume_failure`) and SH-5's new idle-txn probe both currently cap out at `notify_error`, not remediation.
  - **AC:** *Given* a stuck approval/resume streak or an idle-in-transaction session past threshold, *When* the bounded-retry cap is reached, *Then* an operational remediation attempts first (release-and-retry a sandbox slot, terminate the idle session) BEFORE falling through to the human-notify floor.
  - **DoD:** bounded remediation action wired ahead of the existing notify-only cap in both call sites; guardrail-4 discipline preserved (bounded, audited, fail-safe); TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `agent_loop.py`'s existing `_APPROVAL_START_FAILURE_CAP`/`_RESUME_FAILURE_CAP` counters (add a remediation step before the existing notify call, don't replace the cap discipline).

### EPIC REVIEW-UX — the Pending-Reviews decision + refinement workflow (Kevin, 2026-08-10)
**Principle:** The review queue is where Kevin actually works. The flow: open the **source posting** → decide **Continue / Save-for-later / Discard** → (if Continue) review + refine generated answers → **prefill** the real form → **submit**. Plus freeform feedback that **teaches the profile** (global, transparent, reversible) and a **campaign chat**. **REUSE-FIRST:** Review/Approve/Snooze actions, `CriteriaService.edit_criteria`/`apply_learned_adjustment` (+ FR-CRIT/FR-LEARN transparency), `MaterialService.generate_cover_letter`/`generate_screening_answer` (per-section regen), the camoufox prefill/`easy_apply`/computer-use pipeline, and the a0 `chat_service` ALL exist — these stories are THIN UX + wiring over them, not new engines. Each story: DoR + BDD AC + DoD (TDD+BDD, verified on 10.0.1.11, fresh-install resilient).

- **RUX-1 Source posting link (P1, quick).** *Kevin: "the absolute first thing I look at is the posting itself; Review has no link."* **AC:** *Given* a pending review, *When* I open Review, *Then* a prominent "View source posting" link opens the original listing in a new tab; *And* if the source URL is unreachable/pulled, a cached snapshot is offered; *And* the link never leaks PII in the URL. **DoD:** link on the Review view (+ the row) sourced from `job_posting.source_url`; **live link + cached snapshot** (CONFIRMED Kevin) — snapshot captured at ingest so a pulled listing is still readable; committed.
- **RUX-2 Three-way decision: Continue / Save-for-later / Discard-with-reason (P1).** **AC:** (Continue) *Then* proceed to answer review. (Save-for-later) *Then* the app moves to a distinct **"Saved / To submit"** bucket with a reminder nudge, out of the active queue *(assumption Q6)*. (Discard) *Then* I type a **reason**, the app is discarded, **and the reason feeds a negative learning signal** so similar roles rank lower (reuse FR-LEARN + feedback_service). **DoD:** three actions wired, saved-bucket + nudge, discard-reason persisted + fed to learning; committed. Never deletes user data irrecoverably (discard = archived + reversible).
- **RUX-3 Per-section answer review + edit + regenerate (P1).** *Kevin picked ALL: regenerate a specific section, apply feedback across sections, inline-edit, regenerate whole app.* **AC:** *Given* an app under review, *When* I give freeform feedback targeting one section (cover letter / a specific screening answer / résumé variant), *Then* only that section regenerates (reuse MaterialService); *And* I can apply one instruction across multiple/all sections; *And* I can edit any section's text inline and save; *And* I can regenerate the whole app. All edits are review-gated (status stays DIGESTED until I approve). **DoD:** per-section + cross-section regen + inline edit + whole-app regen, reusing MaterialService; committed.
- **RUX-4 Prefill + submit, per-app boundary (P0-safety).** *Kevin: "Decide per application."* **AC:** *Given* I approved an app's answers, *When* I choose "prefill", *Then* Applicant fills the real form in-browser (camoufox) and **STOPS at review-before-submit**; *And* the submit boundary is per-app: default **I submit manually**, OR (only if I explicitly set auto-submit on THAT app) Applicant submits after my approval; *And* the system NEVER submits without that explicit per-app opt-in (FR-RESUME review gate holds). **DoD:** per-app submit-mode setting; prefill stops pre-submit by default; auto-submit only on explicit per-app opt-in; committed. **Guardrail: this is the never-auto-submit safety line.**
- **RUX-5 Freeform profile feedback → global, persistent, transparent, reversible (P1).** *Kevin: "Update my whole profile."* **AC:** *Given* I type freeform feedback to fine-tune my profile, *When* I submit it, *Then* it updates the campaign criteria/profile (reuse `CriteriaService`), affecting ALL future scoring + suggestions; *And* I'm shown exactly what changed; *And* I can revert it (reuse `learned_adjustments` transparency, FR-CRIT-2/3). **DoD:** freeform→criteria/learning wired, change surfaced + reversible; re-score triggers on the change; committed.
- **RUX-6 Campaign chat — "Ask anything to start a new chat" (P1).** **AC:** *Given* the chat box, *When* I type, *Then* it starts a conversation with the campaign agent (reuse a0 `chat_service`) that answers campaign questions, captures feedback, AND can take actions (edit criteria, trigger re-score, draft/save/discard) — *but* every side-effect routes through the existing review gates, is transparent + reversible, and it NEVER auto-submits an application *(authority assumption Q7)*. **DoD:** chat box wired to the campaign agent with gated, transparent actions; committed.

*Open confirmations (Kevin): Q5 source link = original+cached? · Q6 save-for-later = distinct bucket+nudge? · Q7 chat = action-capable within gates? (defaults assumed above).*

### EPIC AGENTS — Self-improving product: Reflection Coach + Automation Engineer (Kevin, 2026-08-10, 10-Q scoped)
**Vision:** Applicant continuously evaluates its own effectiveness and improves itself — extending SELF-HEAL from *detect→remediate* to *reflect→strategize* and *build→ship*. Two in-product agents. **Sequencing (Kevin Q10): build BOTH in parallel, starting now** — with one responsible gate (below).

**Agent A — REFLECTION COACH.** Re-evaluates the campaign's real effectiveness and tweaks strategy.
- **Cadence (Q1):** daily **AND** event-driven (fires on a rejection, a response-rate/velocity stall, N apps sent, a fit-score trend shift).
- **Effectiveness signals (Q2):** response/interview rate · velocity + time-in-stage · fit-score trend + Kevin's approve/discard/edit feedback · funnel progress (discovered→drafted→submitted→responded→interview→offer) vs the deadline. Evaluation is **semantic** (is this getting the right job, fast), not just counts.
- **Authority (Q3):** **auto-apply** profile + strategy tweaks, **transparent + reversible** (reuse `CriteriaService.edit_criteria`/`apply_learned_adjustment` + `learned_adjustments` transparency, FR-CRIT/FR-LEARN). Every change surfaced + one-click revert.
- **Outputs:** profile tweaks (criteria) · strategy tweaks (sources/thresholds/pacing/throughput) · **programmatic tweaks → Automation Engineer**.
- **AC (BDD):** *Given* a daily/event trigger, *When* the Coach evaluates, *Then* it produces a scored effectiveness assessment across all Q2 signals, auto-applies reversible tweaks (logged), and files any programmatic needs to the Engineer. **DoD:** scheduled + event hooks; reuses criteria/learning; transparent+reversible; audited; TDD+BDD; verified on 10.0.1.11.

**Agent B — AUTOMATION ENGINEER.** Monitors, fixes, and autonomously **extends/builds** the product.
- **Triggered by (Q4):** the user, the Reflection Coach (**shared backlog queue** for routine + **direct handoff for urgent**), or self (detected need/breakage).
- **Autonomy (Q5):** **fully autonomous including deploy**, within hard guardrails: NEVER auto-submit a user application, never destroy user data, everything reversible + audited, auto-rollback on failed health checks.
- **Deploy safety harness (Q6 — ALL required):** (1) deploy to the **e2e/test instance** first → run **full test suite + browser monkey-crawl** → promote to live only if green; (2) **hard TDD/BDD gate** (no deploy unless all tests + the feature's BDD scenarios pass); (3) **auto-rollback** on failed post-deploy health checks; (4) **snapshot + instant revert** on every deploy.
- **Scope (Q7):** Applicant's own code · campaign config/criteria/sources · infra it runs on (vLLM/router/DB/deploy) · new external integrations. **HARD RULE: every new piece of functionality is communicated to Kevin PROACTIVELY as it's being built** (not after).
- **AC (BDD):** *Given* a task (from user/Coach/self), *When* the Engineer builds it, *Then* it writes code + tests, passes the TDD/BDD gate, canaries on the e2e instance (suite + monkey-crawl), promotes with snapshot + health-gated auto-rollback, and proactively notifies Kevin — never auto-submitting an application or destroying data. **DoD:** end-to-end build→canary→promote→verify loop with all 4 safety layers, proactive comms, full audit; TDD+BDD; verified by a real feature shipped through it.

**Shared:**
- **Oversight (Q8 — ALL):** proactive notifications · live activity feed + audit log (with revert buttons) · daily digest · **global kill switch + per-action veto**.
- **Runtime (Q9):** **COPY the Agent-Zero coding stack (coder/reviewer/debugger + orchestration) INTO Applicant** so it is **entirely independent of the external Agent-Zero install**, running on **Applicant's own local+DeepSeek ladder**. (Reuse the proven A0 agent machinery, vendored in.) ⚠️ *Capability checkpoint: autonomous production coding on qwen-27B + deepseek-flash is weaker than a Claude-class coder — validate quality on real tasks before granting full auto-deploy; consider a stronger coding tier for the Engineer if quality is insufficient.*
- **Responsible gate on "parallel now" (Q10):** start building both immediately, BUT the Automation Engineer's **autonomous-DEPLOY authority stays OFF** until (a) the core pipeline is stably producing a full + relevant queue, and (b) the AE safety harness (Q6) is built + verified. Until then the AE builds + canaries + proposes; auto-promote flips on after that checkpoint. (Don't let a self-deploying agent loose on an unstable base.)
- **Relation to SELF-HEAL:** AE subsumes/extends EPIC SELF-HEAL (S1–S5 remediation become AE capabilities); RC is the strategic layer above it. Reconcile the two epics during design (no duplicate detectors/remediators).

**Story ladder (current state → fully implemented; ADR-0009 is Proposed — no RC/AE code exists yet: `grep -rl "automation_engineer\|reflection_coach" src/` returns only the EPIC MODEL-CONFIG use-case registry entry, `core/model_config.py` L137/146, not an implementation):**

- **RC-1 — Reflection Coach service: scheduled sibling of `CurationService`.**
  - **DoR:** `Scheduler.tick`'s daily-cadence idiom + `CurationService`'s "propose, stage, review" shape studied as the pattern to mirror; the event-driven trigger points (rejection, velocity stall, N-apps-sent, fit-trend-shift) identified in the existing `ApplicationStateChanged`/`OutcomeRecorded` handlers.
  - **AC:**
    - *Given* the daily cadence, *When* `Scheduler.tick` fires once per campaign per UTC day, *Then* RC runs an effectiveness pass over response/interview rate, velocity + time-in-stage, fit-score trend, and funnel progress vs. deadline.
    - *Given* an event-driven trigger (a rejection, a stall, N apps sent, a fit-trend shift), *Then* RC also evaluates off-cycle, consuming the same event bus every other detector uses.
    - *Given* the evaluation, *Then* it is a semantic LLM judgment over the aggregated signals ("is this getting the right job, faster"), not a threshold rule.
  - **DoD:** `ReflectionCoachService` (new, sibling of `CurationService`/the SELF-HEAL remediator — not a new agent runtime); daily + event-driven cadence wired through `Scheduler`; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `scheduler.py`'s daily-cadence idiom, `curation_service.py`'s propose/stage shape, `core/events.py`/`DomainEventBus`.

- **RC-2 — Auto-apply reversible criteria/strategy tweaks.**
  - **DoR:** RC-1 ships (effectiveness assessment produces a recommendation); `CriteriaService.apply_learned_adjustment`/`edit_criteria(confirm=...)` identified as the existing mutation seam.
  - **AC:** *Given* RC's assessment recommends a non-integral tweak, *When* applied, *Then* it goes through `apply_learned_adjustment` (auto-applied, transparent via `learned_adjustments`, one-click revert via `clear_learned`); *Given* it touches an integral field (`titles`/`locations`/`salary_floor`), *Then* it stages via `edit_criteria`'s confirmation gate like any other caller — RC never bypasses it.
  - **DoD:** RC calls the existing `CriteriaService` seam exclusively (no parallel mutation path); every applied tweak carries a human-readable summary + is revertible; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `criteria_service.py` (`apply_learned_adjustment`/`edit_criteria`) — RC is a new CALLER, not a new mutation mechanism.

- **RC-3 — Programmatic-need handoff to the Automation Engineer.**
  - **DoR:** RC-1/RC-2 ship; the "shared backlog queue" (routine) vs. "direct handoff" (urgent) split (Q4) scoped against `CurationService`'s `MemoryProposal`/`SkillProposal` staged-proposal shape as the pattern to mirror.
  - **AC:** *Given* RC surfaces a programmatic need (e.g. "a source keeps 403ing, needs a new connector"), *When* it is routine, *Then* it lands on a durable shared backlog table AE polls; *When* urgent, *Then* it directly invokes AE's task intake (mirrors `notify_error`'s IMMEDIATE-urgency bypass).
  - **DoD:** `ProgrammaticNeedRaised` domain event + shared backlog table; routine/urgent routing; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `curation_service.py`'s staged-proposal pattern; `NotificationService`'s urgency-routing precedent.

- **AE-1 — AE↔`a0-applicant` bridge service.**
  - **DoR:** the `a0-applicant/agents/{agent0,coder,coder-cloud,explorer,explorer-cloud,reviewer,security-auditor,debugger,test-engineer}` roster + `config/intel_tiers.yaml`/`intel_orchestration.yaml` confirmed already-vendored and contract-tested (grounded, ADR-0009 Context); confirmed by absence that nothing under `src/applicant/` calls this roster programmatically today.
  - **AC:** *Given* a task (from the user, RC, or self-detection), *When* AE hands it to the `agent0` overseer profile via the same `call_subordinate`/`orchestrate`/`subagent` shape a human operator uses today, *Then* AE gets back a result it can gate/canary/promote — no new model plane, routed through the existing Plane A tier topology.
  - **DoD:** a new, narrow bridge service in `src/applicant` (genuine new build, no existing seam); TDD+BDD; verified by a real task round-tripped through it.
  - **Reuse:** the already-vendored `a0-applicant/agents/*` roster + `config/intel_tiers.yaml`/`intel_orchestration.yaml` — no second coding stack.

- **AE-2 — Deploy safety harness: canary (build → disposable → full suite + monkey-crawl).**
  - **DoR:** AE-1 ships; the `applicant-e2e` disposable-instance recipe (`HANDOFF.md` §5.2) + `journey_via_sidebar.py`/`scripts/monkey_crawl.py` confirmed already-working manual tools.
  - **AC:** *Given* AE builds a change, *When* it canaries, *Then* it runs the `applicant-e2e` build→run-disposable→wait-for-200 sequence, then the full test suite + `journey_via_sidebar.py` + `monkey_crawl.py` against it; *Given* either fails, *Then* promotion is blocked.
  - **DoD:** the canary sequence is scripted/AE-driven (not human-typed); hard TDD/BDD gate enforced (no promotion without the change's own tests + BDD scenarios green); TDD+BDD; verified end-to-end.
  - **Reuse:** `applicant-e2e` recipe, `journey_via_sidebar.py`, `scripts/monkey_crawl.py` — a human-run recipe, automated, not reinvented.

- **AE-3 — Deploy safety harness: snapshot + auto-rollback on failed health.**
  - **DoR:** AE-2 ships; `/healthz`/`/api/health/capabilities` identified as the existing post-deploy signal; `scripts/install.sh`'s pre-migration snapshot step identified as the pattern to extend.
  - **AC:** *Given* AE promotes a build, *When* it does, *Then* a snapshot (image tag + DB/schema snapshot) precedes the promotion; *Given* a post-promote health check fails within the window, *Then* an automatic rollback to the snapshot fires with zero human action.
  - **DoD:** snapshot-before-promote + health-gated auto-rollback, a new narrow sibling of the updater sidecar's control-plane pattern (promote/health-check/rollback, not restart); a forced-failure drill proves rollback actually fires; TDD+BDD; verified on the e2e instance.
  - **Reuse:** `scripts/updater-daemon.sh`'s control-plane *pattern* (new implementation, scoped differently — genuine new build per ADR-0009 Consequences).

- **AE-4 — Proactive comms: every new capability communicated as it's built.**
  - **DoR:** AE-1 ships; `NotificationService`'s existing notification-kind pattern (`notify_error`/`notify_digest_ready`) identified as the channel to extend.
  - **AC:** *Given* AE starts building a new capability, *When* it does, *Then* Kevin is notified PROACTIVELY (as it's being built, not after) through a new `NotificationService` kind.
  - **DoD:** new notification kind (learned-tweak-applied / feature-shipped / remediation-outcome) reusing the existing escalation ladder; TDD+BDD; verified live.
  - **Reuse:** `notification_service.py` — new kind, not a new channel.

- **AE-5 — Global kill switch + per-action veto + revert buttons on the audit surface.**
  - **DoR:** the automated-work gate's "0 is the kill switch" convention (`agent_loop.py` L457, `scheduler.py`) identified as the shape to model, broadened; the audit panel (`app/routers/audit.py`) confirmed currently read-only.
  - **AC:**
    - *Given* the global kill switch is on, *When* checked at the top of RC's evaluation and every AE pipeline stage (build/canary/promote), *Then* all RC/AE activity halts.
    - *Given* a single proposed action (shared backlog queue, activity feed), *When* vetoed, *Then* only that item is blocked, not the whole system.
    - *Given* an audited RC action, *When* "revert" is clicked, *Then* `CriteriaService.edit_criteria(clear_learned=True)` runs (already the revert operation); *Given* an audited AE promotion, *When* "revert" is clicked, *Then* AE-3's snapshot-restore path runs.
  - **DoD:** kill switch + per-action veto wired at every RC/AE checkpoint; revert-button endpoints added to the audit surface (new UI/API wiring over existing-or-AE-3's-new reversal primitive); TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** the automated-work gate's convention; `AuditLogService`/`ActionEvent`; `CriteriaService.clear_learned`; AE-3's snapshot-restore.

- **AE-6 — Responsible gate (Q10): propose-only until the harness is independently verified.**
  - **DoR:** AE-2/AE-3 ship; the two-condition gate scoped ((a) core pipeline stably produces a full/relevant queue, (b) the harness is built AND independently verified via a forced-failure drill).
  - **AC:** *Given* the gate conditions are NOT both met, *When* AE completes a build+canary, *Then* it PROPOSES the promotion and a human approves it manually; *Given* both conditions are met and independently verified, *Then* the config flag flips and AE promotes autonomously with no redesign required.
  - **DoD:** a config flag on the AE-1 bridge service gates auto-promote vs. propose-only; both states tested; committed. **Stays OFF by default per Q10 — flipping it is a Kevin decision, not an agent decision.**
  - **Reuse:** AE-1's bridge service (a flag on existing logic, not a structural fork).

### EPIC MODEL-CONFIG — every model/endpoint choice is user-configurable in Settings (Kevin, 2026-08-10, STANDING)
**Principle:** There must be NO hardcoded model/endpoint decision. For **every use case** — scoring, drafting (cover letter / screening answers / résumé variant), research/enrichment, the campaign chat, the Reflection Coach, the Automation Engineer, embeddings, summarization, and any future LLM use — Kevin can choose **local or remote**, point at **any OpenAI-compatible endpoint** (arbitrary base_url + api_key + model name), and pick the model, all from the **Settings UI**. Every preference we've set (local qwen scoring · deepseek-v4-flash drafting · DeepSeek fallback tier · local+DeepSeek ladder · router/prefer-local) is a **DEFAULT preset in Settings, changeable by Kevin later** — never a fixed decision.
- **DoR:** the per-use-case LLM call sites are enumerable; there's an endpoint registry to reuse.
- **AC (BDD):**
  - *Given* the Settings UI, *When* I open model configuration, *Then* I see every use case with its current model/endpoint and can change each to local OR any remote OpenAI-compatible endpoint (base_url + key + model), tested/validated on save.
  - *Given* I set a use case to a custom endpoint, *When* that use case runs, *Then* it uses my chosen endpoint/model (not the default), and falls back per my configured fallback (also configurable).
  - *Given* a fresh install, *Then* the defaults are preset exactly as documented (local scoring, deepseek-v4-flash drafting, etc.) and everything still works out of the box with zero config.
  - *Given* I add an arbitrary OpenAI-compatible endpoint, *Then* it's usable for any use case (any endpoint supported, incl. OpenRouter, DeepSeek, local vLLM/Ollama, OpenAI, etc.).
- **DoD:** a per-use-case model/endpoint config surface in Settings, backed by the existing `ModelEndpointService` + tier ladder + `CriteriaService`/config (REUSE — do not build a parallel config system); defaults preset + overridable; add/test/validate arbitrary endpoints; every LLM call site reads its configured model/endpoint (no hardcoded model names); fresh-install-safe; TDD+BDD; verified on 10.0.1.11. **Also fold in the deferred tech-debt UI items** (model-endpoint enable/disable toggle, `llm_smart_routing` master flag, `POST /api/setup/llm/from-endpoint` UI) as part of this surface.

### EPIC EXPLAIN — per-posting score-explainability breakdown (Kevin, 2026-08-10, P2/lower)
**Principle:** On the review page, each posting shows a scannable **weighted greens/reds breakdown** — the positives (why it fits) and detractors (why it doesn't) that explain *why it got the score*, so scoring is a glass box, not a black box. **REUSE-FIRST:** ScoringService already computes the criterion evaluations (title/seniority, work-mode, location, salary, keyword overlap), a one-sentence `rationale`, and the learned taste/converting-role signature blend (FR-LEARN-1/5) — expose THOSE as structured factors; reuse FeedbackService/CriteriaService for the actionable path. Do NOT build a second scoring engine.
- **Confirmed decisions (Kevin):** factors from **both deterministic criteria + LLM nuance** (Q1); **weighted** — each factor's impact shown visually, exact numeric contribution on hover, reconciles with the score (Q2); **computed + stored at scoring time** so it displays instantly and matches the shown number (Q3); **actionable** — click/thumb a factor to feed profile learning so scoring improves (Q4, ties to RUX-5/FeedbackService); factor groups = role/title+seniority · logistics (remote/location/salary) · skills/Agile-domain keywords · company+recency+learned-taste · **+ any other relevant factor** (Q5); placement = **full weighted panel in the Review modal + compact top-plus/top-minus summary on each Pending-Reviews card** for at-a-glance triage (Q6).
- **DoR:** ScoringService's per-criterion evals + rationale + taste/signature are capturable as structured factors; a place to store the breakdown alongside the score exists (extend the stored score/rationale JSON — additive).
- **AC (BDD):**
  - *Given* a scored posting, *When* I open Review, *Then* I see a weighted breakdown of green (positive) and red (detractor) factors across the groups above, whose relative impacts visually explain the score, with the exact point contribution on hover.
  - *Given* a factor came from the LLM's semantic read vs a hard criterion, *Then* the two are visually distinguished, and a criterion pass/fail is never fabricated.
  - *Given* a factor, *When* I thumb/adjust it ("this shouldn't count" / "this matters more"), *Then* that feeds my profile learning (reuse FeedbackService → CriteriaService), transparently + reversibly, and future scoring reflects it.
  - *Given* the Pending-Reviews card, *Then* a compact top-plus/top-minus summary shows for triage without opening the modal.
  - *Given* scoring runs, *Then* the breakdown is computed + stored with the score (instant display, consistent with the number).
- **DoD:** breakdown computed + stored at scoring time (additive to the stored score/rationale structure); full weighted greens/reds panel in the Review modal (light+dark, HIG, per UIKIT-STANDARDS.md) + compact card summary; factors actionable → FeedbackService → learning; reuses ScoringService internals (no new scorer); TDD+BDD; verified on 10.0.1.11; fresh-install resilient.

### EPIC STEALTH — undetectable ingestion/apply + residential-IP-reputation protection (Kevin, 2026-08-10, P0-URGENT)
**Principle (Kevin):** "We need stealth. We cannot be detected at all. Our residential IP score MUST be protected." Automation must NEVER egress from Kevin's home IP, hard anti-bot targets must go through residential proxies with a matched browser fingerprint + human-like pacing, and the residential IP reputation must be actively conserved (sticky, selective, paced — never burned). The blocks we saw (Glassdoor 400 / ZipRecruiter 403) are the symptom.
**CURRENT-STATE ASSESSMENT (researched 2026-08-10 — the protection was built for the DESKTOP 10.0.1.225 but the live Applicant runs on 10.0.1.11, which was NEVER covered):**
- 🔴 **Live Applicant (10.0.1.11 `docker-api-1`) egresses from the HOME WAN IP `72.208.174.40`** — no WireGuard on 10.0.1.11 at all. **Actively burning Kevin's real residential IP reputation.** (Verified via `ipify` from the container.)
- 🔴 **Browser residential-escalation patch ABSENT on `docker-a0-1`** — never image-baked (known TODO in [[VPS Egress Node]]); today's a0 rebuilds wiped it. Apply-flow has no residential fallback on block.
- 🔴 **`EGRESS_PROXY`/`DISCOVERY_PROXIES` empty** → jobspy discovery hits boards from the home IP → 400/403 blocks. Proxy SEAM exists in code (`adapters/discovery/factory.py` `ProxyConfig`, `clients.py`, `url_intake.py` all accept `proxy=`) — just unconfigured.
- 🟡 `BROWSER_ENGINE=camoufox` set but fingerprint-injection unverified where Applicant's browser actually runs; `CAPTCHA_SERVICE=capsolver` but `CAPTCHA_API_KEY` empty.
**EXISTING INFRA TO REUSE (from [[VPS Egress Node]] / [[Camoufox Install]] — do NOT rebuild):** VPS WireGuard egress `173.254.204.32` (LA RackNerd); DataImpulse residential proxy via VPS tunnel forwarder `http://10.8.0.1:8880` (sticky-US, `sessid` labels, ~30-min hold); Camoufox anti-detect Firefox; the a0 browser-proxy patch (`~/agent-zero-ops/browser-proxy-patch/deploy.sh`); the daily `egress-reputation-watchdog` Claude task; API-first ATS connectors (Greenhouse/Lever, keyless = zero IP risk).
**Slices:**
- **ST-1 (P0-URGENT) — route 10.0.1.11 through the VPS egress.** Replicate the desktop's WG-client + Docker source-policy-routing pattern (container subnets 172.17/172.18 → table 200 → `wg0`; LAN 10.0.1.0/24 + local-model + SSH stay DIRECT) so ALL Applicant automation egresses from the VPS, not the home IP. **AC:** *Given* the live engine, *When* it fetches any external URL, *Then* the source IP is the VPS (173.254.204.32), never `72.208.174.40`; LAN + local-model + SSH unaffected. **Needs:** VPS-side `[Peer]` add (VPS creds user-held) + 10.0.1.11 WG client. *(Kevin: this is the one actively harming your IP — recommend executing ASAP.)*
- **ST-2 (P0) — wire residential proxy into discovery.** Point `DISCOVERY_PROXIES`/`EGRESS_PROXY` at `http://10.8.0.1:8880` for block-prone jobspy sources (LinkedIn/Indeed/Glassdoor/ZipRecruiter/Google), selectively (on block-detect) + sticky-US per flow; keyless-ATS + APIs stay direct (no GB burn). **AC:** jobspy sources stop 400/403-ing; hard fetches exit a residential IP; ATS/API stay direct.
- **ST-3 (P1) — re-apply + BAKE the browser residential-escalation patch into the a0 image** so it survives rebuilds (the standing TODO), + WebRTC-leak suppression. **AC:** after any a0 rebuild, the apply-flow browser still escalates to residential on 403/429/503/Cloudflare/DataDome, sticky per flow.
- **ST-4 (P1) — verify + enforce Camoufox fingerprint** in Applicant's actual apply-flow browser (Windows UA / geoip matched to the exit/proxy IP). **AC:** the apply browser presents a consistent, non-headless, geoip-matched fingerprint.
- **ST-5 (P1) — residential-reputation conservation + behavior:** sticky per-flow `sessid` (browse→apply = one identity), selective escalation (don't burn GB on easy targets), human-like pacing/rate-limits/backoff, IPv6/DNS-leak suppression on 10.0.1.11, identity hygiene (never personal accounts from the bot browser). **AC:** one residential IP per apply-flow; no leaks (IPv6/DNS/WebRTC); paced requests; GB usage bounded.
- **ST-6 (P2) — coverage + detection:** extend the `egress-reputation-watchdog` to include 10.0.1.11 (alert if it ever egresses home-IP); wire capsolver key + CAPTCHA strategy; API-first preference (reconcile w/ DISCOVERY-BREADTH — prefer keyless ATS/APIs over scraping wherever possible); use the existing `detection_events` table to log + react to blocks.
**DoR:** current-state assessed (above); VPS + DataImpulse + patch infra exist. **DoD:** live Applicant NEVER egresses home-IP; hard targets via residential + matched fingerprint + pacing; no IPv6/DNS/WebRTC leaks; residential IP score conserved (sticky/selective/paced); browser patch image-baked; verified by egress-IP checks + a Cloudflare/challenge canary + fault injection; watchdog covers 10.0.1.11; TDD+BDD; fresh-install resilient. See [[VPS Egress Node]] · [[Camoufox Install]].

### EPIC DISCOVERY — verified-source, wide-net job-posting ingestion (Kevin, 2026-08-11) · see ADR-0015
**Principle (Kevin, verbatim):** "We only scrape jobs from verified sources… the only entity we receive is a job posting." "Throw the net as wide as you possibly can… prioritize aggregators but direct connections are useful… we can't limit ourselves to specific industries." Breadth of SOURCE, never looseness of SHAPE: cast the widest possible net, industry-agnostic, but every row that reaches `job_postings` must first prove it is a real, verifiable posting. This was the single biggest known gap (no ADR existed) despite being the top of the funnel everything else depends on. **REUSE-FIRST:** `adapters/discovery/validate.py` (`validate_provider_rows`/`validate_postings_shape`) is the ONE real-postings gate, reused at both the runtime `DiscoveryService.add_board` write path and the offline `scripts/validate_discovery_boards.py` check; the keyless connector roster (`clients.py`/`factory.py`: Greenhouse/Lever/Ashby/SmartRecruiters/Workday direct + RemoteOk/Remotive/WorkingNomads aggregators + jobspy/SearXNG/RSS) and the circuit-breaker/pacing layer (`jobspy_searxng.py`'s `SourceCircuitBreaker`/`PerBoardRateLimiter`) already exist. Do NOT build a second validation gate or a second connector framework.

- **DISC-1 — Real-posting-shape validation gate at ingestion.** ✅
  - **DoR:** provider response shapes catalogued (title-field + identity/URL-field per provider, `PROVIDER_SHAPES`); `add_board` identified as the runtime write path to gate.
  - **AC:**
    - *Given* a candidate board's fetched response, *When* it is empty, a 404-turned-`[]`, or has no row with both a title and an identity/URL field, *Then* `validate_provider_rows` returns `ok=False` and the board is NEVER persisted/registered.
    - *Given* a response with real postings mixed with malformed rows, *When* validated, *Then* `posting_count` reports only the rows that passed shape-validation, never the raw row count.
    - *Given* an unrecognized provider key, *Then* the gate fails closed (`unknown provider`), never silently passing.
  - **DoD:** `adapters/discovery/validate.py` + `DiscoveryService.add_board` (L211-266) enforce the gate; committed, unit-tested, verified live (board add rejects a dead slug).
  - **Reuse:** `adapters/discovery/validate.py` — the one enforcement point for both callers below.

- **DISC-2 — Keyless direct-ATS connector roster.** ✅
  - **DoR:** target ATS platforms identified (Greenhouse/Lever/Ashby/SmartRecruiters/Workday), each with a public keyless listing API.
  - **AC:**
    - *Given* `DISCOVERY_LIVE=true` and a configured `DISCOVERY_{GREENHOUSE,LEVER,ASHBY,SMARTRECRUITERS,WORKDAY}_*` token list, *When* discovery runs, *Then* each live client fetches real postings with zero API key / zero login.
    - *Given* the test lane, *Then* every connector has a `Fake*` counterpart so tests run with zero network.
  - **DoD:** `Live{Greenhouse,Lever,Workday,Ashby,SmartRecruiters}Client` + `Fake*` siblings in `adapters/discovery/clients.py`; wired in `factory.py`; `PROVIDER_SHAPES` covers all five; committed + deployed (seed companies ingesting live per [[Applicant — ATS Discovery Connectors]]).
  - **Reuse:** `adapters/discovery/clients.py`/`factory.py` — new ATS platforms extend this roster, never a parallel client layer.

- **DISC-3 — Aggregator connectors (breadth-per-integration).** ✅
  - **DoR:** aggregator sources identified that publish many companies' postings behind one feed (RemoteOk, Remotive, WorkingNomads) alongside the existing jobspy/SearXNG/RSS aggregators.
  - **AC:**
    - *Given* an aggregator connector, *When* discovery runs, *Then* postings from many companies are ingested through ONE connector, keyless, industry-agnostic (no title/role/industry allowlist at this layer).
    - *Given* an RSS feed URL, *Then* `LiveRssClient` ingests it the same way as any other source (arbitrary direct-connection breadth beyond the named aggregators).
  - **DoD:** `Live{RemoteOk,Remotive,WorkingNomads}Client` + `LiveRssClient`/`LiveSearxngClient`/`LiveJobSpyClient` in `clients.py`; `PROVIDER_SHAPES` covers the three named aggregators; committed + live.
  - **Reuse:** same `clients.py`/`factory.py` roster as DISC-2; aggregators and direct connections share one framework.

- **DISC-4 — Board-validation as a CI gate (not just an operator tool).**
  - **DoR:** `scripts/validate_discovery_boards.py` exists and runs standalone; no CI workflow currently invokes it (grepped `.github/**/*.yml` for `validate_discovery_boards` — no hits).
  - **AC:**
    - *Given* a scheduled/CI job, *When* it runs `validate_discovery_boards.py` against every `DISCOVERY_*`-configured board, *Then* a board that has gone dead (renamed slug, ATS migration, taken down) fails the job loudly instead of silently degrading discovery.
    - *Given* every configured board still validates, *Then* the job is a no-op green check.
  - **DoD:** a CI workflow (or scheduled task) invokes `scripts/validate_discovery_boards.py` on a cadence + on deploy; a forced-dead-board drill proves it fails loudly; committed.
  - **Reuse:** `scripts/validate_discovery_boards.py` + `validate.py` — only new invocation, no new validation logic.

- **DISC-5 — Source-reliability tiers cover every shipped connector.**
  - **DoR:** `core/rules/source_reliability.py`'s `SOURCE_TIERS` audited against `clients.py`'s actual roster — gap confirmed: `ashby`/`smartrecruiters`/`workday`/`remoteok`/`remotive`/`workingnomads` are missing (fall through to the conservative "unknown → medium" default) while `greenhouse`/`lever` already get `high`.
  - **AC:** *Given* a posting sourced from any of the six missing connectors, *When* reliability is scored, *Then* it uses that connector's real tier (`high` for direct public ATS APIs, matching greenhouse/lever; an aggregator-appropriate tier for remoteok/remotive/workingnomads), not the generic default.
  - **DoD:** `SOURCE_TIERS` extended for all six; unit test asserting every key in `clients.py`'s live-client roster has a `SOURCE_TIERS` entry (regression guard against future drift); committed.
  - **Reuse:** `core/rules/source_reliability.py` — data-only change, no new module.

- **DISC-6 — `easy_apply` tagging parity across the connector roster.** ✅
  - **DoR:** assisted-apply parity identified as a cross-connector requirement (quick-apply prioritization downstream needs a consistent signal).
  - **AC:** *Given* a posting from Greenhouse/Lever/Ashby/SmartRecruiters/Workday, *Then* `easy_apply=True` is set (assisted-apply parity); *Given* LinkedIn/other sources with a native quick-apply attribute, *Then* `detect_easy_apply` honors the source's own explicit flag first.
  - **DoD:** `detect_easy_apply` + per-provider mappers in `jobspy_searxng.py`; committed + live.
  - **Reuse:** `jobspy_searxng.py`'s existing mappers.

- **DISC-7 — No-industry-filter invariant, enforced by test.**
  - **DoR:** the "can't limit ourselves to specific industries" requirement is currently true by construction (no connector carries an industry allowlist) but unenforced — nothing stops a future connector from adding one to "clean up" its feed.
  - **AC:** *Given* every discovery connector in `clients.py`, *Then* a regression test asserts none filters rows by industry/title/role — that narrowing happens exclusively in `core/rules/role_domain_fit.py`, downstream, at scoring.
  - **DoD:** a contract-style test (mirrors `test_intel_tier_topology.py`'s "assert the roster shape" pattern) fails if a connector introduces industry filtering; committed.
  - **Reuse:** existing connector roster; test-only addition, no new runtime code.

### EPIC MATERIAL-QUALITY — degraded résumé variants + malformed screening targets never reach review (#44)
**Principle:** A drafted application that reaches Kevin's review queue must be genuinely tailored — never a silently-degraded fallback résumé variant, never a screening answer written against the wrong/malformed question. **REUSE-FIRST:** `MaterialService` already tracks its own degradation (`last_generation_degraded`, `_degraded_marker`, `_note_silent_degradation`, `emit_degradation_diagnostic`) and screening-answer generation (`generate_screening_answer`, `generate_for_deferred_question`) — this epic makes those existing signals BLOCKING/visible instead of silent, and adds a target-integrity check to screening answers. Do NOT build a second material-generation pipeline.

- **MAT-1 — Degraded résumé variant never reaches review silently.**
  - **DoR:** `MaterialService.last_generation_degraded`/`_note_silent_degradation` identified as the existing (currently internal-only) degradation signal; the review-queue surfacing point (Pending Reviews / RUX flow) identified.
  - **AC:**
    - *Given* a résumé variant generation that fell back to degraded output (LLM failure, empty tailoring), *When* it would enter the review queue, *Then* the item is flagged as degraded (visible badge/marker), never presented as a normal tailored draft.
    - *Given* `emit_degradation_diagnostic` fires past its threshold, *Then* it is surfaced to the operator/self-heal surface (ties EPIC SELF-HEAL), not only logged.
  - **DoD:** degraded variants carry a visible, honest marker through to the review UI; diagnostic threshold wired to an existing notification/audit surface; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `MaterialService._degraded_marker`/`_with_degraded_marker`/`emit_degradation_diagnostic` (extend visibility, don't rebuild the detector).

- **MAT-2 — Screening-answer target integrity (never answer the wrong question).**
  - **DoR:** `generate_screening_answer`/`generate_for_deferred_question` identified as the generation seam; the failure mode (a generated answer that doesn't address the actual asked question — a malformed/mismatched target) scoped.
  - **AC:**
    - *Given* a screening question extracted from a posting, *When* an answer is generated, *Then* the answer is checked against the question it claims to answer (a lightweight relevance/target check) before it is offered for review.
    - *Given* the check fails (answer doesn't address the question), *Then* the item is flagged for regeneration/human review rather than silently shipped as a normal answer.
  - **DoD:** a target-integrity check wraps `generate_screening_answer`/`generate_for_deferred_question`'s output; flagged mismatches surfaced in review; TDD+BDD; verified on 10.0.1.11.
  - **Reuse:** `MaterialService.generate_screening_answer`/`generate_for_deferred_question` (wrap, don't duplicate).

- **MAT-3 — Regression coverage: degraded-fallback fixtures never silently pass quality checks.**
  - **DoR:** the existing "New-draft quality re-check (P1)" DONE item (backlog, verified real LLM-tailored content 2026-08-10) identified as the last manual spot-check; no standing automated regression exists.
  - **AC:** *Given* a fixture that simulates a degraded/fallback generation, *When* the quality-check suite runs, *Then* it is caught (not silently graded as normal tailored content) — closing the gap the manual 2026-08-10 check covered once, ongoing.
  - **DoD:** an automated test fixture + assertion added alongside the existing material-generation test suite; committed.
  - **Reuse:** existing material-generation test suite (extend, don't fork).

## ✅ DONE + verified this cycle (P0/P1)

- **B1 Digest reads stored scores** — build_digest no longer LLM-re-scores in the hot path. Committed + baked. (Part of the perf story below.)
- **B2 Auto-register local LLM endpoint on boot** — a fresh install now gets a working chat/routing endpoint with no manual step. Verified `endpoints_online: 1` on a clean boot.
- **B3 vLLM stops wedging** — router is qwen-only (GLM swaps disabled); no re-wedge. (Kevin's box, backup kept.)
- **B4 Bound per-tick scoring + digest perf (the thundering-herd)** — scorer walked the whole 4k backlog every tick AND build_digest did 266 full posting-scans per build (167s). Fixed: per-tick scoring cap (SCORING_BATCH_PER_TICK, default 20) + hoisted the campaign-wide reads out of the per-row warnings loop. **Digest 167s → 1.5s warm.** Verified.
- **B6 Rebuild prod from source** — api rebuilt from HEAD, migration applied, data intact; all fixes baked. (a0 rebuild pending the landing page.)
- **RESEARCH-400 (owner attribution)** — engine never sent `X-Applicant-Owner`; companion 400'd every callback. Fixed via `default_owner` (APPLICANT_OWNER, default "applicant") — clears research + calendar/emails/memory lanes. Committed + baked.
- **Latest build on remote** — all 370+ commits pushed to GitHub; prod == HEAD (was ~370 behind).
- **UI monkey crawl** — 23 broken panels → 0 (campaigns API shape, undefined callJsonApi, Alpine x-for crashes, /api/setup/automation 404, tiers config path). Committed + baked.
- **Self-drafting works** — 5 DIGESTED drafts for top-fit roles with genuinely tailored materials (verified real Wells Fargo/Slalom/Ally content); Today shows a 22-item review queue. Review-gated, never auto-submitted.

## ✅ DONE this cycle (cont.)

- **APP-LP-1 Landing-page overhaul** — DONE + verified (`4ee732e1`). Command-center root: Pending Reviews (score badges, sorted best-fit, inline Review/Approve/Snooze) → Top New Matches (score + why + Draft/Skip) → Pipeline Funnel → Daily Progress → notifications-connect + System Resources; clutter cut; chat kept. Reused digest/pending endpoints; 1 justified new endpoint (pipeline-summary). Contrast measured (5–11:1) light+dark; **also fixed an app-wide light-mode theme freeze** (buttons/badges/cards) + the sidebar white-on-white + the branding logo. Delivers B5 (review UX). Baked (a0+api image rebuild).

## 🔜 IN PROGRESS (delegated agents, overseer integrates+deploys)

- **SCORE-P0 — transient LLM failure poisons viability scores (FROZEN PIPELINE).** *Root-caused 2026-08-10 midday.* Live: 5376 postings / 1266 scored / **0 viable (>=70)** → auto-draft starved → review queue frozen at 4 old drafts. Cause: `scoring_service._base_score` catches any LLM exception (cold-start/loaded-vLLM call >60s HTTP timeout) and **degrades to embedding similarity, which ~never reaches 70, then persists it** — and `agent_loop` only scores UNSCORED postings, so the poisoned score is never retried. Config is CORRECT (tier qwen3.6:27b @10.0.1.225/v1; a warm `complete()` scores real roles 75-85). **DoR:** root-caused w/ file anchors; config confirmed good. **DoD:** (1) transient LLM failure leaves posting UNSCORED/retryable (never persist embedding score when an LLM is configured) w/ bounded-retry safety valve; (2) LLM HTTP timeout raised + env-configurable + defaulted in compose; (3) test proving it; committed. THEN overseer: deploy + live re-score of poisoned postings + verify viable>0 + queue grows. *(Agent running.)*
- **MODEL-RESILIENCY — local-primary + deterministic DeepSeek(-compatible) cloud FALLBACK tier.** Kevin: "if local fails or is unavailable, deterministic fallback to DeepSeek API (or compatible endpoint), IN ADDITION to the existing auto-escalation." Folded into SCORE-P0 (same ladder subsystem; a real fallback tier is the robust cure — the ladder climbs to cloud on local failure instead of degrading to embeddings). **DoD:** ladder holds local-primary + optional cloud tier, env-configured (`LLM_FALLBACK_BASE_URL`/`_MODEL`/`_API_KEY`/`_PROVIDER`, default DeepSeek), OFF without a key (byte-identical to today), dropped under private/local-only mode, appended so existing escalation uses it; unit test; compose vars. THEN overseer: drop the real key on the box + activate + verify escalation live. Key exists in A0 stack (secret-injected; Kevin to supply the value — never handled in chat). *(Folded into running agent.)*
- **APP-LP-2 — posting date + freshness on Pending Reviews / role cards.** Kevin: a high-fit role posted a month ago is probably filled; the posted date is decision-critical. **DoR:** job_postings has a date field to surface. **DoD:** posted date + relative-freshness cue on every scored Pending Review row + Digest/Top-Matches cards, both themes, stale roles visually de-emphasized, reuses existing payload (no redundant endpoint), graceful when unknown; committed (`e298110dd`) + DEPLOYED + live. **DONE.**
- **APP-UIKIT-1 — design-system / UIKit standard (P2, "nice to have").** Kevin wants codified color/contrast/HIG standards for future UI consistency. **DoD:** `docs/UIKIT-STANDARDS.md` derived from real source (theme tokens light+dark, `.light-mode` leak trap, typography/spacing, component patterns, WCAG/HIG targets + do/don'ts, recipes + pre-ship checklist), file-cited; committed. *(Agent running.)*

- **DISCOVERY-BREADTH (P1, CRITICAL-TO-QUALITY) — maximize job-posting reach across the internet.** Kevin: "widen the net to as full a reach as I possibly can get — the most postings possible gives me the most edge." **Superseded/formalized by EPIC DISCOVERY · ADR-0015** (above) — the connector roster this item scoped (jobspy + Greenhouse/Lever/Ashby/SmartRecruiters/Workday + RemoteOk/Remotive/WorkingNomads aggregators) now has its own ADR + decomposed DISC-1..7 story ladder, with DISC-1/2/3/6 already ✅ shipped and DISC-4/5/7 tracking the remaining CI-gate/reliability-tier/industry-invariant gaps. This entry stays only as the original P1 scoping request pointer — see EPIC DISCOVERY for current AC/DoD. See [[Applicant — ATS Discovery Connectors]].
- **Tech-Debt burn-down (PARALLEL, overseer)** — audit DONE → `docs/TECH-DEBT-REGISTER.md` (128 items: 21 UNEXPOSED / 18 PARTIAL / 7 DUP / 7 UNWIRED; 4 P0). Now: parallel per-domain FIX agents (isolated worktrees, commit only) → coordinator cherry-picks + ONE batched rebuild/deploy → verify. Covers the 4 P0s (base-résumé overwrite, easy-apply consent, model-endpoint JSON/Form=B7, ops-allowlist recovery) + P1 UNEXPOSED/PARTIAL + DUP. Deferred to a later serial wave: the 18-file `_engine_client` consolidation (conflicts with everyone).

### Landing page (APP-LP-1 shipped) — open follow-ups
- [ ] channels.html "Current configuration" display reads response fields the API no longer returns (now `*_configured` booleans, by design) — fix the display. (Agent-flagged, pre-existing.)
- [x] Coordinator live **light-mode self-verify** — DONE 2026-08-10: captured fresh live light + dark full-page from the deployed build, both fully readable (no white-on-white), match score restored on Pending Reviews, 0 console errors; screenshots sent to Kevin.
- [ ] Post-burndown **full visual re-pass** (light+dark, all panels) once fixes land.

## ⏳ TODO

- **B4-deep (P2)** digest cold build still ~15s (first call after restart / cache-invalidation); warm is 1.5s. Optional: warnings only need the ~5 apps' postings, not all 5376 — make it size-independent.
- **RESEARCH-503 (P1)** with owner fixed, `/research` now 503s: the COMPANION has no research/default LLM endpoint. Mirror the engine's auto-register on the companion so research enrichment actually runs. (Enrichment only — not a draft blocker.)
- **B7 (P1) model_endpoints proxy JSON→Form** — engine `add_endpoint` uses Form; the plugin proxy sends JSON → UI "Add endpoint" fails. (Endpoint auto-registers now, so lower urgency.)
- **B8 (P1) idle-in-transaction sessions** — boot/tick sessions leave transactions open (ClientRead ~6 min), blocking VACUUM on job_postings. (NOT the digest cause — that was the per-row scans, fixed. Separate hygiene item.)
- **B10 branding (P2)** — logo wordmark + `.js` substitution done in source; bakes on the next a0 rebuild (landing-page agent's rebuild). Verify no "Agent Zero" post-bake.
- **B12 (P2) modal titles show raw file paths** (e.g. `/plugins/applicant/webui/digest.html`) — give panels friendly titles.
- **B13 (P2) full visual QA re-pass** — after landing page + branding land, re-run the visual crawl in light + dark.
- **UI-DEBT-1 (P1 contrast, from UIKIT audit `e1009e937`)** — real WCAG fails found by cascade analysis: `--color-text-secondary` (#5a5a5a, one literal shared by both themes) = **2.7:1 on dark** (fail), used in nearly every panel's meta text; dark-mode primary buttons **4.35:1** (borderline AA); `.card/.item/.surface` inherit `--ap-color-text` + `--color-input-bg:#fff` declared only at `:root` (no `.light-mode` counterpart) → potential white-on-white card in dark default (static-analysis, **not yet screen-confirmed** — my live shots looked OK, so verify before fixing). **DoR/AC/DoD + TDD/BDD** per standing conventions. Fix = theme-scoped tokens per UIKIT-STANDARDS.md.
- **UI-DEBT-2 (P2, from UIKIT audit)** — three divergent status-badge color paths (canonical tokens vs `digest.html` typo'd `--color-warn-bg` that never resolves vs `documents.html` hardcoded literals); + design tokens adopted by 0/41 panels (all hardcode raw px/rem). Consolidate onto the UIKIT scale. Standing conventions apply.
- ~~**New-draft quality re-check (P1)**~~ — DONE 2026-08-10: verified live materials are real LLM-tailored content (cover letters avg 1721 chars w/ role-specific rationale; screening answers present; work-auth answers correctly use stored policy, never guessed). NOT deterministic fallback.

## Done earlier (foundation)
- Fresh install on 10.0.1.11; campaign recreated; OOM root-caused (sequential builds); install/update system + fork-safe Update button; discovery resilience (Greenhouse/Lever + circuit breaker).

## 🧠 EPIC MIND-DURABLE — curated agent-memory survives an engine restart (#286, FR-MIND-1/2/3, FR-DUR-3) · see ADR-0010
**Principle (Kevin):** *A "remembers you" product cannot lose what it learned on a restart.* The deployed engine ran `MIND_BACKEND=in_memory`, so the curated-memory / skills / recall trio was in-process and EPHEMERAL — every restart/rebuild wiped it. The prior durable option (`bridge`→companion) was disabled for stalling the digest read path ~45s, so durability must NOT add a network/companion dependency to the read path. **REUSE-FIRST:** the SQLAlchemy models/session/alembic stack, the pure `core/rules/agent_memory` bounds policy, the `session_factory` the container already builds, and the `pg_credential_store` short-lived-session idiom ALL exist — this is a new durable adapter over them, not a new framework.

**Story ladder (current state → fully implemented; decomposes the durable-memory build into DoR/AC/DoD-bearing stories — the first four are BUILT + TESTED + COMMITTED on this branch, grounded by file: `adapters/memory/sql_backend.py` (15.9KB), `adapters/storage/alembic/versions/0015_agent_memory.py`, and `tests/{unit/test_agent_memory_sql_backend.py, contract/test_agent_memory_contract.py, migrations/test_agent_memory_migration.py}` all exist on disk; ONLY the final deploy/restart-verify step remains):**

- **MEM-1 — Schema + migration: `memory_entries`/`skills`/`recall_entries`.** ✅
  - **DoR:** ports (`MemoryStore`/`SkillStore`/`RecallIndex`) + `in_memory` reference behavior + storage/alembic idioms studied.
  - **AC:** *Given* `alembic upgrade head`, *Then* the three tables + indexes (`ix_memory_entries_scope_campaign_kind`, `ix_skills_scope_campaign`, recall's `campaign_id` index) are created; *And* `downgrade` cleanly drops them.
  - **DoD:** 3 SQLAlchemy models registered with `Base.metadata` (`memory_entries` INTEGER-PK for insertion order, `skills` name-PK, `recall_entries` run_id-PK); `alembic/versions/0015_agent_memory.py` (up+down tested, `tests/migrations/test_agent_memory_migration.py`); committed.
  - **Reuse:** the existing SQLAlchemy models/session/alembic stack — no new schema framework.

- **MEM-2 — `SqlMemoryStore`/`SqlSkillStore`/`SqlRecallIndex` adapters, behaviorally identical to `in_memory`.** ✅
  - **DoR:** MEM-1 ships; `in_memory.py`'s add/replace/remove/snapshot semantics studied as the contract to match exactly.
  - **AC:**
    - *Given* the SQL trio, *Then* it passes the SAME add / replace(first substring match) / remove(all substring matches, returns count) / snapshot(scope+campaign filtering, kind split, char-bounds + `truncated`) behavior as `in_memory` (parametrized contract over BOTH adapters, `tests/contract/test_agent_memory_contract.py`).
    - *Given* concurrent `add()`s from many sessions, *Then* none are lost and none deadlock (short-lived session per op, never the per-tick isolated Session).
    - *Given* a populated table, *When* `snapshot()` runs, *Then* it is a SINGLE indexed query returning under a tight budget (<50ms on the test DB) — the guard against re-introducing the disabled `bridge` backend's ~45s hot-path stall.
  - **DoD:** `adapters/memory/sql_backend.py`'s `SqlMemoryStore`/`SqlSkillStore`/`SqlRecallIndex`; `snapshot()` enforces the same char bounds as `InMemoryMemoryStore` via `core/rules/agent_memory.enforce_bounds`; `recall.search()` reuses `in_memory._tokenize`, local, no network; committed.
  - **Reuse:** `core/rules/agent_memory.enforce_bounds` (the pure bounds policy, shared with `in_memory` — one policy, two adapters).

- **MEM-3 — Bounded growth (per-(scope,campaign) row cap).** ✅
  - **DoR:** MEM-2 ships; `learning_service.cap_feature_stats`'s "cap it so a rewritten blob can't grow unbounded" philosophy identified as the pattern to mirror.
  - **AC:** *Given* many writes past the cap (default 500), *Then* `add()` prunes the oldest rows beyond the per-(scope,campaign) cap, keeping the table — and the snapshot query — bounded over a 24/7 lifetime.
  - **DoD:** pruning logic in `sql_backend.py`'s `add()`; unit-tested; committed.
  - **Reuse:** `learning_service.cap_feature_stats`'s capping philosophy (same rule, new table).

- **MEM-4 — Wiring: `build_agent_memory` `sql` branch + container `session_factory` + config defaults.** ✅
  - **DoR:** MEM-1/MEM-2 ship; `container.py`'s existing `session_factory` construction site identified.
  - **AC:**
    - *Given* `MIND_BACKEND=sql` with a reachable DB, *When* `build_agent_memory` runs, *Then* it returns the SQL trio; *Given* `sql` with NO reachable DB, *Then* it falls back to `in_memory` so boot and the hermetic test lane stay safe.
    - *Given* a fresh install with no override, *Then* the test lane still defaults to `in_memory` (fast, isolated) while `docker-compose.prod.yml` defaults to `sql` (confirmed: `MIND_BACKEND: ${MIND_BACKEND:-sql}`).
  - **DoD:** `build_agent_memory` gains a keyword-only `session_factory` (backward-compatible — existing 2-arg callers unchanged); container threads its existing `session_factory` in; `app/config.py`'s `mind_backend` field default stays `in_memory` (test-safe), prod compose sets `sql`; committed.
  - **Reuse:** the container's already-built `session_factory` (the `pg_credential_store` short-lived-session idiom) — no new session management.

- **MEM-5 — Deploy + restart-verify on 10.0.1.11.**
  - **DoR:** MEM-1..MEM-4 built + tested + committed on branch (confirmed above); `alembic upgrade head` already runs in `install.sh`/`update.sh` before the api serves.
  - **AC:**
    - *Given* the live 10.0.1.11 engine, *When* deployed with this branch + `alembic upgrade head` run, *Then* the three new tables exist in the production database.
    - *Given* a stated user preference recorded post-deploy, *When* the engine restarts/rebuilds, *Then* the rebuilt agent still recalls that preference — the restart-survival headline, proved live, not just in the test lane.
  - **DoD:** deployed to 10.0.1.11; migration applied; a live restart-and-recall smoke test passes; **Overseer (parent) deploys, migrates on the server, restart-verifies, seeds** — this is the one remaining open item for EPIC MIND-DURABLE.
  - **Reuse:** `scripts/install.sh`/`update.sh`'s existing `alembic upgrade head` step — no new deploy mechanism.

---

## 🎯 EPICS — Fit Engine + Companion (Kevin, 2026-08-11; from ADR-0011/0012/0013/0014)

### EPIC FIT-MODEL — Candidate competitiveness model, not flat attributes · see ADR-0011
**Principle:** Model the candidate's real COMPETITIVENESS from the résumé — the substrate for judging "would this candidate get a *call*?" — not just parse facts. **REUSE-FIRST:** derive OVER the existing attribute cloud (`AttributeCloudService`) + `onboarding.base_resume` (raw + parsed) with the wired LLM tier + local embeddings; persist per-campaign via the existing storage pattern. Do NOT build a second résumé parser.
- **DoR:** ADR-0011 accepted; the parsed résumé + attribute cloud expose enough to derive title-history/level/certs/degree/industries/skills-with-evidence/wins/tech-depth; a per-campaign persistence slot exists (additive).
- **AC (BDD):**
  - *Given* a completed résumé, *When* the fit model derives, *Then* it captures title/role history (roles held + level + primary-vs-stretch), typed certs, **degree presence** (explicit), industries (depth/recency), skills (evidence strength), quantified wins, and true technical depth — as structured fields, not free text.
  - *Given* the model, *Then* it derives `strong_fit` / `viable_stretch` role families **with a rationale each**, computed from the candidate (never hand-authored — this is what generalizes it; ties to #46).
  - *Given* a résumé change, *Then* the model re-derives (cached; only on change); *And* a sparse résumé degrades gracefully to today's attribute-only behavior.
- **DoD:** `CandidateProfile` entity + `CandidateProfileService`; strong-fit/stretch bands derived + explainable; persisted per campaign; TDD+BDD; verified on 10.0.1.11; fresh-install resilient.

### EPIC FIT-SCORING — Score "would they get a call?", not "is it in-domain?" · see ADR-0012 (supersedes the hardcoded allowlist; folds in #46)
**Principle:** Scoring becomes a FIT judgment over the Candidate Fit Model × the posting — the reach-vs-strong-fit call Claude makes by hand, systematized. **REUSE-FIRST:** extend `core/rules/role_domain_fit.py` to DERIVE its allowlist from the fit model (generalizing #46); keep the deterministic gates (`posting_quality`, US-remote) + the ranking factors already specified; the LLM assists on nuance, never as the primary discriminator (banked lesson). Do NOT build a second scorer.
- **DoR:** ADR-0011 shipped (fit model available); ADR-0012 accepted; `role_domain_fit`/`scoring_service` are extensible with a profile-derived tier + competitiveness signals; postings expose location/salary/description to parse degree/level/industry.
- **AC (BDD):**
  - *Given* a posting + the fit model, *When* scored, *Then* it passes the hard gates (real posting, **US-remote** inferred when `work_mode` is null) or is gated out; *And* it is placed in a fit tier **derived from the model**, not a hardcoded list.
  - *Given* two equally-fresh viable roles, *When* one matches the candidate's actual title history and the other is a stretch, *Then* the strong-fit role scores higher (a Scrum Master / Agile Coach out-ranks an equivalent big-tech TPM for THIS candidate).
  - *Given* a posting that HARD-REQUIRES a degree the candidate lacks, *Then* it is penalized; "preferred"/unstated = neutral.
  - *Given* the same engine + a DIFFERENT candidate/target role, *Then* the fit tiers re-derive from THAT profile — no code change (generalizes; #46).
  - *Given* any score, *Then* it carries an explainable fit rationale (feeds EXPLAIN).
- **DoD:** `role_domain_fit.derive_from_profile()` + competitiveness signals (title-match, degree gate, level, industry) layered into scoring, deterministic-first; the hardcoded Agile list remains ONLY as the derived default until derivation ships (no regression); TDD+BDD; verified on 10.0.1.11 that a strong-fit role out-ranks a reach; fresh-install resilient.

### EPIC OUTCOME-LEARN — Learn from application outcomes to beat a one-shot read · see ADR-0013
**Principle:** The product's edge over a human advisor is learning from OUTCOMES continuously — which applications get replies/screens/interviews/offers vs. ghost — feeding that back into the fit model + scoring + Reflection Coach. **REUSE-FIRST:** extend `LearningService`'s existing `converting_role_signature` (centroid of roles that convert) + `feature_stats`/`taste_bias`, and `PostSubmissionService` + the `applications` state machine; the Reflection Coach (EPIC AGENTS/ADR-0009) consumes the effectiveness signal. Do NOT build a parallel learning store.
- **DoR:** ADR-0011/0012/0013 accepted; the applications state machine + post-submission/inbox-match plumbing can carry an outcome funnel; the learning model + `apply_learned_adjustment` seam are the reuse targets.
- **AC (BDD):**
  - *Given* a submitted application, *When* its outcome advances (responded / screen / interview / offer / rejected / ghosted), *Then* it is captured (user one-tap · inbox/email-match · status scrape where supported); *And* "unknown" is a valid state (never fabricated).
  - *Given* outcomes accrue, *Then* role families/companies/levels that draw responses strengthen the candidate's derived strong-fit signal and those that ghost down-weight (extend `converting_role_signature`); *And* fit-scoring weights tune toward what converts for THIS candidate.
  - *Given* the Reflection Coach's cadence, *Then* it grades effectiveness on the real KPI — *calls/interviews earned, faster* — not volume — and applies transparent, reversible tweaks (`apply_learned_adjustment` / `clear_learned` revert).
  - *Given* any learned adjustment, *Then* it carries a human-readable summary and is reversible; the loop NEVER silently narrows the search away from the user's intent.
- **DoD:** outcome funnel captured (cheapest-first) + fed to fit model + scoring weights + RC; reuses the converting-role signature + post-submission tracking; transparent + reversible; TDD+BDD; verified on 10.0.1.11; fresh-install resilient.

### EPIC COMPANION — The main chat is a companion, not a command line · see ADR-0014
**Principle (Kevin):** "there's been benefit in sharing feedback and catharsis with you, who would eventually become the main Applicant agent I could speak with through the main chat." The main chat is the RELATIONSHIP layer — it KNOWS the user (fit model + memory, not just résumé facts), REMEMBERS across every conversation, is HONEST about fit, can ACT (gated, never auto-submit), and is a place to think + be heard. **REUSE-FIRST:** rebuild over `ChatService.converse` + `ChatToolbox`/`chat_tools.py` (gated actions) + the durable curated memory (ADR-0010) + the fit model (ADR-0011). Do NOT build a new chat engine. **First: fix the audited chat P0s** (dead-on-load, wrong send field, no-op Confirm).
- **DoR:** ADR-0014 accepted; chat P0 fixes landed; `ChatService` can be grounded in the fit model + durable memory + campaign context; the gated tool surface exists.
- **AC (BDD):**
  - *Given* the main chat, *When* I converse, *Then* the agent grounds every turn in my fit model + criteria + durable memory + queue state — it speaks to MY situation, not a generic applicant.
  - *Given* a new conversation later, *Then* it remembers me (preferences, history, prior context) via the durable curated memory — continuity is the feature.
  - *Given* I ask about fit, *Then* it gives the honest reach-vs-strong-fit read (reuse fit-scoring), never flattering a reach into a strong fit.
  - *Given* I ask it to act (tune criteria, re-score, draft, discard, explain), *Then* it does so via the gated tool surface — confirm-gate for integral changes, transparent + reversible, and **NEVER auto-submits an application.**
  - *Given* the conversation moves from job-frustration toward genuine distress, *Then* the agent responds with warmth and without judgment, surfaces real human/crisis support, and never positions itself as a substitute for human connection or clinical help (care boundary).
  - *Given* a high-stakes/nuanced turn, *Then* it may escalate to a stronger model tier (the local/DeepSeek ladder carries these qualities deliberately, not by assumption).
- **DoD:** chat rebuilt on fit-model + memory grounding with gated, transparent, reversible actions; care-boundary guardrails (distress recognition + resource surfacing) first-class; model-escalation path wired; TDD+BDD; verified on 10.0.1.11; fresh-install resilient. **Guardrails: never auto-submit; never substitute for human/professional support.**

---

## 🪜 STORY LADDERS — Fit Engine + Companion (current state → fully implemented) (Kevin, 2026-08-11)
_Each new epic decomposed into sequenced user stories bridging what exists today to the fully-implemented ADR. ✅ = already shipped this session. Every story carries the standing DoR/AC(BDD)/DoD; the one-line AC below is the executable intent, reuse-first._

### FIT-MODEL (ADR-0011) — current: flat attribute cloud only
- **FM-1 CandidateProfile entity + schema.** *AC:* a typed per-campaign entity holds title-history (role/level/tenure/primary-vs-stretch), typed certs, degree-presence, industries (depth/recency), skills (evidence strength), quantified wins, tech-depth. *Reuse:* `core/entities/` style.
- **FM-2 Deterministic derivation.** *AC:* `CandidateProfileService` populates the structural fields from `onboarding.base_resume` (parsed) + `AttributeCloudService`, no LLM.
- **FM-3 LLM-assisted derivation.** *AC:* normalize noisy titles, infer level, write the human-readable fit rationale via the wired LLM tier; stored + re-derivable.
- **FM-4 Derive strong-fit / viable-stretch bands.** *AC:* the model computes the candidate's strong-fit + stretch role families **with a rationale each**, from the model (not hand-authored).
- **FM-5 Persist + refresh + degrade.** *AC:* persisted per campaign; re-derives only on résumé/profile change (cached); a sparse résumé degrades to today's attribute-only behavior.
- **FM-6 Fit model in the Profile UI.** *AC:* Kevin sees his derived competitiveness model + bands in the Profile panel and can correct them (feeds back to derivation).

### FIT-SCORING (ADR-0012) — current: ✅ FS-1 shipped; scoring still uses the hardcoded Agile allowlist
- **FS-1 ✅ Deterministic ranking factors + US-remote gate (`5e981b678`).** recency · SAFe-penalty · pay · seniority · fit-to-profile · degree-requirement multipliers + a hard US-remote gate. *Verified:* Kevin's rejected SAFe/stale/low-pay case 95→45%; a Scrum Master out-ranks an equally-fresh big-tech TPM.
- **FS-2 Derive the allowlist from the fit model.** *AC:* `role_domain_fit.derive_from_profile(candidate_model)` replaces the hardcoded Agile list with a per-candidate one (generalizes; #46). *(Depends on FM-4.)*
- **FS-3 Parse posting competitiveness signals.** *AC:* extract level + industry + degree-requirement from the description and match against the candidate model (title/level/industry fit), extending the FS-1 degree/seniority multipliers.
- **FS-4 Wire scoring to the derived model.** *AC:* scoring uses the derived allowlist + competitiveness when a fit model exists; the hardcoded Agile list remains the fallback default (no regression).
- **FS-5 Fit rationale → EXPLAIN.** *AC:* each score's fit reasoning (strong/stretch, degree gate, US-remote, freshness, pay) surfaces as the EXPLAIN greens/reds breakdown (ties EPIC EXPLAIN).
- **FS-6 Generalization proof.** *AC:* a BDD scenario shows a DIFFERENT candidate/target role re-derives the fit tiers with no code change.

### OUTCOME-LEARN (ADR-0013) — current: taste signals + converting-role-signature exist; no outcome funnel
- **OL-1 Outcome funnel on the application.** *AC:* the application state machine carries applied→viewed→responded→screen→interview→offer→rejected/ghosted (unknown allowed). *Reuse:* `PostSubmissionService` + `applications` states.
- **OL-2 One-tap outcome capture.** *AC:* Kevin marks an outcome from the review/tracker card in one tap.
- **OL-3 Inbox/email-match outcome inference.** *AC:* recruiter replies auto-advance the funnel via the existing inbox-match plumbing; never fabricated.
- **OL-4 Outcomes → fit model.** *AC:* families/companies/levels that draw responses strengthen the candidate's strong-fit signal; ghosts down-weight (extend `converting_role_signature`).
- **OL-5 Outcomes → scoring weights.** *AC:* fit-scoring weights tune toward what actually converts for THIS candidate.
- **OL-6 Reflection Coach on the real KPI.** *AC:* RC grades effectiveness on calls/interviews-earned (not volume) and applies transparent, reversible tweaks (ties EPIC AGENTS / ADR-0009).

### COMPANION (ADR-0014) — current: ✅ CO-1 shipped; chat works but doesn't yet know Kevin
- **CO-1 ✅ Revive the chat (`646fb6233`).** dead-on-load, wrong send-field, no-op Confirm all fixed; false job-title nag dropped.
- **CO-2 Ground every turn in fit model + memory.** *AC:* `ChatService.converse` reads the fit model + durable curated memory + criteria + queue state so it speaks to Kevin's situation, not a generic applicant.
- **CO-3 Honest fit guidance in chat.** *AC:* asked about a role, the agent gives the reach-vs-strong-fit read (reuse fit-scoring), never flattering a reach.
- **CO-4 Gated action surface.** *AC:* tune criteria / re-score / draft / discard / explain via `ChatToolbox`, confirm-gated for integral changes, transparent + reversible, never auto-submit.
- **CO-5 Care-boundary guardrails.** *AC:* on genuine distress, respond with warmth, surface real human/crisis support, never substitute for it or feign clinical competence.
- **CO-6 Model-escalation.** *AC:* high-stakes/nuanced turns escalate to a stronger tier; the local/DeepSeek ladder carries the companion qualities deliberately.
