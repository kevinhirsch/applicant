# Requirements Catalog

Source of truth: [`docs/spec/master-spec.md`](spec/master-spec.md) (Consolidated v4.4). This catalog enumerates **every** requirement ID in the master spec with its MoSCoW priority, a one-line summary, and the work-package phase (0-4, per §9) where it lands. No ID is omitted; where a requirement spans phases, the **primary** delivery phase is listed and secondary phases are noted in the summary.

Priority language (§ preamble): **MUST** = non-negotiable; **SHOULD** = strong recommendation, deviate only with rationale; **MAY** = optional/forward-looking.

## Functional requirements

### FR-LLM — LLM / model access (§3.1)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-LLM-1 | MUST | Provider-agnostic LLM port: OpenAI-compatible cloud API and/or local/network Ollama; can run fully local. | 0 |
| FR-LLM-2 | MUST | Auto-populate model list from the configured provider; provider/model/endpoint/key set and edited via UI (OOBE). | 0 |
| FR-LLM-3 | MUST | User-defined ordered, capability-ranked tier ladder (L1→LN), each tier any model from any provider; reorderable, 1-N tiers (default 3). | 0 |
| FR-LLM-4 | MUST | Escalation = climb the ladder on low confidence, context overflow, or per-task starting tier; top tier is the ceiling, surface gracefully. | 0 |
| FR-LLM-4a | MUST | Adapter robust to model variance in function-calling/JSON-mode/context; defensive parse + prompt-based structured-output fallback; never exceed context. | 0 |
| FR-LLM-5 | MUST | Minimize tokens (NFR-TOKEN-1); local default keeps routine work free/private, only escalations cost. | 0 |

### FR-DISC — Discovery & pluggable sources (§3.2)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-DISC-1 | MUST | Agentically scan the internet on a schedule to gather postings. | 1 |
| FR-DISC-2 | MUST | Wave-one master aggregator over easy sources (JobSpy boards); pluggable, user-toggleable, extensible source adapters. | 1 |
| FR-DISC-3 | MUST | Per-posting normalization: title, company, location, work mode, salary, source URL, full description. | 1 |
| FR-DISC-4 | MUST | Gather maximal sensible data; structured scraping/metasearch incur zero LLM tokens. | 1 |
| FR-DISC-5 | MUST | Source-yield learning: track per-source matches→approvals→submissions, reweight, with a learned exploration budget. | 1 |
| FR-DISC-6 | SHOULD | Design a pluggable proxy hook for hostile boards later without committing to a proxy now. | 1 |

### FR-CRIT — Search criteria & campaign scope (§3.3)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-CRIT-1 | MUST | Criteria dynamic, exploratory, self-learning per campaign. | 1 |
| FR-CRIT-2 | MUST | Criteria human-readable and UI-editable always; learned adjustments surfaced transparently and overridable. | 1 |
| FR-CRIT-3 | MUST | Criteria mutable by the LLM (learning/feedback) and directly by the user. | 1 |
| FR-CRIT-4 | MUST | Everything campaign-scoped; MVP-1 single campaign, model/ports multi-campaign-ready without rework. | 0 |

### FR-LEARN — Learning & optimization engine (§3.4)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-LEARN-1 | MUST | Learning is per campaign. | 1 |
| FR-LEARN-2 | MUST | Conversion = approval taste + final submission; learn real conversion, not only approval. | 1 (depth in 4) |
| FR-LEARN-3 | MUST | Learn from every input: digest approvals/declines, submissions, career data, chat, surveys, revision feedback. | 1 (depth in 4) |
| FR-LEARN-4 | MUST | Cross-reference parsed input with the attribute cloud; auto-apply non-integral, confirm integral (FR-FB-3). | 1 (depth in 4) |
| FR-LEARN-5 | MUST | Learn the signature of converting roles; bias discovery + scoring + variant selection toward it. | 1 |
| FR-LEARN-6 | MUST | Include the exploration budget (FR-DISC-5). | 1 |
| FR-LEARN-7 | SHOULD | Keep learning cheap (statistical/local-embedding); reserve LLM for human-readable criteria summaries. | 1 |

### FR-DIG — Daily digest (§3.5)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-DIG-1 | MUST | Produce a daily digest per campaign when matches are aggregated. | 1 |
| FR-DIG-2 | MUST | Delivery via email/webpage + Discord "ready" notification; digest exempt from Applicant visual style. | 1 |
| FR-DIG-3 | MUST | Table, one row per role: summary, link, work mode, fit/viability score, approve/decline controls. | 1 |
| FR-DIG-4 | MUST | Brief "why this role was suggested" rationale. | 1 |
| FR-DIG-5 | MUST | Decline-with-feedback free-text feeding FR-LEARN and next-run criteria. | 1 |
| FR-DIG-6 | SHOULD | On an empty day, still send a short "no new matches; here's what I searched and why" note. | 1 |

### FR-FB — Feedback & confirmation (§3.6)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-FB-1 | MUST | Decline-with-feedback mandatory, tunes next run per campaign. | 1 |
| FR-FB-2 | MUST | Feedback also via free-text/chat any time and via guided survey. | 1 |
| FR-FB-3 | MUST | Integral change (core attribute/criterion) requires explicit user confirmation; non-integral may auto-apply. | 0 (rule), 1 (UI) |

### FR-ATTR — Attribute / alias / value store (§3.7)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-ATTR-1 | MUST | Dynamic per-campaign cloud of attributes→values, each with aliases. | 1 |
| FR-ATTR-2 | MUST | Each attribute/alias binds to a specific form field for pre-fill; mapping knowledge may be shared, values per-campaign. | 1 (used in 2) |
| FR-ATTR-3 | MUST | UI-editable and feedback-editable (FR-FB-3); auto-updated by FR-LEARN-4. | 1 |
| FR-ATTR-4 | MUST | Dynamic — AI may add attributes as applications require. | 1 |
| FR-ATTR-5 | MUST | Missing-attribute during pre-fill → soft error; acquired detail stored and reused per campaign. | 2 |
| FR-ATTR-6 | MUST | Sensitive EEO/demographic fields filled only from explicit stored answers, never AI-guessed; default "decline to self-identify". | 0 (rule), 2 (fill) |

### FR-ONBOARD — Onboarding intake (§3.8)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-ONBOARD-1 | MUST | Onboarding gathers a comprehensive Workday-ready profile from the start (identity, work-auth, history, education, EEO, base resume, criteria). | 0 |
| FR-ONBOARD-2 | MUST | Interview persistent/resumable across steps; MUST complete before any automated work begins. | 0 |
| FR-ONBOARD-3 | MUST | Bootstrap attribute cloud by parsing the uploaded base resume; reconcile with interview answers. | 0 |

### FR-OOBE — Out-of-box setup & zero-CLI (§3.9)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-OOBE-1 | MUST | After install all configuration is via UI in a logical order; no CLI for any setup once reachable. | 0 |
| FR-OOBE-2 | MUST | Wizard sequences: LLM → notification channels → font management → Workday-ready intake; steps light up as backends land. | 0 (framework), 1 (channels) |
| FR-OOBE-3 | MUST | Notifications/digest can't function until channels configured; wizard gates automated work on channel setup. | 1 |
| FR-OOBE-4 | SHOULD | In-settings Update button invokes the update script (FR-INSTALL-2). | 4 |

### FR-FONT — Font management (§3.10)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-FONT-1 | MUST | Font upload/management with feedback; on base-resume upload detect required fonts and prompt for missing ones. | 0 |
| FR-FONT-2 | MUST | Uploaded fonts installed into conversion env and font cache refreshed at runtime (no rebuild). | 0 (flow), 3 (render use) |

### FR-PREFILL — Browser pre-fill & ATS strategy (§3.11)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-PREFILL-1 | MUST | On approval, spin up an isolated browser sandbox on the host (FR-SANDBOX). | 2 |
| FR-PREFILL-2 | MUST | Pre-fill every fillable field on every page of every ATS incl. account-creation + screening questions; Workday from the start; ATS adapter abstraction. | 2 |
| FR-PREFILL-3 | MUST | Map attributes/aliases to detected fields; escalate ambiguous mapping to LLM or soft-error; sensitive fields per FR-ATTR-6. | 2 |
| FR-PREFILL-4 | MUST | Stop/hand off at irreducible human steps (CAPTCHA, email/SMS verify, final submit); pre-fill account form but never click account-creating submit; notify with VNC. | 2 |
| FR-PREFILL-5 | MUST | At final submit, user submits in live session or authorizes engine to click (friction-free); user completes any CAPTCHA/verification. | 2 |
| FR-PREFILL-6 | MUST | Cautious mode: on detection signals checkpoint, pause, notify with live-session handoff; never bypass/solve a CAPTCHA. | 2 |
| FR-PREFILL-7 | MUST | Data-handoff mode is emergency-only (copy/paste) offered only after the agent reports a fill failure; never default. | 2 |

### FR-RESUME — Resume, cover letter generation (§3.12)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-RESUME-1 | MUST | Engine MAY decide a resume adaptation and/or cover letter is needed for a role. | 3 |
| FR-RESUME-2 | MUST | Truthfulness hard guardrail: reframe real experience, never fabricate; fit-scorer is coverage check not a target. | 0 (rule), 3 (impl) |
| FR-RESUME-3 | MUST | Pluggable ResumeTailoring port: LaTeX primary (auto-converted docx→moderncv banking), docx-XML fallback; page-fit check. | 3 |
| FR-RESUME-3a | MUST | Onboarding conversion preview & accept/reject gate selects per-campaign engine (LaTeX vs docx), switchable later. | 0 (gate), 3 (engine) |
| FR-RESUME-4 | MUST | Output fidelity: xelatex/lualatex+fontspec embedded PDF, or docx→PDF/docx upload; compile-and-visually-inspect fidelity check guards every artifact. | 3 |
| FR-RESUME-5 | MUST | Non-AI-looking: em-dashes forbidden/stripped by deterministic post-filter; banned-phrase list + voice-matching on every revision pass. | 0 (post-filter rule), 3 (impl) |
| FR-RESUME-6 | MUST | Variant library & lineage: forked, scored against JD, stored/reused/re-forked; only approved variants become parents; cluster/cap sprawl. | 3 |
| FR-RESUME-7 | MUST | Selection & generation: score variants locally vs JD; reuse if above threshold else choose best parent + generate adaptation; budget 1 pass + ≤2 refinements. | 3 |
| FR-RESUME-8 | MUST | Interactive review/revision: redline with add+subtract highlights; add/subtract/free-text loop; no submission until approved; default bundled into final-submit gate. | 3 |
| FR-RESUME-9 | MUST | Aggressiveness/tuning control built but grayed out now; ship a stub spec (scaffold-and-gray). | 3 (stub), 4 (backlog) |
| FR-RESUME-10 | MUST | Cover letters on demand; same truthfulness/non-AI/review rules; plain text default, active engine for attachments. | 3 |

### FR-ANSWER — Screening-answer generation (§3.12)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-ANSWER-1 | MUST | Factual screening questions fill from attributes; essay-style generated in user's voice and routed through the FR-RESUME-8 review gate; never auto-submitted. | 3 |

### FR-SANDBOX — Sandbox + remote view/takeover (§3.13)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-SANDBOX-1 | MUST | Each active application runs in an isolated browser sandbox on the host. | 2 |
| FR-SANDBOX-2 | MUST | One-click live remote session (Neko/WebRTC default); remote-view provider is its own swappable sub-port. | 2 |
| FR-SANDBOX-3 | MUST | From live session, user submits themselves or authorizes the engine to finish (FR-PREFILL-5). | 2 |
| FR-SANDBOX-4 | MUST | Multi-session, independently controllable, ephemeral per application. | 2 |

### FR-STEALTH — Cautious mode, fingerprint, egress (§3.14)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-STEALTH-1 | MUST | Coherent honest browser identity (consistent UA/locale/timezone/resolution/WebGL); patchright to remove automation tells. | 2 |
| FR-STEALTH-2 | MUST | Human-like interaction: timing, typing cadence, mouse, scroll, jitter within/across sessions. | 2 |
| FR-STEALTH-3 | MUST | Persistent per-site/tenant browser profile so user appears as a returning real user. | 2 |
| FR-STEALTH-4 | MUST | Egress via the user's residential connection; never datacenter exit; Tailscale later. | 2 |
| FR-STEALTH-5 | MUST | Honest UX caveat: anti-detection best-effort; user performing irreducible steps is the strongest legitimacy lever. | 2 |

### FR-DUR — Durable orchestration (§3.15)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-DUR-1 | MUST | Mid-step crash resumption from day one; resume from last completed step, no lost long-running work. | 0 |
| FR-DUR-2 | MUST | Agent runs 24/7, queuing and processing approvals continuously. | 0 (backbone), 2 (queues) |
| FR-DUR-3 | MUST | DBOS Transact chosen: app=durable workflow, idempotent steps checkpointed; queues for concurrency/rate-limit; send/recv for gates; scheduling for cron. | 0 |
| FR-DUR-4 | MUST | Pivot-around-blocker (FR-AGENT-6). | 0 (rule), 2 (live) |

### FR-LOG — Application logging & conversion capture (§3.16)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-LOG-1 | MUST | On completion log every detail: attributes/values used, variant, role/title/work mode, root application URL. | 2 |
| FR-LOG-2 | MUST | Archive per-page screenshots of each pre-filled page. | 2 |
| FR-LOG-3 | MUST | All logged data retrievable via a UI. | 2 (capture), 4 (history UI) |
| FR-LOG-4 | MUST | Auto-detect final submission in the controlled session; one-tap "mark submitted" fallback; events feed FR-LEARN-2. | 2 |

### FR-AGENT — Agent behavior (§3.17)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-AGENT-1 | MUST | Tunable throughput (~15/day default, hard cap 30/day, fully tunable). | 1 |
| FR-AGENT-2 | MUST | Run modes: 24/7 continuous, fixed duration, or until N viable roles — selectable. | 1 |
| FR-AGENT-3 | MUST | Viability scoring from the JD (roles the user could reasonably get); distinct from resume-fit scorer. | 1 |
| FR-AGENT-4 | MUST | On any question, pause and notify, hold for input. | 0 (rule), 1 (live) |
| FR-AGENT-5 | MUST | Never continue on an uncertain response. | 0 (rule) |
| FR-AGENT-6 | MUST | Pivot around blockers. | 0 (rule), 2 (live) |
| FR-AGENT-7 | MUST | Each run logs a single sentence about what it intends to do next. | 1 |

### FR-NOTIF — Notifications & approval ladder (§3.18)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-NOTIF-1 | MUST | Channels: Discord (primary, one-click), web UI, email via Apprise; extensible; configured in setup wizard. | 1 |
| FR-NOTIF-2 | MUST | Escalation ladder: hold Discord push 30s; in-app if user verifiably present; email after 15-min (configurable) timeout. | 1 (digest), 2 (final-approval) |
| FR-NOTIF-3 | MUST | Idempotency: acting on one channel expires/no-ops the others. | 1 |
| FR-NOTIF-4 | MUST | Document/answer-review notifications link to the redline surface; one-click approve only after viewing. | 3 |
| FR-NOTIF-5 | MUST | Errors surface immediately any hour; approvals/digests MAY respect optional quiet hours unless 24/7. | 1 |

### FR-UI — UI, pending-actions portal & tool toggles (§3.19)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-UI-1 | MUST | Pixel-perfect Applicant clone: vendor its static/ verbatim (MIT notice preserved), served from FastAPI, wired to our APIs; extensible. | 0 |
| FR-UI-2 | MUST | Unwired surfaces grayed out but present; produce a Dormant Surface Wiring Backlog (one stub spec each); no dead UI shipped as live. | 0 (shell), 4 (backlog) |
| FR-UI-3 | MUST | Pending-actions portal: primary surface listing everything awaiting user input, each actionable. | 1 |
| FR-UI-4 | MUST | Many agent tools toggled on/off in UI; initial registry (Discovery, Scoring, Pre-fill, ... Notifications). | 4 |
| FR-UI-5 | MUST | First UI deliverable = setup wizard beginning with the LLM-settings gate, gating features until configured. | 0 |
| FR-UI-6 | MUST | UI exposes criteria editing, attribute-cloud editor, history retrieval, variant library + redline surface, debug surface, chatbot, onboarding wizard, Update button. | 1-4 (spans) |

### FR-CHAT — Chatbot (§3.20)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-CHAT-1 | MUST | Dynamic chatbot assists input, identifies gaps, updates attributes/criteria (subject to FR-FB-3). | 4 |

### FR-VAULT — Credential vault (§3.21)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-VAULT-1 | MUST | CredentialStorePort with default encrypted-Postgres adapter (libsodium, per-tenant); Vaultwarden later. | 2 |
| FR-VAULT-2 | MUST | Both banking modes: manual entry in vault UI (preferred) and auto-capture during human account-creation in live session. | 2 |
| FR-VAULT-3 | MUST | Master key is a strict-permission key-file on disk (clean unattended restart); secrets never logged. | 2 |

### FR-OBS — Observability / debugging (§3.22)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-OBS-1 | MUST | structlog (JSON prod / pretty dev) with per-run/per-application correlation IDs, secret redaction; DBOS OTel traces/metrics. | 0 |
| FR-OBS-2 | MUST | Dedicated debug surface: inspect logs, per-page screenshots, per-application history, durable-workflow state. | 4 |

### FR-INSTALL — Install & update (§3.23)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| FR-INSTALL-1 | MUST | One-liner install script (Proxmox-helper style) → Proxmox VM; editable defaults, root password preset, auto-import SSH keys. | 4 |
| FR-INSTALL-2 | MUST | Matching one-liner update script: backs up DB, runs migrations, supports rollback; invokable via in-UI Update button. | 4 |
| FR-INSTALL-3 | MUST | Ships whole stack (FastAPI+frontend, Postgres+DBOS, SearXNG, Apprise, on-demand Neko, font-install) in the VM via Docker Compose. | 4 |

## Non-functional requirements (§4)

| ID | Priority | One-line summary | Phase |
|---|---|---|---|
| NFR-LOCAL-1 | MUST | Everything local on Proxmox; embeddings local; LLM may be cloud or local; supports fully-local; only optional paid service is cloud LLM. | 0 |
| NFR-TOKEN-1 | MUST | Three-layer frugality: zero-token discovery+local scoring, deterministic pre-fill, LLM only for generation/ambiguous-mapping/reasoning; cheap default, escalate. | 0-3 (spans) |
| NFR-247-1 | MUST | 24/7, accessible any time, durable mid-step resumption. | 0 |
| NFR-CAUTION-1 | MUST | Pre-fill maximally; stop at irreducible human steps; pause-and-notify on detection; data-handoff emergency-only. | 2 |
| NFR-EXT-1 | MUST | Extensible across sources, ATS adapters, tools, models, channels, UI surfaces, and to multi-campaign. | 0 (rule), 4 (verify) |
| NFR-ARCH-1 | MUST | Hexagonal + BDD + TDD. | 0 |
| NFR-ZEROCLI-1 | MUST | No logical setup/config/update step requires the command line after install. | 0 (rule), 4 (update) |
| NFR-PRIV-1 | SHOULD | Banked credentials and PII encrypted at rest; PII to cloud LLM only when a step requires it (opt-in), default minimal. | 2 |
| NFR-TRUTH-1 | MUST | No fabricated content in any generated application material. | 0 (rule), 3 (impl) |

## Summary counts

- FR families: LLM (6), DISC (6), CRIT (4), LEARN (7), DIG (6), FB (3), ATTR (6), ONBOARD (3), OOBE (4), FONT (2), PREFILL (7), RESUME (11 incl. 3a), ANSWER (1), SANDBOX (4), STEALTH (5), DUR (4), LOG (4), AGENT (7), NOTIF (5), UI (6), CHAT (1), VAULT (3), OBS (2), INSTALL (3).
- NFR: 9.
- Total enumerated IDs: 110 functional + 9 non-functional = **119**.
