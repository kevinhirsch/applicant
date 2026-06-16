# Traceability Matrix

Mandated by master spec §13: **Requirement ID → Work Package (phase) → BDD Feature(s) → adapter/contract test.** Any requirement lacking a downstream feature and test is a **GAP** to flag, not drop.

- **WP** = phase from [work-packages.md](work-packages.md) / §9.
- **BDD Feature(s)** seed from the §10 acceptance anchors where one exists; otherwise the feature name is proposed (to be authored per the work package) and noted.
- **Adapter / contract test** — many cells say "scaffold (Stage B)" because this is the spec tree (Stage A); the concrete adapters/contract tests are written in implementation. Core domain rules are tested in the core (no adapter).
- **GAP** rows: requirements with no §10 anchor get a proposed feature; rows where the spec defines no distinct downstream test surface are marked **GAP** explicitly.

§10 seed feature names (verbatim): Zero-CLI out-of-box setup; Per-campaign attribute cloud; Resume uploads right and looks right; Screening answers go through review; Sensitive fields are never AI-guessed; Pending-actions portal; Maximal pre-fill, stop at irreducible human steps; Interactive resume review with highlighted edits; Adaptation never fabricates; Mid-step crash resumption; Conversion is approval plus submission; Discord-first with 30s hold and web pre-empt; Master aggregator in wave one; Source-yield learning with exploration.

## FR-LLM

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-LLM-1 | 0 | "Zero-CLI out-of-box setup" (LLM step); *proposed:* "Provider-agnostic LLM (cloud or local)" | LLM port contract test (OpenRouter + Ollama adapters) — scaffold (Stage B) |
| FR-LLM-2 | 0 | "Zero-CLI out-of-box setup"; *proposed:* "Auto-populated model list" | LLM adapter model-list contract test — scaffold (Stage B) |
| FR-LLM-3 | 0 | *proposed:* "Configurable tier ladder" | Ladder config unit test (core) — scaffold (Stage B) |
| FR-LLM-4 | 0 | *proposed:* "Escalation climbs the ladder on low confidence / context overflow" | LLM escalation contract test — scaffold (Stage B) |
| FR-LLM-4a | 0 | *proposed:* "Defensive structured-output across model variance" | LLM adapter structured-output contract test — scaffold (Stage B) |
| FR-LLM-5 | 0 | *proposed:* "Token frugality with local default" (shared with NFR-TOKEN-1) | Token-budget assertion in LLM contract test — scaffold (Stage B) |

## FR-DISC

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-DISC-1 | 1 | "Master aggregator in wave one" | Discovery port contract test — scaffold (Stage B) |
| FR-DISC-2 | 1 | "Master aggregator in wave one" | JobSpy aggregator adapter contract test — scaffold (Stage B) |
| FR-DISC-3 | 1 | *proposed:* "Posting normalization" | Normalization unit test (core) — scaffold (Stage B) |
| FR-DISC-4 | 1 | *proposed:* "Zero-token structured discovery" | Discovery adapter no-LLM contract test — scaffold (Stage B) |
| FR-DISC-5 | 1 | "Source-yield learning with exploration" | Source-yield learning unit test (core) — scaffold (Stage B) |
| FR-DISC-6 | 1 | *proposed:* "Pluggable proxy hook" (SHOULD) | Proxy-hook interface contract test — scaffold (Stage B) |

## FR-CRIT

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-CRIT-1 | 1 | *proposed:* "Self-learning per-campaign criteria" | Criteria mutation unit test (core) — scaffold (Stage B) |
| FR-CRIT-2 | 1 | *proposed:* "Criteria editable and transparent" | Criteria editing driving-port test — scaffold (Stage B) |
| FR-CRIT-3 | 1 | *proposed:* "Criteria mutable by LLM and user" | Criteria mutation unit test (core) — scaffold (Stage B) |
| FR-CRIT-4 | 0 | "Per-campaign attribute cloud" | Campaign-scoping schema test — scaffold (Stage B) |

## FR-LEARN

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-LEARN-1 | 1 | "Per-campaign attribute cloud" (scoping); *proposed:* "Per-campaign learning" | LearningModel unit test (core) — scaffold (Stage B) |
| FR-LEARN-2 | 1 (depth 4) | "Conversion is approval plus submission" | OutcomeEvent → learning unit test (core) — scaffold (Stage B) |
| FR-LEARN-3 | 1 (depth 4) | *proposed:* "Learn from every input" | Learning-input integration test — scaffold (Stage B) |
| FR-LEARN-4 | 1 (depth 4) | *proposed:* "Cross-reference attribute cloud" | Attribute cross-reference unit test (core) — scaffold (Stage B) |
| FR-LEARN-5 | 1 | *proposed:* "Learn converting-role signature" | Signature-learning unit test (core) — scaffold (Stage B) |
| FR-LEARN-6 | 1 | "Source-yield learning with exploration" | Exploration-budget unit test (core) — scaffold (Stage B) |
| FR-LEARN-7 | 1 | *proposed:* "Cheap statistical learning" (SHOULD) | Embedding port contract test — scaffold (Stage B) |

## FR-DIG

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-DIG-1 | 1 | *proposed:* "Daily digest per campaign" | Digest generation unit test (core) — scaffold (Stage B) |
| FR-DIG-2 | 1 | "Discord-first with 30s hold and web pre-empt" (delivery) | Notification adapter contract test — scaffold (Stage B) |
| FR-DIG-3 | 1 | *proposed:* "Digest table with approve/decline" | DigestReview driving-port test — scaffold (Stage B) |
| FR-DIG-4 | 1 | *proposed:* "Why this role rationale" | Rationale unit test (core) — scaffold (Stage B) |
| FR-DIG-5 | 1 | *proposed:* "Decline with feedback" | Decision feedback unit test (core) — scaffold (Stage B) |
| FR-DIG-6 | 1 | *proposed:* "Empty-day note" (SHOULD) | Digest empty-day unit test (core) — scaffold (Stage B) |

## FR-FB

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-FB-1 | 1 | *proposed:* "Mandatory decline-with-feedback tunes next run" | Decision→criteria-delta unit test (core) — scaffold (Stage B) |
| FR-FB-2 | 1 | *proposed:* "Feedback via chat and survey" | Chat/survey driving-port test — scaffold (Stage B) |
| FR-FB-3 | 0 (rule), 1 (UI) | *proposed:* "Integral change requires confirmation" | Confirmation-gate unit test (core) — scaffold (Stage B) |

## FR-ATTR

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-ATTR-1 | 1 | "Per-campaign attribute cloud" | AttributeStore unit test (core) — scaffold (Stage B) |
| FR-ATTR-2 | 1 (use 2) | *proposed:* "Attribute binds to form field" | Field-mapping contract test — scaffold (Stage B) |
| FR-ATTR-3 | 1 | *proposed:* "Attribute editable by UI and feedback" | AttributeEditing driving-port test — scaffold (Stage B) |
| FR-ATTR-4 | 1 | *proposed:* "AI adds attributes dynamically" | AttributeStore dynamic-add unit test (core) — scaffold (Stage B) |
| FR-ATTR-5 | 2 | *proposed:* "Missing attribute soft-errors and is reused" | BLOCKED_MISSING_ATTR flow test — scaffold (Stage B) |
| FR-ATTR-6 | 0 (rule), 2 (fill) | "Sensitive fields are never AI-guessed" | Sensitive-field policy unit test (core) — scaffold (Stage B) |

## FR-ONBOARD

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-ONBOARD-1 | 0 | "Zero-CLI out-of-box setup" (intake step) | Onboarding intake schema test — scaffold (Stage B) |
| FR-ONBOARD-2 | 0 | "Zero-CLI out-of-box setup" (gate) | Onboarding completion-gate unit test (core) — scaffold (Stage B) |
| FR-ONBOARD-3 | 0 | *proposed:* "Bootstrap attribute cloud from base resume" | Resume-parse adapter contract test — scaffold (Stage B) |

## FR-OOBE

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-OOBE-1 | 0 | "Zero-CLI out-of-box setup" | Setup-wizard driving-port test — scaffold (Stage B) |
| FR-OOBE-2 | 0/1 | "Zero-CLI out-of-box setup" | Wizard-sequencing unit test (core) — scaffold (Stage B) |
| FR-OOBE-3 | 1 | "Zero-CLI out-of-box setup" (channels gate) | Channel-gating unit test (core) — scaffold (Stage B) |
| FR-OOBE-4 | 4 | *proposed:* "In-UI Update button" (SHOULD) | UpdateTrigger driving-port test — scaffold (Stage B) |

## FR-FONT

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-FONT-1 | 0 | "Resume uploads right and looks right" (font detection) | FontInstall port contract test — scaffold (Stage B) |
| FR-FONT-2 | 0/3 | "Resume uploads right and looks right" (install + cache) | FontInstall runtime-refresh contract test — scaffold (Stage B) |

## FR-PREFILL

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-PREFILL-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Sandbox port contract test — scaffold (Stage B) |
| FR-PREFILL-2 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Workday ATS adapter contract test — scaffold (Stage B) |
| FR-PREFILL-3 | 2 | *proposed:* "Map attributes to detected fields, escalate ambiguity" | Field-mapping + LLM-escalation contract test — scaffold (Stage B) |
| FR-PREFILL-4 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Pre-fill-stop boundary unit test (core) — scaffold (Stage B) |
| FR-PREFILL-5 | 2 | *proposed:* "Final submit: self or engine" | Final-approval gate test (DBOS recv) — scaffold (Stage B) |
| FR-PREFILL-6 | 2 | *proposed:* "Cautious mode pauses on detection" | DetectionMonitor adapter contract test — scaffold (Stage B) |
| FR-PREFILL-7 | 2 | *proposed:* "Emergency data-handoff only after fill failure" | EMERGENCY_DATA_HANDOFF flow test — scaffold (Stage B) |

## FR-RESUME / FR-ANSWER

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-RESUME-1 | 3 | *proposed:* "Engine decides material is needed" | MaterialPrep unit test (core) — scaffold (Stage B) |
| FR-RESUME-2 | 0/3 | "Adaptation never fabricates" | Truthfulness guardrail unit test (core) — scaffold (Stage B) |
| FR-RESUME-3 | 3 | "Resume uploads right and looks right" | ResumeTailoring port contract test (LaTeX + docx-XML) — scaffold (Stage B) |
| FR-RESUME-3a | 0/3 | *proposed:* "Onboarding conversion accept/reject gate" | Conversion-preview driving-port test — scaffold (Stage B) |
| FR-RESUME-4 | 3 | "Resume uploads right and looks right" | Fidelity-check (compile + inspect) contract test — scaffold (Stage B) |
| FR-RESUME-5 | 0/3 | *proposed:* "No em-dashes, voice-matched output" | Em-dash post-filter unit test (core) — scaffold (Stage B) |
| FR-RESUME-6 | 3 | *proposed:* "Variant library and lineage" | ResumeVariant lineage unit test (core) — scaffold (Stage B) |
| FR-RESUME-7 | 3 | *proposed:* "Score then reuse or generate variant" | ResumeFitScoring unit test (core) — scaffold (Stage B) |
| FR-RESUME-8 | 3 | "Interactive resume review with highlighted edits" | DocumentReview driving-port test + RevisionSession unit test (core) — scaffold (Stage B) |
| FR-RESUME-9 | 3/4 | *proposed:* "Aggressiveness control (grayed stub)" | Dormant-surface stub test — scaffold (Stage B); see [dormant-surfaces.md](dormant-surfaces.md) |
| FR-RESUME-10 | 3 | *proposed:* "Cover letters on demand" | Cover-letter generation unit test (core) — scaffold (Stage B) |
| FR-ANSWER-1 | 3 | "Screening answers go through review" | Screening-answer generation + review-gate test — scaffold (Stage B) |

## FR-SANDBOX

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-SANDBOX-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Sandbox adapter contract test — scaffold (Stage B) |
| FR-SANDBOX-2 | 2 | *proposed:* "One-click live remote session" | RemoteView sub-port contract test (Neko/noVNC) — scaffold (Stage B) |
| FR-SANDBOX-3 | 2 | *proposed:* "Submit-self or authorize engine from live session" | RemoteSessionControl driving-port test — scaffold (Stage B) |
| FR-SANDBOX-4 | 2 | *proposed:* "Multi-session, ephemeral per application" | Sandbox concurrency contract test — scaffold (Stage B) |

## FR-STEALTH

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-STEALTH-1 | 2 | *proposed:* "Coherent browser identity" | Fingerprint normalization contract test — scaffold (Stage B) |
| FR-STEALTH-2 | 2 | *proposed:* "Human-like interaction" | Interaction-cadence contract test — scaffold (Stage B) |
| FR-STEALTH-3 | 2 | *proposed:* "Persistent per-tenant profile" | Profile-persistence contract test — scaffold (Stage B) |
| FR-STEALTH-4 | 2 | *proposed:* "Residential egress" | Egress-routing contract test — scaffold (Stage B) |
| FR-STEALTH-5 | 2 | *proposed:* "Honest anti-detection caveat in UX" | UX-caveat presence test — scaffold (Stage B) |

## FR-DUR

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-DUR-1 | 0 | "Mid-step crash resumption" | DurableOrchestration contract test — scaffold (Stage B) |
| FR-DUR-2 | 0/2 | *proposed:* "24/7 continuous queue processing" | DBOS queue contract test — scaffold (Stage B) |
| FR-DUR-3 | 0 | "Mid-step crash resumption" | DBOS workflow/step resume contract test — scaffold (Stage B) |
| FR-DUR-4 | 0/2 | *proposed:* "Pivot around blocker" | Pivot unit test (core) — scaffold (Stage B) |

## FR-LOG

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-LOG-1 | 2 | "Conversion is approval plus submission" (log detail) | Application-log unit test (core) — scaffold (Stage B) |
| FR-LOG-2 | 2 | *proposed:* "Per-page screenshots archived" | Screenshot storage contract test — scaffold (Stage B) |
| FR-LOG-3 | 2/4 | *proposed:* "Logged data retrievable via UI" | AdminQuery driving-port test — scaffold (Stage B) |
| FR-LOG-4 | 2 | "Conversion is approval plus submission" | Submission-detection + mark-submitted test — scaffold (Stage B) |

## FR-AGENT

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-AGENT-1 | 1 | *proposed:* "Tunable throughput" | Throughput config unit test (core) — scaffold (Stage B) |
| FR-AGENT-2 | 1 | *proposed:* "Selectable run modes" | Run-mode unit test (core) — scaffold (Stage B) |
| FR-AGENT-3 | 1 | *proposed:* "Viability scoring from JD" | ViabilityScoring unit test (core) — scaffold (Stage B) |
| FR-AGENT-4 | 0/1 | *proposed:* "Pause and notify on any question" | BLOCKED_QUESTION flow test — scaffold (Stage B) |
| FR-AGENT-5 | 0 | *proposed:* "Never continue on uncertain response" | Uncertainty-halt unit test (core) — scaffold (Stage B) |
| FR-AGENT-6 | 0/2 | *proposed:* "Pivot around blockers" | Pivot unit test (core) — scaffold (Stage B) |
| FR-AGENT-7 | 1 | *proposed:* "One-sentence next-action log per run" | AgentIntent unit test (core) — scaffold (Stage B) |

## FR-NOTIF

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-NOTIF-1 | 1 | "Discord-first with 30s hold and web pre-empt" | Notification (Apprise/Discord) contract test — scaffold (Stage B) |
| FR-NOTIF-2 | 1/2 | "Discord-first with 30s hold and web pre-empt" | Escalation-ladder unit test (core) — scaffold (Stage B) |
| FR-NOTIF-3 | 1 | "Discord-first with 30s hold and web pre-empt" (idempotency scenario) | Idempotency unit test (core) — scaffold (Stage B) |
| FR-NOTIF-4 | 3 | "Interactive resume review with highlighted edits" (review link) | Review-notification link test — scaffold (Stage B) |
| FR-NOTIF-5 | 1 | *proposed:* "Immediate errors, optional quiet hours" | Quiet-hours unit test (core) — scaffold (Stage B) |

## FR-UI

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-UI-1 | 0 | *proposed:* "Pixel-perfect Odysseus clone" | Vendored static/ presence test — scaffold (Stage B) |
| FR-UI-2 | 0/4 | *proposed:* "Dormant surfaces grayed with stubs" | Dormant-surface backlog test — scaffold (Stage B); see [dormant-surfaces.md](dormant-surfaces.md) |
| FR-UI-3 | 1 | "Pending-actions portal" | PendingActionsQuery driving-port test — scaffold (Stage B) |
| FR-UI-4 | 4 | *proposed:* "Per-tool toggle registry" | ToolRegistry contract test — scaffold (Stage B) |
| FR-UI-5 | 0 | "Zero-CLI out-of-box setup" (LLM-gate first) | Wizard LLM-gate test — scaffold (Stage B) |
| FR-UI-6 | 1-4 | *proposed:* "UI exposes all core surfaces" | Per-surface driving-port tests — scaffold (Stage B) |

## FR-CHAT

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-CHAT-1 | 4 | *proposed:* "Chatbot assists input and updates attributes/criteria" | Chat driving-port test — scaffold (Stage B). **Soft mapping:** §9 lists the chatbot only under FR-UI-6 surfaces, not as its own phased sub-task. |

## FR-VAULT

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-VAULT-1 | 2 | *proposed:* "Encrypted credential store" | CredentialStore port contract test — scaffold (Stage B) |
| FR-VAULT-2 | 2 | *proposed:* "Both credential-banking modes" | Manual-entry + auto-capture contract test — scaffold (Stage B) |
| FR-VAULT-3 | 2 | *proposed:* "Key-file master key, secrets never logged" | Key-file + redaction test — scaffold (Stage B) |

## FR-OBS

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-OBS-1 | 0 | *proposed:* "Structured logging with correlation IDs" | structlog redaction test — scaffold (Stage B) |
| FR-OBS-2 | 4 | *proposed:* "Debug surface" | Debug-surface driving-port test — scaffold (Stage B) |

## FR-INSTALL

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| FR-INSTALL-1 | 4 | *proposed:* "One-liner install to Proxmox VM" | Install-script test — scaffold (Stage B) |
| FR-INSTALL-2 | 4 | *proposed:* "Update script with backup/migrate/rollback" | Update-script test — scaffold (Stage B) |
| FR-INSTALL-3 | 4 | *proposed:* "Docker Compose ships whole stack" | Compose-stack smoke test — scaffold (Stage B) |

## NFR

| ID | WP | BDD Feature(s) | Adapter / contract test |
|---|---|---|---|
| NFR-LOCAL-1 | 0 | *proposed:* "Fully-local operation" | Local-only integration test — scaffold (Stage B) |
| NFR-TOKEN-1 | 0-3 | *proposed:* "Three-layer token frugality" | Token-budget assertions across adapters — scaffold (Stage B) |
| NFR-247-1 | 0 | "Mid-step crash resumption" | Durability/uptime test — scaffold (Stage B) |
| NFR-CAUTION-1 | 2 | "Maximal pre-fill, stop at irreducible human steps" | Cautious-mode unit test (core) — scaffold (Stage B) |
| NFR-EXT-1 | 0/4 | "Master aggregator in wave one" (adapter extensibility) | Adapter-extensibility contract tests — scaffold (Stage B) |
| NFR-ARCH-1 | 0 | (cross-cutting; every feature maps to an ID) | Architecture fitness test (no core→adapter deps) — scaffold (Stage B) |
| NFR-ZEROCLI-1 | 0/4 | "Zero-CLI out-of-box setup" | Zero-CLI assertion test — scaffold (Stage B) |
| NFR-PRIV-1 | 2 | *proposed:* "Encrypted PII at rest, minimal cloud PII" (SHOULD) | Encryption-at-rest test — scaffold (Stage B) |
| NFR-TRUTH-1 | 0/3 | "Adaptation never fabricates" | Truthfulness guardrail unit test (core) — scaffold (Stage B) |

## GAP register

No requirement is dropped. The following are flagged for attention:

1. **FR-CHAT-1 — phase placement GAP (soft).** §3.20 mandates the chatbot but §9 never assigns it to a phase as its own sub-task; it appears only inside the FR-UI-6 surface list. Mapped to Phase 4 here; confirm during planning.
2. **FR-UI-6 — composite requirement.** It bundles many surfaces (criteria editing, attribute-cloud editor, history, variant library + redline, debug surface, chatbot, onboarding wizard, Update button) that land across Phases 1-4. Tracked as a span, not a single test; each sub-surface has its own row above.
3. **Requirements with no §10 anchor** (the majority, marked *proposed:* above) need BDD features authored in their work package — this is expected scaffolding, not a spec gap, but is listed so coverage is verifiable.
4. **All "adapter/contract test" cells** are "scaffold (Stage B)" because Stage A is docs only; no test is yet implemented. This is by design for this stage.
