# Traceability Matrix

Mandated by master spec §13: **Requirement ID → Work Package (phase) → BDD Feature(s) → adapter/contract test.** Any requirement lacking a downstream feature and test is a **GAP** to flag, not drop.

> **Why this matrix was distrusted, and what changed.** Earlier versions verified the
> **engine only** and treated "the engine implements it + tests pass" as done. That
> overstated reality twice over: (1) some MUST behaviors were present-but-not-enforced,
> never driven, or not persisted (fixed in the production-hardening remediation); and
> (2) it implied front-door reachability that did not exist — the engine is internal-only
> and the operator never touches it directly. A requirement is delivered **only when it is
> reachable/operable in the white-labeled workspace front door** (`workspace/`), across
> the chain spec → engine router → workspace proxy → JS → nav/section. This matrix now
> reports **both** dimensions: per-row **engine delivery** (with file:line + test), and a
> **front-door reachability** summary (the [section below](#front-door-reachability)) that
> names the workspace surface exposing each requirement family. Where the distinction
> matters (engine-internal vs. operator-reachable), it is called out.

**Status (2026-06): all phases (0–5) are merged to `main`** — engine phases 0–4, the
production-hardening remediation, and the **front-door (Phase 5)** lift-and-shift onto the
workspace + the reachability re-audit. Every engine row below was re-verified against the
actual `src/` code (file:line), and every requirement family is confirmed reachable in the
front door (see [Front-door reachability](#front-door-reachability)). The engine suite is
green (`uv run pytest -q`: **613 passed, 14 skipped**).

- **WP** = phase from [work-packages.md](work-packages.md) / §9.
- **BDD Feature(s)** are the §10 acceptance anchors plus the features authored per work
  package; live under `tests/bdd/features/`.
- **Status** column reports the *verified* engine delivery: the satisfying code surface
  (adapter / service / router / core rule) at a real path plus the test surface that covers
  it. Core domain rules are tested in the core (no adapter); adapters carry contract tests;
  flows carry BDD scenarios.
- **Reachability** is NOT in the per-row Status column (which is engine-only). It is
  asserted family-by-family in [Front-door reachability](#front-door-reachability): each
  requirement family maps to the workspace `/api/applicant/*` proxy + JS surface that
  exposes it.
- **What the tests prove:** the 613 hermetic engine tests prove the *logic* against fakes /
  in-memory adapters. End-to-end exercise of the integration-gated boundaries (live
  Postgres/DBOS, real browser, TeX/LibreOffice, Discord/SMTP, live job boards) requires a
  live deployment — those are environment dependencies, not requirement gaps (see the
  14 skips and the note at the bottom).
- **GAP** rows: any requirement genuinely not delivered is flagged in **Remaining gaps**
  below. As of this re-audit none of the previously-flagged BLOCKER/DEVIATION/PARTIAL/
  STUB-ONLY items remains open — all re-verified OK, and all are reachable in the front door.

§10 seed feature names (verbatim): Zero-CLI out-of-box setup; Per-campaign attribute cloud; Resume uploads right and looks right; Screening answers go through review; Sensitive fields are never AI-guessed; Pending-actions portal; Maximal pre-fill, stop at irreducible human steps; Interactive resume review with highlighted edits; Adaptation never fabricates; Mid-step crash resumption; Conversion is approval plus submission; Discord-first with 30s hold and web pre-empt; Master aggregator in wave one; Source-yield learning with exploration.

## FR-LLM

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-LLM-1 | 0 | "Zero-CLI out-of-box setup" (LLM step); "Provider-agnostic LLM (cloud or local)" | Delivered — Phase 0; LLM port + OpenRouter/OpenAI-compatible and Ollama adapters; contract test |
| FR-LLM-2 | 0 | "Zero-CLI out-of-box setup"; "Auto-populated model list" | Delivered — Phase 0; LLM adapter model-list + setup router; contract test |
| FR-LLM-3 | 0 | "Configurable tier ladder" | Delivered — Phase 0; ladder config in core; unit test |
| FR-LLM-4 | 0 | "Escalation climbs the ladder on low confidence / context overflow" | Delivered (re-verified) — `complete()` accepts a per-task `start_tier` so a complex task starts above L1 (`adapters/llm/openai_compatible.py`), wired in pre-fill field-mapping escalation (`prefill_service` `FIELD_MAPPING_START_TIER`); tests `tests/unit/test_openai_compatible_llm.py::test_start_tier_respected`, `tests/unit/test_prefill_service.py` |
| FR-LLM-4a | 0 | "Defensive structured-output across model variance" | Delivered — Phase 0; defensive parse + prompt-fallback in LLM adapter; contract test |
| FR-LLM-5 | 0 | "Token frugality with local default" (shared with NFR-TOKEN-1) | Delivered — Phase 0; local-default routing + token-budget assertions; contract test |

## FR-DISC

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DISC-1 | 1 | "Master aggregator in wave one" | Delivered — Phase 1; discovery port + scheduled scan; contract+BDD |
| FR-DISC-2 | 1 | "Master aggregator in wave one" | Delivered — Phase 1; JobSpy aggregator adapter (`python-jobspy`); contract+BDD |
| FR-DISC-3 | 1 | "Posting normalization" | Delivered — Phase 1; normalization in core; unit test |
| FR-DISC-4 | 1 | "Zero-token structured discovery" | Delivered — Phase 1; no-LLM discovery path; contract test (token-budget assertion) |
| FR-DISC-5 | 1 | "Source-yield learning with exploration" | Delivered (re-verified) — source-yield funnel (matches→approvals→submissions) wired live: `digest_service.py:248-258` records the approvals leg, `submission_service.py:162-174` records the submissions leg, folded by `learning_service.record_source_event`; test `tests/unit/test_source_funnel_legs.py` |
| FR-DISC-6 | 1 | "Pluggable proxy hook" (SHOULD) | Delivered — Phase 1; proxy-hook interface on discovery adapter; contract test |

## FR-CRIT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-CRIT-1 | 1 | "Self-learning per-campaign criteria" | Delivered — Phase 1; criteria mutation in core; unit test |
| FR-CRIT-2 | 1 | "Criteria editable and transparent" | Delivered — Phase 1; criteria router (driving port); contract+BDD |
| FR-CRIT-3 | 1 | "Criteria mutable by LLM and user" | Delivered — Phase 1; criteria mutation (LLM + user paths) in core; unit test |
| FR-CRIT-4 | 0 | "Per-campaign attribute cloud" | Delivered — Phase 0; campaign-scoped schema; unit+contract (storage) |

## FR-LEARN

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-LEARN-1 | 1 | "Per-campaign attribute cloud" (scoping); "Per-campaign learning" | Delivered — Phase 1; LearningModel in core (campaign-scoped); unit test |
| FR-LEARN-2 | 1 (depth 4) | "Conversion is approval plus submission" | Delivered — Phase 1, deepened Phase 4 (AdvancedLearningService); OutcomeEvent→learning; unit+BDD |
| FR-LEARN-3 | 1 (depth 4) | "Learn from every input" | Delivered — Phase 1/4; multi-source learning inputs (digest, outcomes, chat, revision feedback); unit+integration |
| FR-LEARN-4 | 1 (depth 4) | "Cross-reference attribute cloud" | Delivered — Phase 1/4; attribute cross-reference + confirmation gate; unit test |
| FR-LEARN-5 | 1 | "Learn converting-role signature" | Delivered (re-verified) — `learning_service.record_converting_role` accumulates the signature; only real conversions (approval+submission) feed it via `learning_advanced.is_conversion`; persisted to `campaigns.learning_state` and survives reload; test `tests/unit/test_learning_advanced.py` |
| FR-LEARN-6 | 1 | "Source-yield learning with exploration" | Delivered (re-verified) — `learning_service.record_source_funnel` weights conversions above raw matches + exploration budget; producers wired (see FR-DISC-5); test `tests/unit/test_learning_service.py`, `tests/unit/test_source_funnel_legs.py` |
| FR-LEARN-7 | 1 | "Cheap statistical learning" (SHOULD) | Delivered — Phase 1; local embedding port + statistical learning; contract test |

## FR-DIG

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DIG-1 | 1 | "Daily digest per campaign" | Delivered (re-verified) — `DigestService.deliver` is now actually driven on a cadence by `scheduler.py:84-96` (once/UTC-day guard) and per-tick by `agent_loop.py:187-192`; the digest-decision pending-action key bug is fixed (`digest_service.py:302-319`, decisions resolve by posting id); test `tests/unit/test_scheduler.py`, `tests/unit/test_agent_loop.py` |
| FR-DIG-2 | 1 | "Discord-first with 30s hold and web pre-empt" (delivery) | Delivered (re-verified) — `DigestService.deliver` now SENDS the rendered email body via `notification_service.send_digest_email` (`digest_service.py:157-166`), not pull-only; Apprise notifier adapter; contract+BDD |
| FR-DIG-3 | 1 | "Digest table with approve/decline" | Delivered — Phase 1; digest router (driving port) approve/decline; contract+BDD |
| FR-DIG-4 | 1 | "Why this role rationale" | Delivered — Phase 1; rationale in core/digest; unit test |
| FR-DIG-5 | 1 | "Decline with feedback" | Delivered — Phase 1; decision-feedback in core; unit+BDD |
| FR-DIG-6 | 1 | "Empty-day note" (SHOULD) | Delivered — Phase 1; empty-day digest path; unit test |

## FR-FB

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-FB-1 | 1 | "Mandatory decline-with-feedback tunes next run" | Delivered (re-verified) — `DigestService.decline` now REJECTS blank/whitespace feedback (`digest_service.py:200-215`) so the learning loop never closes on a silent decline; the delta biases next-run criteria via `apply_learned_adjustment`; unit+BDD |
| FR-FB-2 | 1 | "Feedback via chat and survey" | Delivered — Phase 1/4; feedback router + chat (Phase 4); contract+BDD |
| FR-FB-3 | 0 (rule), 1 (UI) | "Integral change requires confirmation" | Delivered — Phase 0 rule + Phase 1 UI; confirmation-gate in core; unit+BDD |

## FR-ATTR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-ATTR-1 | 1 | "Per-campaign attribute cloud" | Delivered — Phase 1; AttributeStore in core; unit+BDD |
| FR-ATTR-2 | 1 (use 2) | "Attribute binds to form field" | Delivered — Phase 1 (used Phase 2 pre-fill); field-mapping; contract test |
| FR-ATTR-3 | 1 | "Attribute editable by UI and feedback" | Delivered — Phase 1; attributes router (driving port); contract+BDD |
| FR-ATTR-4 | 1 | "AI adds attributes dynamically" | Delivered — Phase 1; AttributeStore dynamic-add in core; unit test |
| FR-ATTR-5 | 2 | "Missing attribute soft-errors and is reused" | Delivered (re-verified) — full loop: `prefill_service` blocks at BLOCKED_MISSING_ATTR + emits a pending action; `attribute_cloud_service.resume_after_missing_attr` upserts the supplied value to the campaign attribute cloud and resumes the stalled app; a later application reuses the stored value without re-asking; test `tests/unit/test_attribute_cloud.py` (end-to-end reuse) |
| FR-ATTR-6 | 0 (rule), 2 (fill) | "Sensitive fields are never AI-guessed" | Delivered — Phase 0 rule + Phase 2 fill; sensitive-field policy in core; unit+BDD |

## FR-ONBOARD

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-ONBOARD-1 | 0 | "Zero-CLI out-of-box setup" (intake step) | Delivered (re-verified) — comprehensive resumable intake persisted per section in `onboarding_service.py`; section-fill detection + completion flag. **Wave 2 — minimal onboarding (FR-ONBOARD/FR-OOBE):** the form now requires ~only "connect a model"; a new core rule `core/rules/apply_readiness.py` defines the REQUIRED-TO-APPLY set (target roles, work mode, locations, salary floor, key skills, résumé) consumed by the apply-readiness gate below; contract+unit (`tests/unit/test_onboarding_service.py`) |
| FR-ONBOARD-2 | 0 | "Zero-CLI out-of-box setup" (gate) | Delivered (re-verified) — **automated-work gate is now ENFORCED**: `setup_service.is_automated_work_allowed` requires LLM + channels + onboarding-complete (`setup_service.py:261-271`); the `require_automated_work` dependency 409s every automated router until then (`deps.py:89-106`); test `tests/bdd/steps/test_p0_steps.py` (`automated_work_blocked`/`allowed` + 409). **Wave 2 — block-until-essentials:** `automated_work_allowed` now also keys on `apply_readiness.is_ready_to_apply()` and stays BLOCKED until the REQUIRED-TO-APPLY essentials exist; `/api/setup/status` emits `apply_ready` / `apply_missing` / `apply_blocked_reason` so the wizard shows an honest "what's still needed to start applying" banner |
| FR-ONBOARD-3 | 0 | "Bootstrap attribute cloud from base resume" | Delivered — Phase 0; resume-parser adapter (`pypdf`/`python-docx`); contract test. **P1-1a parse-verify (PRs #644/#727):** every ingest is re-slotted through the LLM tier ladder by `adapters/resume_parser/llm_verify.py` (decorator over the port, late-bound via `bind_llm`) under the slotting contract — window-scoped grounding, one-tier escalation, entry-scoped/heading-gated restoration, grounding-hole refill; outcome persisted in the intake record's `verify` block, returned by `POST /{cid}/base-resume`, and rendered honestly in the wizard ("Double-checked …" / "Not double-checked (why)"); hermetic tests `tests/unit/test_parse_verify.py` + env-flagged live smoke `tests/integration/test_parse_verify_live.py` |

## FR-OOBE

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-OOBE-1 | 0 | "Zero-CLI out-of-box setup" | Delivered — Phase 0; setup-wizard router (driving port); contract+BDD |
| FR-OOBE-2 | 0/1 | "Zero-CLI out-of-box setup" | Delivered — Phase 0/1; wizard-sequencing in core; unit test |
| FR-OOBE-3 | 1 | "Zero-CLI out-of-box setup" (channels gate) | Delivered (re-verified) — channels are part of the enforced automated-work gate (`setup_service.channels_configured` + `_channels_complete_now`, `setup_service.py:94-114`); contributes to the 409 in `require_automated_work`; unit+BDD |
| FR-OOBE-4 | 4 | "In-UI Update button" (SHOULD) | Delivered — Phase 4; update router (driving port) + `scripts/update.sh`; contract test |

## FR-FONT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-FONT-1 | 0 | "Resume uploads right and looks right" (font detection) | Delivered — Phase 0; FontInstall port + fonts router; contract test |
| FR-FONT-2 | 0/3 | "Resume uploads right and looks right" (install + cache) | Delivered (re-verified) — `FontInstaller._refresh_font_cache` now shells out to a REAL `fc-cache -f <confined dir>` when fontconfig is on PATH (`font_installer.py:192-222`) and degrades to a counted no-op otherwise; copy is into a confined dir (path-escape guarded); contract test (`tests/unit/test_font_flow.py`) |

## FR-PREFILL

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-PREFILL-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; sandbox port + spin-up on approval; contract+BDD |
| FR-PREFILL-2 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; Workday ATS adapter (browser); contract+BDD |
| FR-PREFILL-3 | 2 | "Map attributes to detected fields, escalate ambiguity" | Delivered — Phase 2; field-mapping + LLM-escalation; contract test |
| FR-PREFILL-4 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; pre-fill-stop boundary in core; unit+BDD |
| FR-PREFILL-5 | 2 | "Final submit: self or engine" | Delivered — Phase 2; final-approval gate (orchestrator recv) + remote router; flow test |
| FR-PREFILL-6 | 2 | "Cautious mode pauses on detection" | Delivered — Phase 2; detection adapter + checkpoint/pause; contract test |
| FR-PREFILL-7 | 2 | "Emergency data-handoff only after fill failure" | Delivered — Phase 2; EMERGENCY_DATA_HANDOFF flow; flow test |

## FR-RESUME / FR-ANSWER

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-RESUME-1 | 3 | "Engine decides material is needed" | Delivered — Phase 3; MaterialService prep decision in core; unit test |
| FR-RESUME-2 | 0/3 | "Adaptation never fabricates" | Delivered — Phase 0 rule / Phase 3 impl; truthfulness guardrail in core; unit+BDD. **P1-13 truth policy (PR #643, owner directive):** the guard is a server-side fact-gate, not a hard wall — `TruthPolicy` (`core/rules/truthfulness.py`, `TRUTH_POLICY`) defaults to `balanced` (flagged facts are surfaced for review, generation proceeds); `strict` preserves the hard fail and the injection/persists-nothing/bypass tests run under it; policy is chosen in `MaterialService`, never caller-supplied |
| FR-RESUME-3 | 3 | "Resume uploads right and looks right" | Delivered (re-verified) — REAL docx→moderncv conversion: `moderncv_converter.py` parses the base resume and renders the vendored `templates/latex/moderncv/main.tex.j2` via Jinja2 (LaTeX-escaped, em-dash-stripped, never fabricated) — structured, not a passthrough; contract+BDD (`tests/contract/test_resume_tailoring_contract.py`) |
| FR-RESUME-3a | 0/3 | "Onboarding conversion accept/reject gate" | Delivered (re-verified) — conversion router + ConversionService over the real converter; auto-enabled when a compile engine is present; contract test (`tests/unit/test_conversion_gate.py`) |
| FR-RESUME-4 | 3 | "Resume uploads right and looks right" | Delivered (re-verified) — fidelity-check (compile + inspect) with auto compile/convert when a TeX engine is present; the real-TeX compile itself is integration-gated (`tests/integration/test_latex_conversion_real.py`, skips without lualatex/xelatex) |
| FR-RESUME-5 | 0/3 | "No em-dashes, voice-matched output" | Delivered — Phase 0 rule / Phase 3 impl; em-dash post-filter in core; unit test |
| FR-RESUME-6 | 3 | "Variant library and lineage" | Delivered — Phase 3; ResumeVariant lineage in core; unit test |
| FR-RESUME-7 | 3 | "Score then reuse or generate variant" | Delivered — Phase 3; ResumeFitScoring + select_or_generate; unit test |
| FR-RESUME-8 | 3 | "Interactive resume review with highlighted edits" | Delivered (re-verified) — **review-before-submit is now ENFORCED at the service layer**, the single chokepoint every submit funnels through: `SubmissionService.record_submission` calls `ensure_submittable` first (`submission_service.py:65-99`), which raises `ReviewRequired` on any unapproved generated material (`core/rules/review_gate.py:47-54`); routers translate it to **409** (`documents.py:220-227`, `remote.py:89-119`); durable RevisionSession repo; tests `tests/bdd/steps/test_p3_steps.py` (raises ReviewRequired), `tests/integration/test_documents_router.py` |
| FR-RESUME-9 | 3/4 | "Aggressiveness control (grayed stub)" | Delivered — Phase 3 stub / Phase 4 backlog; dormant-surface stub; test — see [dormant-surfaces.md](dormant-surfaces.md) |
| FR-RESUME-10 | 3 | "Cover letters on demand" | Delivered — Phase 3; cover-letter generation in MaterialService; unit test |
| FR-ANSWER-1 | 3 | "Screening answers go through review" | Delivered — Phase 3; screening-answer generation + review-gate; contract+BDD |

## FR-SANDBOX

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-SANDBOX-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; sandbox adapter (ephemeral per application); contract+BDD |
| FR-SANDBOX-2 | 2 | "One-click live remote session" | Delivered — Phase 2; RemoteView sub-port (Neko/noVNC) + remote router; contract test (live-Neko integration-gated) |
| FR-SANDBOX-3 | 2 | "Submit-self or authorize engine from live session" | Delivered — Phase 2; RemoteSessionControl (remote router); contract test |
| FR-SANDBOX-4 | 2 | "Multi-session, ephemeral per application" | Delivered — Phase 2; sandbox concurrency/ephemerality; contract test |

## FR-STEALTH

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-STEALTH-1 | 2 | "Coherent browser identity" | Delivered (hardened) — a single **coherent real Linux + Google Chrome** identity (NOT a spoofed Windows persona): real Chrome channel, headful, `--disable-blink-features=AutomationControlled`; UA `X11; Linux x86_64 ... Chrome/<major>` with `<major>` derived from the installed Chrome (`detect_chrome_major`), `Sec-CH-UA-Platform: Linux`, `navigator.platform=Linux x86_64`/`vendor=Google Inc.`/languages `en-US,en`, a stable real-Linux/Mesa WebGL renderer (no randomization, no canvas noise). EVERY field is APPLIED to the launched context (`launch_kwargs` + minimal `add_init_script`; CH-UA left to Chrome). `fingerprint_is_coherent` validates the Linux branch + rejects Windows-on-Linux spoofs and UA↔CH-UA major mismatch. tz/locale pinned to egress (`EGRESS_TIMEZONE`/`EGRESS_LOCALE`). Google Chrome installed in all three takeover desktops (`docker/webtop-chrome`, `docker/webtop-gnome`) + realistic fonts. Unit + integration-gated coherence tests. |
| FR-STEALTH-2 | 2 | "Human-like interaction" | Delivered — Phase 2; interaction-cadence in browser adapter; contract test |
| FR-STEALTH-3 | 2 | "Persistent per-tenant profile" | Delivered — Phase 2; profile-persistence in browser adapter; contract test |
| FR-STEALTH-4 | 2 | "Residential egress" | Delivered (re-verified) — `EgressPolicy` REFUSES a self-flagged datacenter exit and refuses residential-proxy mode without a proxy (`stealth.py:271-288`); the validated proxy is THREADED INTO the real browser launch (`patchright_browser.py:88-89, 200` → `launch_proxy()`), not just a hook; contract test. (Honest caveat: IP/ASN residential classification cannot be fully proven — operator attestation is the guardrail.) |
| FR-STEALTH-5 | 2 | "Honest anti-detection caveat in UX" | Delivered (re-verified) — `STEALTH_CAVEAT` + `EGRESS_CAVEAT` copy surfaced (`stealth.py:47-56, 244-249`); presence test |

## FR-DUR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DUR-1 | 0 | "Mid-step crash resumption" | Delivered (re-verified) — orchestration port with file-backed shim default AND a real DBOS adapter that decorates `@DBOS.workflow`/`run_step`/`send`/`recv` (`dbos_orchestrator.py`); the durable pipeline is registered + driven by `agent_loop` (`agent_loop.py:106-110, 210-232`); contract+BDD; DBOS variant gated (`tests/integration/test_dbos_orchestrator.py`) |
| FR-DUR-2 | 0/2 | "24/7 continuous queue processing" | Delivered (re-verified) — durable queue + capacity admission (`CapacityService`) driven by the loop + scheduler cadence (`scheduler.py`); DBOS `Queue` concurrency in the real adapter; contract test (DBOS variant integration-gated) |
| FR-DUR-3 | 0 | "Mid-step crash resumption" | Delivered (re-verified) — workflow/step resume + the AWAITING_FINAL_APPROVAL durable `recv` gate (`final_approval_service.py:58-77`); DBOS `recover_pending_workflows`; contract+BDD (DBOS variant integration-gated) |
| FR-DUR-4 | 0/2 | "Pivot around blocker" | Delivered — Phase 0 rule / Phase 2 live; pivot in core; unit test |

## FR-LOG

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-LOG-1 | 2 | "Conversion is approval plus submission" (log detail) | Delivered — Phase 2; application-log in core/storage; unit test |
| FR-LOG-2 | 2 | "Per-page screenshots archived" | Delivered (re-verified) — screenshots are PERSISTED via a real SQLAlchemy-backed repo (`adapters/storage/repositories.py:488` `ApplicationScreenshotRepo`, migration `0002_screenshot_page_url`); `SubmissionService._archive_screenshots` writes rows (`submission_service.py:201-213`); contract test |
| FR-LOG-3 | 2/4 | "Logged data retrievable via UI" | Delivered — Phase 2 capture / Phase 4 history UI; AdminQueryService + admin router; contract test |
| FR-LOG-4 | 2 | "Conversion is approval plus submission" | Delivered — Phase 2; submission-detection + mark-submitted; flow+BDD |

## FR-AGENT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-AGENT-1 | 1 | "Tunable throughput" | Delivered (re-verified) — **the run loop now ENFORCES the per-day cap at runtime**: `AgentLoop` keys a per-`(campaign, UTC date)` ledger and refuses the 31st application (`daily_budget`→`clamp_throughput`, hard cap 30; `agent_loop.py:112-167, 195-208`); test `tests/unit/test_agent_loop.py::test_throughput_hard_cap_refuses_31st_per_day` |
| FR-AGENT-2 | 1 | "Selectable run modes" | Delivered (re-verified) — `AgentLoop.tick` consults `AgentRunService.should_continue` (run-mode + UNTIL_N_VIABLE) before doing work (`agent_loop.py:137-144`); agent_runs router; tests `tests/unit/test_agent_loop.py` (`run_mode_stop`), `tests/unit/test_agent_run_service.py` |
| FR-AGENT-3 | 1 | "Viability scoring from JD" | Delivered (re-verified) — `ScoringService` scores every fresh posting inside the tick (`agent_loop.py:180-186, 332-343`); ViabilityScoring entity; unit test |
| FR-AGENT-4 | 0/1 | "Pause and notify on any question" | Delivered (re-verified) — pre-fill lands BLOCKED_QUESTION + emits a pending action/notification; the loop does NOT auto-proceed past the human-in-the-loop point (`agent_loop.py:22-28, 241-253`); flow+BDD |
| FR-AGENT-5 | 0 | "Never continue on uncertain response" | Delivered — uncertainty-halt rule in core; unit test |
| FR-AGENT-6 | 0/2 | "Pivot around blockers" | Delivered (re-verified) — a BLOCKED_* application yields its sandbox slot via `CapacityService` so other work proceeds and never stalls (`agent_loop.py:210-253`); test `tests/unit/test_agent_loop.py::test_pivot_yields_slot_when_blocked` |
| FR-AGENT-7 | 1 | "One-sentence next-action log per run" | Delivered (re-verified) — each tick records a single-sentence intent via `AgentRunService.start_run` (`agent_loop.py:411-445`); agent_runs router; **now also surfaced two ways**: a read-only "what the agent is doing" snapshot (`app/routers/agent_status.py`, `/api/agent/status/{cid}` — now/next/recent, first-person, never fabricated) reachable via `/api/applicant/activity/snapshot` → `applicantActivity.js`; and a proactive daily status update (`status_update.py` `StatusUpdateService`) pushed through the existing notification ladder; unit test |

## FR-NOTIF

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-NOTIF-1 | 1 | "Discord-first with 30s hold and web pre-empt" | Delivered — Phase 1; notification adapter (Apprise/Discord); contract+BDD (live-Discord integration-gated) |
| FR-NOTIF-2 | 1/2 | "Discord-first with 30s hold and web pre-empt" | Delivered (re-verified) — the escalation ladder is now actually DRIVEN: `Scheduler.tick` calls `notification_service.advance(now)` each cadence (`scheduler.py:99-110`); `FinalApprovalService.escalate` steps the ladder for the final-approval gate; unit+BDD (`tests/unit/test_notification_ladder.py`) |
| FR-NOTIF-3 | 1 | "Discord-first with 30s hold and web pre-empt" (idempotency scenario) | Delivered (re-verified) — acting on one channel expires the others (`notification_service.acted`, called from digest `_close_loop` and `FinalApprovalService.submit_decision`); unit+BDD |
| FR-NOTIF-4 | 3 | "Interactive resume review with highlighted edits" (review link) | Delivered — Phase 3; review-notification link; unit test |
| FR-NOTIF-5 | 1 | "Immediate errors, optional quiet hours" | Delivered — Phase 1; quiet-hours in core; unit test |

## FR-UI

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-UI-1 | 0/5 | "White-labeled Applicant clone" | Delivered — the operator UI is the white-labeled **workspace front door** (`workspace/`), not an engine-served page; surfaces reuse the workspace's no-build design system and proxy the engine via `/api/applicant/*`. (Phase 0 stood up an engine `frontend/static/` shell; Phase 5 moved the real front door to the workspace — see [frontend.md](frontend.md).) Front-door reachability tested in the workspace; engine routers presence-tested |
| FR-UI-2 | 0/4/5 | "No dead UI; progressive activation" | Delivered — engine dormant registry (`src/applicant/dormant.py`) **plus** the front-door feature layer (`workspace/src/applicant_features.py`) that greys/locks/activates each section from engine setup status; backlog/consistency test — see [dormant-surfaces.md](dormant-surfaces.md) |
| FR-UI-3 | 1 | "Pending-actions portal" | Delivered (re-verified) — real PRODUCERS now create pending actions (digest-approval in `digest_service.deliver`, missing-attr / agent-question / error / final-approval in `prefill_service`); `pending_actions` router lists + resolves them; the digest-decision resolve key bug is fixed; contract+BDD |
| FR-UI-4 | 4 | "Per-tool toggle registry" | Delivered — Phase 4; ToolRegistry adapter + settings sink; contract test |
| FR-UI-5 | 0 | "Zero-CLI out-of-box setup" (LLM-gate first) | Delivered — Phase 0; wizard LLM-gate; unit+BDD |
| FR-UI-6 | 1-4 | "UI exposes all core surfaces" | Delivered (re-verified, composite) — per-surface routers backed by real services: criteria editor (`criteria.py` ← `CriteriaService` get/edit/learned), attribute-cloud editor (`attributes.py` ← `AttributeCloudService` list/upsert/ai-add/bind/acquire-missing), history/admin, documents redline, debug, chat, onboarding, update; each sub-surface covered by its own row + test (`tests/unit/test_criteria_service.py`, `tests/unit/test_attribute_cloud.py`, `tests/integration/test_phase4_surfaces.py`) |

## FR-CHAT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-CHAT-1 | 4 | "Chatbot assists input and updates attributes/criteria" | Delivered — Phase 4; ChatService (container-wired) + chat router; confirmation-gated (FR-FB-3); contract (`p4_chatbot.feature`)+unit+integration. (Previously flagged as a soft phase-placement gap; resolved by landing in Phase 4.) |

## FR-VAULT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-VAULT-1 | 2 | "Encrypted credential store" | Delivered (re-verified) — `PgCredentialStore` seals records with libsodium and PERSISTS them to the `credentials` table (migration `0003_credentials`); a FRESH store instance (a "restart") hydrates from the DB and unseals with the same key-file — credentials genuinely survive restart; test `tests/unit/test_credential_persistence.py::test_sealed_credential_survives_restart` |
| FR-VAULT-2 | 2 | "Both credential-banking modes" | Delivered — Phase 2; manual-entry (credentials router) + auto-capture; contract test |
| FR-VAULT-3 | 2 | "Key-file master key, secrets never logged" | Delivered — Phase 2; key-file master key + redaction; contract+redaction test |

## FR-OBS

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-OBS-1 | 0 | "Structured logging with correlation IDs" | Delivered (re-verified) — structlog + correlation IDs + **value-based** secret redaction: secrets in non-secret-named keys or embedded in free-text messages are masked too, not just key-name redaction (`observability/logging.py:69-100`); redaction test |
| FR-OBS-2 | 4 | "Debug surface" | Delivered — Phase 4; AdminQueryService + admin router (logs/screenshots/history/workflow state); contract test. **Plus** the operator-facing live activity view: `agent_status.py` snapshot (now/next/recent) → `/api/applicant/activity/snapshot` → `applicantActivity.js` panel, and the chatbot reporting past/present/future from the same real state (`chat_service.py`, FR-MIND-4) — the agent is observable in plain language, not just the debug surface |

## FR-INSTALL

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-INSTALL-1 | 4 | "One-liner install to Proxmox VM" | Delivered — Phase 4; `scripts/install.sh` (idempotent, dry-run/`--apply`); install-script test |
| FR-INSTALL-2 | 4 | "Update script with backup/migrate/rollback" | Delivered — Phase 4; `scripts/update.sh` (backup/migrate/restart/rollback); update-script test |
| FR-INSTALL-3 | 4 | "Docker Compose ships whole stack" | Delivered — Phase 4; Compose stack; compose-stack smoke test |

## FR-CUA (computer use / desktop assist)

Extends the master spec via [computer-use.md](spec/computer-use.md). Lift-and-shift of the
Hermes Agent (`kevinhirsch/hermes-agent`, MIT) computer-use feature onto a swappable
`ComputerUsePort`; ships **dormant** (FR-CUA-9) until the desktop driver is baked into the
sandbox image. Engine chain: core guards → `ComputerUsePort` (`adapters/sandbox/computer_use/`)
→ `app/routers/remote.py` desktop-assist endpoints → workspace `applicant_remote_routes.py`
(`/api/applicant/.../desktop/*`) → `applicantRemote.js`.

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-CUA-1/2 | 6 | "Desktop assist confined to the sandbox; swappable sub-port" | Delivered — `ComputerUsePort` + `noop` (default) / `cua_driver` adapters under `adapters/sandbox/computer_use/`; selected by `COMPUTER_USE_BACKEND`; used by pre-fill for native OS upload dialogs the browser cannot reach (desktop self-use, #141); unit/contract test against the noop adapter |
| FR-CUA-3 | 6 | "Desktop assist inherits the stop-boundary" | Delivered — the core stop-boundary guard denies account-create / CAPTCHA / final-submit for the desktop tool the same way as the browser path; guard derives its own ground truth (no caller flag opts past it); core unit test |
| FR-CUA-4 | 6 | "Approval gate on destructive desktop actions" | Delivered — destructive actions route through review-before-act (`COMPUTER_USE_APPROVALS=manual`/`session`); unit test |
| FR-CUA-5 | 6 | "Hard-blocked key combos / type patterns (server-side)" | Delivered — core denylist (dangerous combos + `curl…|bash` / `rm -rf` patterns) denied regardless of approval; core unit test |
| FR-CUA-6 | 6 | "No secret typing; vault is the credential source" | Delivered — desktop `type` refuses secrets; credentials come from the vault fill path; unit test |
| FR-CUA-7 | 6 | "No-foreground / co-working invariant" | Delivered — background pid-scoped input contract on the port (no cursor-steal/refocus); contract test |
| FR-CUA-8 | 6 | "Every desktop action logged + screenshotted; eviction" | Delivered — actions logged to the per-application record with capture; screenshot eviction + image token accounting; unit test |
| FR-CUA-9/12 | 6 | "Present-but-disabled until reachable; health preflight" | Delivered — registered dormant in `src/applicant/dormant.py` (`desktop_assist`); `health()` preflight degrades to noop when the driver is absent; `tests/unit/test_cov_remote.py` / `test_cov_dormant.py` |
| FR-CUA-10 | 6 | "White-label & honest copy" | Delivered — all front-door copy is plain-language Applicant; no driver/upstream codenames (CI denylist gates it) |
| FR-CUA-11 | 6 | "Degraded text-only (ax) mode" (SHOULD) | Delivered — `COMPUTER_USE_MODE=ax` accessibility-tree path; falls back to human handoff on empty AX trees; unit test |

## FR-MIND (assistant learning / memory / playbooks)

Extends the master spec via [agent-intelligence.md](spec/agent-intelligence.md). Lift-and-shift
of the Hermes Agent (`kevinhirsch/hermes-agent`, MIT) learning/looping substrate — curated
memory, procedural skills, cross-session recall — re-homed onto engine ports + the workspace
`workspace/services/memory/` store. Engine chain: `MemoryStore`/`SkillStore`/`RecallIndex` ports
(in-memory default + `bridge` over the callback channel) → `app/routers/agent_memory.py`
(`/api/agent-memory*`) → workspace `applicant_mind_routes.py` (`/api/applicant/mind/*`) →
`applicantMind.js` (memory panel) + `applicantPortal.js` (curation approvals).

**The learning loop now actually learns, uses, and reports itself.** The scheduled curation
nudge reviews REAL inputs — run history (`application/services/run_history.py`
`RunHistoryProvider`, real `Application` outcomes) AND the user's own feedback
(`application/services/feedback_history.py` `FeedbackSummaryProvider`, from digest declines +
résumé/answer revision instructions) — summarizes each run with a CHEAP optional LLM
(`build_llm_summarizer`, `CURATION_MODEL`; degrades to a trivial summarizer for the hermetic
lane) and **populates recall** through the `RecallIndex.index()` write path so the loop's recall
tool returns real hits. The learned memory/skills then feed BACK into generation + scoring:
`material_service` (résumé/cover/answers) and `scoring_service` (viability) each append a
BOUNDED, advisory-only "what the assistant has learned" block read fresh per call (FR-MIND-10),
which nudges output without conferring authority (FR-MIND-11) and never relaxes the
no-fabrication guard (FR-RESUME-2). The chatbot IS this agent (FR-MIND-4 single first-person
identity), narrating past/present/future from real read-only state (run status, scheduler
estimate, application history — FR-AGENT-7 / FR-OBS-2; `chat_service.py`). End-to-end coverage:
`tests/unit/test_loop_end_to_end.py` runs discovery→scoring→digest→approval→prefill→stop-boundary
green WITH the learning hooks firing.

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-MIND-1 | 6 | "Curated memory (environment + user, bounded)" | Delivered — `MemoryStore` (add/replace/remove, size caps `MEMORY_MAX_CHARS`/`USER_MAX_CHARS`); frozen snapshot read per tick; the advisory "what I've learned" block is consumed by `material_service` + `scoring_service`. **Wave 2 — onboarding seed (FR-MIND-1/3):** completing onboarding seeds a bounded curated-memory baseline and indexes cross-session recall from the user's own profile/résumé (`onboarding_seed.py`); idempotent and a no-op when the substrate is absent; unit test + `tests/unit/test_loop_end_to_end.py` |
| FR-MIND-2/3 | 6 | "Procedural skills + cross-session recall" | Delivered — `SkillStore` (create/patch/edit, progressive disclosure L0/L1) + `RecallIndex` (FTS + chromadb-analogue); curation now WRITES to recall (`RecallIndex.index()`) so the recall tool returns real hits; in-memory + `bridge` adapters; unit test |
| FR-MIND-4/5 | 6 | "Identity tier + tiered prompt assembly" | Delivered — single first-person identity (the chatbot IS the autonomous agent); identity slot sourced from the voice spec (white-labeled); ordered prompt tiers in the prompt builder; `chat_service.py` narrates real state. **Wave 2 — learned-context provenance (FR-MIND-5):** material generation now records which learned memory / playbooks / recall it drew on (`GeneratedDocument.provenance`, migration `0006`); the document-review surface shows a "What I drew on" panel; unit test |
| FR-MIND-6 | 6 | "Tool registry & dispatch" | Delivered — memory/skill/recall are registered tools dispatched through the central registry. **Wave 2 — agent-callable tools (FR-MIND-6):** a capability-gated tool-calling seam on the LLM port/adapter lets the chat assistant call `remember`/`forget`/`save_playbook`/`update_playbook`/`recall`/`desktop` mid-conversation (`chat_tools.py` `ChatToolbox`, opt-in via `CHAT_TOOLS`, default `off`). Writes route through review-before-write (FR-MIND-9); a tool asserting `claims_authority` is refused (FR-MIND-11); `desktop` goes through the FR-CUA guards; each tool is gated by the FR-UI-4 tool registry; unit test |
| FR-MIND-7 | 6 | "Closed learning loop on a schedule" | Delivered — `CurationService` review nudge (`CURATION_SCHEDULE`, optional cheaper `CURATION_MODEL`) reviews REAL run history (`run_history.py` `RunHistoryProvider`) + user feedback (`feedback_history.py` `FeedbackSummaryProvider`, from digest declines + revision instructions), summarizes via `build_llm_summarizer`, and proposes memory/skill updates + recall writes — all staged for review; unit test + `tests/unit/test_loop_end_to_end.py` |
| FR-MIND-8 | 6 | "LLM context management (compression + prefix cache)" | Delivered — `adapters/llm/context_window.py` `ContextWindowManager` compresses middle turns past `CONTEXT_COMPRESS_THRESHOLD` and applies a provider-gated prefix cache (`PREFIX_CACHE` = auto/on/off); applied at the LLM adapter; unit test |
| FR-MIND-9 | 6 | "Review-before-write; self-writes are gated" | Delivered — self-writes (incl. the new history/feedback-driven proposals + recall writes, **and Wave 2 chat-tool `remember`/`forget`/`save_playbook`/`update_playbook` calls**) stage to the process-lived `CurationLedger` (`MEMORY_WRITE_APPROVAL`/`SKILLS_WRITE_APPROVAL` default on) → pending-actions approve/deny; only approval writes a proposal; unit test |
| FR-MIND-10 | 6 | "Per-tick safety: state in process/Postgres, never the loop" | Delivered — curation state lives in the injected process-lived ledger / durable store and survives an `AgentLoop` rebuild; the advisory learned block is read FRESH per call (never cached on the loop); unit test asserts cross-tick survival |
| FR-MIND-11 | 6 | "Memory/skills are advisory, never authorization" | Delivered — a skill claiming submit authority is denied by the core guard (ground truth not caller-supplied); the generation/scoring learned block is advisory-only and never relaxes the no-fabrication guard (FR-RESUME-2); ingested content is treated as untrusted; core unit test |
| FR-MIND-12 | 6 | "Reachability & white-label" | Delivered — viewable/editable in the memory/profile panel; curation queue in the portal; `assistant_memory`/`saved_playbooks`/`curation_approvals` live in `src/applicant/dormant.py`; plain-language copy (no upstream strings; CI denylist gates it); `tests/unit/test_cov_dormant.py` |
| FR-MIND-13 | 6 | "Keep it cheap & local" (SHOULD) | Delivered — recall/embeddings local (chromadb), curation prefers the cheaper model, progressive disclosure + bounds cap token cost; unit test |

## NFR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| NFR-LOCAL-1 | 0 | "Fully-local operation" | Delivered — Phase 0; local-only path (Ollama LLM + local embeddings + shim orchestrator); integration test |
| NFR-TOKEN-1 | 0-3 | "Three-layer token frugality" | Delivered across Phases 0–3; zero-token discovery/scoring, deterministic pre-fill, LLM only for generation/ambiguity; token-budget assertions across adapters |
| NFR-247-1 | 0 | "Mid-step crash resumption" | Delivered — Phase 0; durable orchestration; durability/resumption test |
| NFR-CAUTION-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; cautious-mode in core; unit+BDD |
| NFR-EXT-1 | 0/4 | "Master aggregator in wave one" (adapter extensibility) | Delivered — Phase 0 rule / Phase 4 verify; adapter-extensibility (sources, ATS, tools, models, channels); contract tests |
| NFR-ARCH-1 | 0 / Wave 1 | CI `lint-imports` step + `tests/architecture/test_layering` (marker) | Delivered — Phase 0 (hexagonal + BDD + TDD) + Wave 1 (CI-enforced import-linter contract: `app > application > adapters > ports > core`, core-purity `forbidden` contract; `pyproject.toml` `[tool.importlinter]`; 2 contracts, 234 files, 0 violations) |
| NFR-ZEROCLI-1 | 0/4 | "Zero-CLI out-of-box setup" | Delivered — Phase 0 rule / Phase 4 update; zero-CLI setup + in-UI update; assertion test |
| NFR-PRIV-1 | 2 | "Encrypted PII at rest, minimal cloud PII" (SHOULD) | Delivered — Phase 2; encryption-at-rest (`pynacl`) + minimal-cloud-PII policy; encryption test |
| NFR-TRUTH-1 | 0/3 | "Adaptation never fabricates" | Delivered — Phase 0 rule / Phase 3 impl; truthfulness guardrail in core; unit+BDD |

## Front-door reachability

The per-row Status above proves **engine** delivery. This section proves the second,
previously-missing dimension: that each requirement family is **reachable/operable in the
white-labeled workspace front door**, not just implemented behind the internal `api`. Each
family maps to its workspace `/api/applicant/*` proxy route + JS surface (the engine
router it forwards to is named in [frontend.md](frontend.md)).

| Requirement family | Reachable via (front-door surface) | Proxy route + JS |
|---|---|---|
| FR-LLM (provider, model list, tier ladder, escalation) | OOBE wizard — LLM step (reuses the workspace Local/Remote model-endpoint manager) | `applicant_setup_routes.py` + `applicantOnboarding.js` (+ workspace `/api/model-endpoints`) |
| FR-OOBE, FR-ONBOARD, FR-FONT, FR-RESUME-3a | OOBE setup / onboarding wizard (auto-launch, gated, resumable; **Wave 2** minimal "connect a model" form + the honest "what's still needed to start applying" apply-readiness banner from `/api/setup/status` `apply_ready`/`apply_missing`/`apply_blocked_reason`) | `applicant_setup_routes.py` + `applicantOnboarding.js` |
| FR-DISC, FR-AGENT-1/2/7 (run controls, source toggles, intent) | Activity/debug — ops tab | `applicant_ops_routes.py` + `applicantDebug.js` |
| FR-CRIT (criteria editor) | Profile — criteria editor | `applicant_memory_routes.py` + profile section |
| FR-ATTR (attribute cloud, sensitive policy, missing-attr) | Profile — attribute-cloud editor + portal soft-error resolve | `applicant_memory_routes.py` / `applicant_portal_routes.py` |
| FR-LEARN (attributes + conversion learning) | Profile — learning | `applicant_memory_routes.py` + profile section |
| FR-DIG, FR-FB (digest approve/decline, feedback survey) | Email / digest panel + feedback survey | `applicant_email_routes.py` + `emailLibrary/applicantDigest.js` |
| FR-UI-3 (pending-actions portal) | Pending-actions portal (home base) | `applicant_portal_routes.py` + `applicantPortal.js` |
| FR-RESUME-8 / FR-ANSWER-1 (redline review; **Wave 2** "What I drew on" learned-context provenance panel) | Documents / résumé redline review | `applicant_documents_routes.py` + documents section |
| FR-PREFILL-5, FR-SANDBOX-2/3 (live session, submit/authorize) | Live remote view / takeover | `applicant_remote_routes.py` + `applicantRemote.js` |
| FR-VAULT (credential vault, both banking modes) | Credential vault | `applicant_vault_routes.py` + `applicantVault.js` |
| FR-CHAT (chatbot + job actions) | Chat / assistant | `applicant_chat_routes.py` + `applicantChat.js` |
| FR-LOG-3/4, FR-OBS-2, FR-UI-4 (history, screenshots, logs, workflow state, mark-submitted, tool toggles) | Activity / debug | `applicant_admin_routes.py` + `applicantDebug.js` |
| FR-AGENT-7 / FR-OBS-2 (what the agent is doing: now / next / recent) | Agent-activity panel + status strip | `applicant_activity_routes.py` (`/api/applicant/activity/{snapshot,status,intent,runs}` ← engine `agent_status.py`) + `applicantActivity.js` |
| FR-OOBE-4 / FR-INSTALL-2 (in-UI Update button) | Activity/debug — Update button | `applicant_ops_routes.py` (Update trigger) + `applicantDebug.js` |
| FR-MIND (what the assistant remembers, saved playbooks, curation approvals; learned-from-runs/feedback curation proposals) | Profile — memory panel + pending-actions portal | `applicant_mind_routes.py` (`/api/applicant/mind/{memory,skills,curation}`) + `applicantMind.js` / `applicantPortal.js` |
| FR-CUA (desktop assist on the live session) — **ships dormant/grayed** | Live remote view / takeover (opt-in toggle, present-but-grayed) | `applicant_remote_routes.py` (`.../desktop/{health,enable,disable,action}`) + `applicantRemote.js` |

**Engine-internal, not a separate front-door surface (called out per the spec):**

- **FR-DUR / FR-NOTIF ladder cadence / FR-STEALTH / NFR-ARCH / NFR-247 / NFR-TOKEN /
  NFR-LOCAL** are engine-internal mechanisms (durable orchestration, the
  Discord→web→email escalation, browser fingerprint/egress, the hexagon, token frugality,
  local-first). They are *observable* in the front door (notifications arrive; the
  Activity surface shows workflow state and the egress/stealth caveat), but they are not
  themselves operator screens. This is the legitimate engine-vs-front-door distinction —
  not a reachability gap.
- **FR-UI-1 white-label:** the front door is the **owner's vendored workspace app**,
  white-labeled as Applicant — it is *not* an engine-served clone. The spec's "vendor the
  Applicant UI `static/`" wording is reconciled in
  [master-spec.md](spec/master-spec.md#reconciliation-note-front-door--ui-vendoring) and
  [open-items.md](open-items.md).

## Coverage check

- **Exhaustive:** every FR-*/NFR-* ID in [requirements.md](requirements.md) has a row
  above (110 functional + 9 non-functional family count).
- **Re-verified delivered (engine):** every row reports a delivered code surface (read at
  file:line) plus a covering test. The engine suite is green (**613 passed; 14 skips** are
  integration-gated boundaries — see below).
- **Re-verified reachable (front door):** every operator-facing requirement family maps to
  a workspace `/api/applicant/*` proxy + JS surface in [Front-door
  reachability](#front-door-reachability); the only `present_but_disabled` surface is
  Compare, which is by product decision, not a gap.

## Re-audit verification result

Every requirement previously flagged BLOCKER / DEVIATION / PARTIAL / STUB-ONLY was re-opened
against the actual `src/` code and its test, and classified:

- **OK (verified): all of them.** No item remains STILL-PARTIAL; nothing REGRESSED.
- The four original **blockers** are confirmed truly enforced/persisted (not just present):
  1. **Review-before-submit (FR-RESUME-8)** — `SubmissionService.record_submission` →
     `ensure_submittable` raises `ReviewRequired`; routers return **409**
     (`submission_service.py:65-99`, `core/rules/review_gate.py:47-54`, `documents.py:220-227`).
  2. **Automated-work gate (FR-ONBOARD-2 / FR-OOBE-3)** — `require_automated_work` 409s until
     LLM + channels + onboarding-complete (`deps.py:89-106`, `setup_service.py:261-271`).
  3. **Run loop + 30/day cap (FR-AGENT-1/7)** — `AgentLoop.tick` drives the durable pipeline
     and refuses the 31st application/day (`agent_loop.py:112-167, 195-208`).
  4. **Credentials survive restart (FR-VAULT-1)** — a fresh `PgCredentialStore` hydrates +
     unseals persisted rows (`pg_credential_store.py:305-319`,
     `tests/unit/test_credential_persistence.py`).

## Remaining gaps

**None at the requirement level, in either dimension.** No FR-*/NFR-* is undelivered in the
engine, and every operator-facing requirement family is reachable in the workspace front
door ([Front-door reachability](#front-door-reachability)). The previously-flagged engine
items are all resolved (see the per-row "(re-verified)" annotations and the four blockers
above). The earlier soft phase-placement gaps are also resolved: **FR-CHAT-1** is a
first-class chat surface (`ChatService` + chat router, confirmation-gated per FR-FB-3,
`tests/bdd/features/p4_chatbot.feature`), reachable via the front-door assistant
(`applicant_chat_routes.py` + `applicantChat.js`); and **FR-UI-6** is a span whose
sub-surfaces each carry their own row + test and each map to a front-door surface.

The earlier overstatement — that engine delivery alone meant a requirement was done — is
corrected: reachability is now its own audited dimension. The only deliberately-unreachable
Applicant surface is **Compare** (`present_but_disabled`), which is a product decision, not
a gap.

**What is and isn't proven by the test suite (honest note):** the **613 hermetic tests prove
the logic** of every requirement against fakes / in-memory adapters. They do NOT exercise the
real external boundaries end-to-end — that is what the **14 integration-gated skips** are for.
Those skips need a live deployment to run: DBOS/Postgres durable execution, a real browser
(patchright/playwright + a chromium binary), live job boards, real TeX (lualatex/xelatex) and
LibreOffice for docx conversion, a live Neko remote session, and live Discord/SMTP delivery.
These are **environment dependencies, not requirement gaps** — the production code paths exist
and are wired (egress threaded into the real launch, fc-cache shell-out, DBOS decorators,
email send, Postgres-persisted credentials/screenshots); only their live execution is gated
on the corresponding toolchain/service being present.

## Harvest hardening (Waves 1–4)

Traceability for requirements introduced during the Harvest & White-Label Migration Audit
(`docs/APPLICANT-SURVIVAL-PLAN.md`). Each row follows the same ID → WP → test anchor →
engine surface → front-door reachability schema.

| Requirement | WP | BDD / Test anchor | Engine surface | Front-door reachability |
|-------------|-----|-------------------|----------------|------------------------|
| NFR-ARCH-1 (import-linter) | Wave 1 | CI `lint-imports` step + `tests/architecture/test_layering` (`@pytest.mark.architecture`) | `pyproject.toml` `[tool.importlinter]` (2 contracts: `layers` + `forbidden`) | N/A — build-time guarantee; protects the safety property that is reachable via every front-door route |
| FR-HARVEST-CAPREG | Wave 2 | `tests/unit/test_capability_registry_drift.py` (16 drift tests; mutation→review invariant) | `src/applicant/application/capability_registry.py` (`CAPABILITY_REGISTRY` frozenset, 19 op groups, `REVIEW_EXEMPTIONS` with rationale) | the `/api/applicant/*` proxy boundary (declarative; runtime gates unchanged) |
| FR-HARVEST-CARET | Wave 2 | `node --check workspace/static/js/markdown.js`; visual playtest §6a | N/A (front-door only) | chat surface — `workspace/static/js/markdown.js` `addStreamingCaret`/`removeStreamingCaret`, integrated in `chat.js` |
| FR-HARVEST-PROVIDER | Wave 3 | `tests/unit/test_provider_profiles.py` (42 tests; profile detection, headers, URLs, extraction) | `adapters/llm/provider_profiles.py` + refactored `openai_compatible.py` | model-endpoint manager / `applicantOnboarding.js` |
| FR-HARVEST-TRUTHTIER | Wave 3 | `tests/unit/test_fabrication_grade.py` (30 tests; CLEAN/REVIEW/VIOLATION tiers) | `core/rules/truthfulness.py` `FabricationGrade` + `grade_unsupported_claims()` | review/redline — `applicantDocuments.js` / `documentLibrary.js` |
| NFR-OPS-1 | Wave 4 | `.github/workflows/ci-integration.yml` (manual + weekly lane); `tests/integration/test_ats_prefill_dryrun.py` (ATS dry-run, gated on `APPLICANT_ATS_DRY_RUN_URL`) | `container.py` real wiring (browser/TeX) + existing `@pytest.mark.integration` suite | trigger with real ATS URL to convert "wired" → "demonstrated"; stops at review boundary via `is_final_submit_page()` |
