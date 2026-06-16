# Traceability Matrix

Mandated by master spec §13: **Requirement ID → Work Package (phase) → BDD Feature(s) → adapter/contract test.** Any requirement lacking a downstream feature and test is a **GAP** to flag, not drop.

**Status (2026-06): all five phases (0–4) are implemented and merged to `main`.** Every row
below reflects the **delivered** state — the adapter/service/router that satisfies the
requirement plus the contract and/or BDD test that now covers it. The test suite is green
(`uv run pytest -q`: 539 passed, 10 integration skips). See
[delivery-status.md](delivery-status.md) for the per-phase delivery summary.

- **WP** = phase from [work-packages.md](work-packages.md) / §9.
- **BDD Feature(s)** are the §10 acceptance anchors plus the features authored per work
  package; live under `tests/bdd/features/` (23 `.feature` files).
- **Status** column reports delivery: the satisfying code surface (adapter / service /
  router / core rule) and the test surface that covers it. Core domain rules are tested in
  the core (no adapter); adapters carry contract tests; flows carry BDD scenarios.
- **GAP** rows: any requirement genuinely not delivered is flagged in **Remaining gaps**
  below. As of this closeout there are none — every FR-*/NFR-* is delivered.

§10 seed feature names (verbatim): Zero-CLI out-of-box setup; Per-campaign attribute cloud; Resume uploads right and looks right; Screening answers go through review; Sensitive fields are never AI-guessed; Pending-actions portal; Maximal pre-fill, stop at irreducible human steps; Interactive resume review with highlighted edits; Adaptation never fabricates; Mid-step crash resumption; Conversion is approval plus submission; Discord-first with 30s hold and web pre-empt; Master aggregator in wave one; Source-yield learning with exploration.

## FR-LLM

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-LLM-1 | 0 | "Zero-CLI out-of-box setup" (LLM step); "Provider-agnostic LLM (cloud or local)" | Delivered — Phase 0; LLM port + OpenRouter/OpenAI-compatible and Ollama adapters; contract test |
| FR-LLM-2 | 0 | "Zero-CLI out-of-box setup"; "Auto-populated model list" | Delivered — Phase 0; LLM adapter model-list + setup router; contract test |
| FR-LLM-3 | 0 | "Configurable tier ladder" | Delivered — Phase 0; ladder config in core; unit test |
| FR-LLM-4 | 0 | "Escalation climbs the ladder on low confidence / context overflow" | Delivered — Phase 0; escalation router in LLM service; contract+unit test |
| FR-LLM-4a | 0 | "Defensive structured-output across model variance" | Delivered — Phase 0; defensive parse + prompt-fallback in LLM adapter; contract test |
| FR-LLM-5 | 0 | "Token frugality with local default" (shared with NFR-TOKEN-1) | Delivered — Phase 0; local-default routing + token-budget assertions; contract test |

## FR-DISC

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DISC-1 | 1 | "Master aggregator in wave one" | Delivered — Phase 1; discovery port + scheduled scan; contract+BDD |
| FR-DISC-2 | 1 | "Master aggregator in wave one" | Delivered — Phase 1; JobSpy aggregator adapter (`python-jobspy`); contract+BDD |
| FR-DISC-3 | 1 | "Posting normalization" | Delivered — Phase 1; normalization in core; unit test |
| FR-DISC-4 | 1 | "Zero-token structured discovery" | Delivered — Phase 1; no-LLM discovery path; contract test (token-budget assertion) |
| FR-DISC-5 | 1 | "Source-yield learning with exploration" | Delivered — Phase 1; source-yield learning in core; unit+BDD |
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
| FR-LEARN-5 | 1 | "Learn converting-role signature" | Delivered — Phase 1; signature-learning in core; unit test |
| FR-LEARN-6 | 1 | "Source-yield learning with exploration" | Delivered — Phase 1; exploration-budget in core; unit+BDD |
| FR-LEARN-7 | 1 | "Cheap statistical learning" (SHOULD) | Delivered — Phase 1; local embedding port + statistical learning; contract test |

## FR-DIG

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DIG-1 | 1 | "Daily digest per campaign" | Delivered — Phase 1; DigestService (composed in digest router); unit+BDD |
| FR-DIG-2 | 1 | "Discord-first with 30s hold and web pre-empt" (delivery) | Delivered — Phase 1; notification adapter (Apprise) delivery; contract+BDD |
| FR-DIG-3 | 1 | "Digest table with approve/decline" | Delivered — Phase 1; digest router (driving port) approve/decline; contract+BDD |
| FR-DIG-4 | 1 | "Why this role rationale" | Delivered — Phase 1; rationale in core/digest; unit test |
| FR-DIG-5 | 1 | "Decline with feedback" | Delivered — Phase 1; decision-feedback in core; unit+BDD |
| FR-DIG-6 | 1 | "Empty-day note" (SHOULD) | Delivered — Phase 1; empty-day digest path; unit test |

## FR-FB

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-FB-1 | 1 | "Mandatory decline-with-feedback tunes next run" | Delivered — Phase 1; decision→criteria-delta in core; unit+BDD |
| FR-FB-2 | 1 | "Feedback via chat and survey" | Delivered — Phase 1/4; feedback router + chat (Phase 4); contract+BDD |
| FR-FB-3 | 0 (rule), 1 (UI) | "Integral change requires confirmation" | Delivered — Phase 0 rule + Phase 1 UI; confirmation-gate in core; unit+BDD |

## FR-ATTR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-ATTR-1 | 1 | "Per-campaign attribute cloud" | Delivered — Phase 1; AttributeStore in core; unit+BDD |
| FR-ATTR-2 | 1 (use 2) | "Attribute binds to form field" | Delivered — Phase 1 (used Phase 2 pre-fill); field-mapping; contract test |
| FR-ATTR-3 | 1 | "Attribute editable by UI and feedback" | Delivered — Phase 1; attributes router (driving port); contract+BDD |
| FR-ATTR-4 | 1 | "AI adds attributes dynamically" | Delivered — Phase 1; AttributeStore dynamic-add in core; unit test |
| FR-ATTR-5 | 2 | "Missing attribute soft-errors and is reused" | Delivered — Phase 2; BLOCKED_MISSING_ATTR flow; flow+BDD |
| FR-ATTR-6 | 0 (rule), 2 (fill) | "Sensitive fields are never AI-guessed" | Delivered — Phase 0 rule + Phase 2 fill; sensitive-field policy in core; unit+BDD |

## FR-ONBOARD

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-ONBOARD-1 | 0 | "Zero-CLI out-of-box setup" (intake step) | Delivered — Phase 0; onboarding intake schema + router; contract test |
| FR-ONBOARD-2 | 0 | "Zero-CLI out-of-box setup" (gate) | Delivered — Phase 0; resumable interview + completion-gate in core; unit+BDD |
| FR-ONBOARD-3 | 0 | "Bootstrap attribute cloud from base resume" | Delivered — Phase 0; resume-parser adapter (`pypdf`/`python-docx`); contract test |

## FR-OOBE

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-OOBE-1 | 0 | "Zero-CLI out-of-box setup" | Delivered — Phase 0; setup-wizard router (driving port); contract+BDD |
| FR-OOBE-2 | 0/1 | "Zero-CLI out-of-box setup" | Delivered — Phase 0/1; wizard-sequencing in core; unit test |
| FR-OOBE-3 | 1 | "Zero-CLI out-of-box setup" (channels gate) | Delivered — Phase 1; channel-gating in core; unit+BDD |
| FR-OOBE-4 | 4 | "In-UI Update button" (SHOULD) | Delivered — Phase 4; update router (driving port) + `scripts/update.sh`; contract test |

## FR-FONT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-FONT-1 | 0 | "Resume uploads right and looks right" (font detection) | Delivered — Phase 0; FontInstall port + fonts router; contract test |
| FR-FONT-2 | 0/3 | "Resume uploads right and looks right" (install + cache) | Delivered — Phase 0 flow / Phase 3 render; runtime font-cache refresh; contract test |

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
| FR-RESUME-2 | 0/3 | "Adaptation never fabricates" | Delivered — Phase 0 rule / Phase 3 impl; truthfulness guardrail in core; unit+BDD |
| FR-RESUME-3 | 3 | "Resume uploads right and looks right" | Delivered — Phase 3; ResumeTailoring port (LaTeX + docx-XML via `jinja2`/`python-docx`); contract+BDD |
| FR-RESUME-3a | 0/3 | "Onboarding conversion accept/reject gate" | Delivered — Phase 0 gate / Phase 3 engine; conversion router (driving port); contract test |
| FR-RESUME-4 | 3 | "Resume uploads right and looks right" | Delivered — Phase 3; fidelity-check (compile + inspect); contract test (real-TeX variant integration-gated) |
| FR-RESUME-5 | 0/3 | "No em-dashes, voice-matched output" | Delivered — Phase 0 rule / Phase 3 impl; em-dash post-filter in core; unit test |
| FR-RESUME-6 | 3 | "Variant library and lineage" | Delivered — Phase 3; ResumeVariant lineage in core; unit test |
| FR-RESUME-7 | 3 | "Score then reuse or generate variant" | Delivered — Phase 3; ResumeFitScoring + select_or_generate; unit test |
| FR-RESUME-8 | 3 | "Interactive resume review with highlighted edits" | Delivered — Phase 3; documents router + durable RevisionSession repo (Phase 3b); contract+BDD |
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
| FR-STEALTH-1 | 2 | "Coherent browser identity" | Delivered — Phase 2; fingerprint normalization (browser adapter); contract test |
| FR-STEALTH-2 | 2 | "Human-like interaction" | Delivered — Phase 2; interaction-cadence in browser adapter; contract test |
| FR-STEALTH-3 | 2 | "Persistent per-tenant profile" | Delivered — Phase 2; profile-persistence in browser adapter; contract test |
| FR-STEALTH-4 | 2 | "Residential egress" | Delivered — Phase 2; egress-routing hook; contract test |
| FR-STEALTH-5 | 2 | "Honest anti-detection caveat in UX" | Delivered — Phase 2; UX-caveat surfaced; presence test |

## FR-DUR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-DUR-1 | 0 | "Mid-step crash resumption" | Delivered — Phase 0; orchestration port (shim default + DBOS adapter); contract+BDD |
| FR-DUR-2 | 0/2 | "24/7 continuous queue processing" | Delivered — Phase 0 backbone / Phase 2 queues; durable queue; contract test (DBOS variant integration-gated) |
| FR-DUR-3 | 0 | "Mid-step crash resumption" | Delivered — Phase 0; workflow/step resume; contract+BDD (DBOS variant integration-gated) |
| FR-DUR-4 | 0/2 | "Pivot around blocker" | Delivered — Phase 0 rule / Phase 2 live; pivot in core; unit test |

## FR-LOG

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-LOG-1 | 2 | "Conversion is approval plus submission" (log detail) | Delivered — Phase 2; application-log in core/storage; unit test |
| FR-LOG-2 | 2 | "Per-page screenshots archived" | Delivered — Phase 2; screenshot storage; contract test |
| FR-LOG-3 | 2/4 | "Logged data retrievable via UI" | Delivered — Phase 2 capture / Phase 4 history UI; AdminQueryService + admin router; contract test |
| FR-LOG-4 | 2 | "Conversion is approval plus submission" | Delivered — Phase 2; submission-detection + mark-submitted; flow+BDD |

## FR-AGENT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-AGENT-1 | 1 | "Tunable throughput" | Delivered — Phase 1; throughput config in core; unit test |
| FR-AGENT-2 | 1 | "Selectable run modes" | Delivered — Phase 1; run-mode in core + agent_runs router; unit test |
| FR-AGENT-3 | 1 | "Viability scoring from JD" | Delivered — Phase 1; ViabilityScoring in core; unit test |
| FR-AGENT-4 | 0/1 | "Pause and notify on any question" | Delivered — Phase 0 rule / Phase 1 live; BLOCKED_QUESTION flow; flow+BDD |
| FR-AGENT-5 | 0 | "Never continue on uncertain response" | Delivered — Phase 0; uncertainty-halt in core; unit test |
| FR-AGENT-6 | 0/2 | "Pivot around blockers" | Delivered — Phase 0 rule / Phase 2 live; pivot in core; unit test |
| FR-AGENT-7 | 1 | "One-sentence next-action log per run" | Delivered — Phase 1; AgentIntent in core + agent_runs router; unit test |

## FR-NOTIF

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-NOTIF-1 | 1 | "Discord-first with 30s hold and web pre-empt" | Delivered — Phase 1; notification adapter (Apprise/Discord); contract+BDD (live-Discord integration-gated) |
| FR-NOTIF-2 | 1/2 | "Discord-first with 30s hold and web pre-empt" | Delivered — Phase 1 digest / Phase 2 final-approval; escalation-ladder in core; unit+BDD |
| FR-NOTIF-3 | 1 | "Discord-first with 30s hold and web pre-empt" (idempotency scenario) | Delivered — Phase 1; idempotency in core; unit+BDD |
| FR-NOTIF-4 | 3 | "Interactive resume review with highlighted edits" (review link) | Delivered — Phase 3; review-notification link; unit test |
| FR-NOTIF-5 | 1 | "Immediate errors, optional quiet hours" | Delivered — Phase 1; quiet-hours in core; unit test |

## FR-UI

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-UI-1 | 0 | "Pixel-perfect Odysseus clone" | Delivered — Phase 0; vendored `static/` served from FastAPI; presence test |
| FR-UI-2 | 0/4 | "Dormant surfaces grayed with stubs" | Delivered — Phase 0 shell / Phase 4 backlog; dormant-surface backlog test — see [dormant-surfaces.md](dormant-surfaces.md) |
| FR-UI-3 | 1 | "Pending-actions portal" | Delivered — Phase 1; pending_actions router (driving port); contract+BDD |
| FR-UI-4 | 4 | "Per-tool toggle registry" | Delivered — Phase 4; ToolRegistry adapter + settings sink; contract test |
| FR-UI-5 | 0 | "Zero-CLI out-of-box setup" (LLM-gate first) | Delivered — Phase 0; wizard LLM-gate; unit+BDD |
| FR-UI-6 | 1-4 | "UI exposes all core surfaces" | Delivered across Phases 1–4 (composite); per-surface routers (criteria, attributes, history/admin, documents redline, debug, chat, onboarding, update); each sub-surface covered by its own row + test |

## FR-CHAT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-CHAT-1 | 4 | "Chatbot assists input and updates attributes/criteria" | Delivered — Phase 4; ChatService (container-wired) + chat router; confirmation-gated (FR-FB-3); contract (`p4_chatbot.feature`)+unit+integration. (Previously flagged as a soft phase-placement gap; resolved by landing in Phase 4.) |

## FR-VAULT

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-VAULT-1 | 2 | "Encrypted credential store" | Delivered — Phase 2; CredentialStore port + encrypted-Postgres adapter (`pynacl`); contract test |
| FR-VAULT-2 | 2 | "Both credential-banking modes" | Delivered — Phase 2; manual-entry (credentials router) + auto-capture; contract test |
| FR-VAULT-3 | 2 | "Key-file master key, secrets never logged" | Delivered — Phase 2; key-file master key + redaction; contract+redaction test |

## FR-OBS

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-OBS-1 | 0 | "Structured logging with correlation IDs" | Delivered — Phase 0; structlog + correlation IDs + secret redaction; redaction test |
| FR-OBS-2 | 4 | "Debug surface" | Delivered — Phase 4; AdminQueryService + admin router (logs/screenshots/history/workflow state); contract test |

## FR-INSTALL

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| FR-INSTALL-1 | 4 | "One-liner install to Proxmox VM" | Delivered — Phase 4; `scripts/install.sh` (idempotent, dry-run/`--apply`); install-script test |
| FR-INSTALL-2 | 4 | "Update script with backup/migrate/rollback" | Delivered — Phase 4; `scripts/update.sh` (backup/migrate/restart/rollback); update-script test |
| FR-INSTALL-3 | 4 | "Docker Compose ships whole stack" | Delivered — Phase 4; Compose stack; compose-stack smoke test |

## NFR

| ID | WP | BDD Feature(s) | Status |
|---|---|---|---|
| NFR-LOCAL-1 | 0 | "Fully-local operation" | Delivered — Phase 0; local-only path (Ollama LLM + local embeddings + shim orchestrator); integration test |
| NFR-TOKEN-1 | 0-3 | "Three-layer token frugality" | Delivered across Phases 0–3; zero-token discovery/scoring, deterministic pre-fill, LLM only for generation/ambiguity; token-budget assertions across adapters |
| NFR-247-1 | 0 | "Mid-step crash resumption" | Delivered — Phase 0; durable orchestration; durability/resumption test |
| NFR-CAUTION-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Delivered — Phase 2; cautious-mode in core; unit+BDD |
| NFR-EXT-1 | 0/4 | "Master aggregator in wave one" (adapter extensibility) | Delivered — Phase 0 rule / Phase 4 verify; adapter-extensibility (sources, ATS, tools, models, channels); contract tests |
| NFR-ARCH-1 | 0 | (cross-cutting; every feature maps to an ID) | Delivered — Phase 0; hexagonal + BDD + TDD; architecture fitness test (no core→adapter deps) |
| NFR-ZEROCLI-1 | 0/4 | "Zero-CLI out-of-box setup" | Delivered — Phase 0 rule / Phase 4 update; zero-CLI setup + in-UI update; assertion test |
| NFR-PRIV-1 | 2 | "Encrypted PII at rest, minimal cloud PII" (SHOULD) | Delivered — Phase 2; encryption-at-rest (`pynacl`) + minimal-cloud-PII policy; encryption test |
| NFR-TRUTH-1 | 0/3 | "Adaptation never fabricates" | Delivered — Phase 0 rule / Phase 3 impl; truthfulness guardrail in core; unit+BDD |

## Coverage check

- **Exhaustive:** every FR-*/NFR-* ID in [requirements.md](requirements.md) (110 functional
  + 9 non-functional = **119**) has a row above. Verified against the requirements catalog
  family counts.
- **All delivered:** every row reports a delivered code surface plus a covering test
  (contract / BDD / unit / flow). The suite is green (539 passed; 10 skips are
  integration-gated boundaries — see below).

## Remaining gaps

**None.** As of this closeout no FR-*/NFR-* requirement is undelivered. Previously-flagged
soft gaps are resolved:

1. **FR-CHAT-1 (was a soft phase-placement gap).** §3.20 mandated the chatbot but §9 listed
   it only inside the FR-UI-6 surface span. It is now delivered as a first-class Phase 4
   surface: `ChatService` (container-wired) + chat router, confirmation-gated per FR-FB-3,
   covered by `tests/bdd/features/p4_chatbot.feature` plus unit and integration tests.
2. **FR-UI-6 (composite).** The bundled surfaces (criteria editing, attribute-cloud editor,
   history retrieval, variant library + redline, debug surface, chatbot, onboarding wizard,
   Update button) are all delivered across Phases 1–4; each has its own row + test above.
   Tracked as a span, not a single test.

**Integration-gated (not gaps):** the 10 skipped tests exercise real external boundaries
that require a live deployment — DBOS/Postgres durable orchestration, real browser
(patchright/playwright), live job boards, real TeX (lualatex/xelatex), live Neko remote
session, and live Discord/SMTP delivery. The hermetic default lane proves the same logic
with fakes; the gated tests run only when the corresponding env/toolchain is present.
