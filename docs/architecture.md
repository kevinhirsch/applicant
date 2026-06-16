# Architecture

Source: master spec §2 (architectural principles), §6 (hexagonal architecture), §7 (state machine). This document is the canonical statement of the ports-and-adapters structure and the domain rules the core enforces. Covers **NFR-ARCH-1**, **FR-DUR-3**, **FR-UI-1**, and the domain-rule requirements (**FR-RESUME-2 / NFR-TRUTH-1**, **FR-PREFILL-4**, **FR-ATTR-6**, **FR-FB-3**, **FR-RESUME-8**).

## Dependency rule

> **The core depends only on port interfaces. Each adapter has a contract test.** (§6 Rules)

The core domain is pure: no I/O, no framework imports, no knowledge of HTTP/Postgres/Playwright/DBOS. All external concerns are reached through **ports** (interfaces defined by the core). Concrete **adapters** implement those interfaces at the edge and are injected. Dependencies point inward only. Every adapter ships with a **contract test** proving it honors the port's behavioral contract, so adapters are swappable (e.g., Neko ↔ noVNC remote-view, OpenRouter ↔ Ollama LLM, LaTeX ↔ docx-XML resume engine) without touching the core.

## Binding architectural principles (§2)

| Principle | Statement |
|---|---|
| Hexagonal | Pure core domain, no I/O; all external concerns are ports with swappable adapters. |
| BDD / TDD | Gherkin features mapped to requirement IDs drive implementation; failing test first. |
| Local-first, LLM cloud-or-local | Everything runs on Proxmox; embeddings local. LLM reasoning is the one component that may be cloud (OpenAI-compatible API) or local (network Ollama); the system can run fully local. No paid external service except an optional cloud LLM. |
| Durable execution | Mid-step crash resumption from day one via a lightweight Postgres-backed library (no separate server). |
| Token frugality | LLM is the last resort. Zero-token discovery + local scoring; LLM only for generation, ambiguous mapping, reasoning. |
| Maximal pre-fill | Pre-fill every fillable field on every page of every ATS; never cut corners; stop only at irreducible human steps. |
| Human-in-the-loop | On any uncertainty, detection signal, missing attribute, or generated material — pause and notify; never guess; never auto-submit generated material without approval. |
| Pivot, don't block | One blocked/awaiting application never stalls unrelated work. |
| Truthfulness | Resume/cover-letter/answer adaptation reframes real experience; it never fabricates. |
| Zero-CLI operation | All setup, configuration, and updates happen through the UI; nothing logical requires a command line after install. |
| Campaign-scoped, multi-ready | Everything is campaign-scoped from day one; MVP-1 runs a single campaign but the data model and architecture make multi-campaign drop-in without rework. |
| Scaffold-and-gray | When a future control or surface isn't ready, build it visually, gray it out, and leave a stub spec to complete it later. |
| Extensibility | New discovery sources, ATS adapters, tools, models, channels, and UI surfaces add via adapters without core changes. |

## Core domain entities (pure) — §6

No I/O. These hold state and enforce the domain rules.

| Entity | Responsibility |
|---|---|
| **Campaign** | Scopes everything (criteria, attribute cloud, resumes, credentials, learning). FR-CRIT-4. |
| **SearchCriteria** | Human-readable, UI- and LLM-mutable, self-learning criteria. FR-CRIT-1..3. |
| **JobPosting** | Normalized posting (title, company, location, work mode, salary, URL, description). FR-DISC-3. |
| **ViabilityScoring** | Scores whether the user could reasonably get the role, from the JD. FR-AGENT-3. |
| **ResumeVariant (+ lineage)** | Forked resume variants with parent lineage; only approved ones reusable. FR-RESUME-6. |
| **ResumeFitScoring** | Coverage check of a variant against a JD (distinct from viability). FR-RESUME-7. |
| **GeneratedDocument** | Resume / cover-letter / screening-answer artifact with approval state. FR-RESUME-1/10, FR-ANSWER-1. |
| **RevisionSession** | Interactive add/subtract/free-text redline loop turns. FR-RESUME-8. |
| **AttributeStore** | Per-campaign attribute→value cloud with aliases, confirmation gate, sensitive-field policy. FR-ATTR-*. |
| **Decision** | Approve/decline with feedback and criteria delta. FR-DIG-3/5, FR-FB-1. |
| **OutcomeEvent** | Submission/conversion event (auto or manual source). FR-LOG-4, FR-LEARN-2. |
| **LearningModel** | Per-campaign learning state biasing discovery/scoring/selection. FR-LEARN-*. |
| **AgentIntent** | The single next-action sentence per run. FR-AGENT-7. |
| **DetectionEvent** | Automation-detection signal triggering cautious mode. FR-PREFILL-6, FR-STEALTH. |
| **OnboardingProfile** | Resumable Workday-ready intake; completion gates automated work. FR-ONBOARD-*. |
| **PendingAction** | Anything awaiting user input, for the portal. FR-UI-3. |

## Driving ports (inbound / use-case facing) — §6

Invoked by the UI and schedulers to drive the core.

| Driving port | Purpose |
|---|---|
| **SetupWizard / OOBE** | Sequenced UI setup; LLM gate first. FR-OOBE, FR-UI-5. |
| **CampaignManagement** | Create/configure (clone-ready) campaigns. FR-CRIT-4. |
| **AttributeEditing** | Edit attribute cloud (with confirmation gate). FR-ATTR-3. |
| **DigestReview** | Approve/decline-with-feedback digest rows. FR-DIG, FR-FB-1. |
| **DocumentReview** | Redline + add/subtract/free-text revision for resume/cover-letter/answer. FR-RESUME-8. |
| **Chat** | Conversational input/gap-finding, updates attributes/criteria. FR-CHAT-1. |
| **RemoteSessionControl** | Open/control live session; submit-self or authorize engine. FR-SANDBOX-3, FR-PREFILL-5. |
| **OutcomeLogging** | Mark-submitted when auto-detection cannot. FR-LOG-4. |
| **PendingActionsQuery** | Feed the pending-actions portal. FR-UI-3. |
| **AdminQuery** | History/screenshots/workflow-state retrieval. FR-LOG-3, FR-OBS-2. |
| **UpdateTrigger** | Invoke update script from the UI. FR-OOBE-4, FR-INSTALL-2. |

## Driven ports (outbound / infrastructure facing) — §6

Implemented by adapters; each has a contract test.

| Driven port | Default adapter(s) | Requirements |
|---|---|---|
| **LLM** | OpenRouter (cloud) and/or Ollama (local), OpenAI-compatible, tier ladder | FR-LLM-* |
| **Discovery** | JobSpy master aggregator; pluggable per-source; SearXNG exploratory | FR-DISC-* |
| **BrowserAutomation** | patchright/Playwright; browser-use/Skyvern fallback | FR-PREFILL, FR-STEALTH |
| **DetectionMonitor** | CAPTCHA/Turnstile/Cloudflare/403/429 signals | FR-PREFILL-6 |
| **Sandbox + RemoteView (sub-port)** | Neko + neko-rooms; RemoteView swappable Neko↔noVNC | FR-SANDBOX-1/2/4 |
| **ResumeTailoring** | LaTeX primary (xelatex/lualatex+fontspec, moderncv) / docx-XML fallback; redline + embedded-font export | FR-RESUME-3/4 |
| **FontInstall** | Install uploaded fonts, refresh cache at runtime | FR-FONT-* |
| **Embedding** | Local embedding model (dedup, variant scoring, conversion) | NFR-LOCAL-1 |
| **Storage** | Postgres/JSONB + screenshot store | FR-ATTR, FR-LOG, FR-DUR |
| **CredentialStore** | Encrypted Postgres (libsodium) / Vaultwarden later | FR-VAULT-* |
| **Notification** | Apprise + Discord gateway bot | FR-NOTIF-* |
| **DurableOrchestration** | DBOS Transact (Postgres-backed, no separate server) | FR-DUR-* |
| **ToolRegistry** | Per-tool on/off toggles | FR-UI-4 |

## Domain rules enforced in the core (§6)

These are **not** adapter concerns; they live in the pure core so no adapter can bypass them.

1. **Truthfulness** (FR-RESUME-2, NFR-TRUTH-1) — Adaptation reframes/reorders/re-terms real experience and surfaces true history; it never fabricates qualifications, titles, dates, or skills. The fit-scorer is a coverage check, never a fabrication target.
2. **Pre-fill-stop boundary** (FR-PREFILL-4) — The engine pre-fills every fillable field but **stops and hands off** at irreducible human steps: it never clicks an account-creating submit, never solves/bypasses a CAPTCHA, never completes email/SMS verification.
3. **Sensitive-field policy** (FR-ATTR-6) — Demographic/EEO/self-identification fields are filled only from the user's explicit stored answers, never AI-guessed, defaulting to "decline to self-identify".
4. **Confirmation-on-integral-change** (FR-FB-3) — Any integral change (core attribute value or core criterion) requires explicit user confirmation before commit; non-integral updates may auto-apply.
5. **Mandatory review-before-submission** (FR-RESUME-8, FR-ANSWER-1) — Any application carrying an edited resume, generated cover letter, or generated screening answer must pass the interactive review/revision gate; submission is impossible until the user approves; generated material is never auto-submitted.

## Durable execution mapping (§3.15, FR-DUR-3)

- Each application = one durable **DBOS workflow**; each small idempotent step (navigate, fill field, screenshot, score, generate) is individually checkpointed → true mid-step resumption.
- **DBOS durable queues** enforce the sandbox concurrency cap and per-provider LLM rate limiting.
- **DBOS `send`/`recv`** implement the approval gates and revision-loop hand-offs.
- **DBOS scheduling** drives cron-like work (digests, discovery). LangGraph is the reasoning loop *within* steps.

See [ADR-0001](adr/0001-hexagonal.md) (hexagonal + BDD + TDD) and [ADR-0002](adr/0002-dbos.md) (DBOS choice).
