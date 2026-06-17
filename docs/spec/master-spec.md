# Autonomous Job-Application Engine — Master Build Specification

**Status:** Consolidated v4.4 (LaTeX-primary resume; cloud/local LLM with tiered escalation ladder) — the single source of truth for Claude Code.
**Supersedes:** all prior drafts. Hand Claude Code *only* this file.
**Codename:** **Applicant** (placeholder — rename cascades everywhere).
**Engineering mandate:** Claude Code builds this via implementer sub-agents using **hexagonal (ports-and-adapters) architecture, BDD, and TDD**. Every sub-agent spec cites the requirement IDs it satisfies; every BDD scenario maps to ≥1 ID; any new ambiguity is added to §12 with a recommended default, never silently decided.

Priority language: **MUST** = non-negotiable. **SHOULD** = strong recommendation; deviate only with rationale. **MAY** = optional/forward-looking.

---

## Reconciliation note (front door & UI vendoring)

> **Binding requirements below are unchanged.** This note records where the *as-built*
> system differs from this spec's original implementation assumptions, so the spec stays
> truthful (NFR-TRUTH spirit) without re-litigating requirements. It corrects facts only.
>
> 1. **The front door is the owner's vendored workspace app, white-labeled — not a clone of
>    a third-party "applicant" repo.** §5/§5.1 instruct cloning and vendoring an external UI
>    repo (`github.com/pewdiepie-archdaemon/applicant`) and serving its `static/` from the
>    engine's FastAPI. **As built, the operator UI is the owner's own no-build *workspace*
>    web app** (`workspace/`), white-labeled as Applicant, running as a **separate public
>    service** (`applicant-ui` on `${APP_PORT}` → container 7000) in front of the engine.
>    Read FR-UI-1's "vendor its `static/`, served from our FastAPI backend, wired to our
>    APIs" as satisfied by **vendoring/white-labeling the owner's workspace app** and wiring
>    it to the engine through the bridge — not by an engine-served clone of an external repo.
>    The external repo is not used; the engine serves no operator UI. See
>    [architecture.md](../architecture.md) and [frontend.md](../frontend.md). (The UI-license
>    reconciliation is logged in [open-items.md](../open-items.md).)
> 2. **The engine and the UI are two apps joined by a bridge.** The UI reaches the engine
>    via `workspace/src/applicant_engine.py` (`ENGINE_URL`); the engine reaches back via the
>    token-gated internal channel (`workspace/routes/applicant_internal_routes.py`,
>    `APPLICANT_INTERNAL_TOKEN`). Where §3.19/§6 say "the UI/frontend", read it as the
>    workspace front door proxying the engine's internal routers.
> 3. **Remote-view default is the configurable webtop full desktop**
>    (`REMOTE_VIEW_BACKEND=webtop`), with Neko (browser-only) and noVNC selectable behind
>    the swappable RemoteView sub-port. §3.13/§5 name Neko as the default; treat that as one
>    selectable backend, not the only one. The requirement (one-click live session, swappable
>    sub-port) is unchanged.
> 4. **Removed features.** Home Assistant, awareness/proactive behavior, and a
>    "Nobody"/incognito mode are **not** part of the product. They are not in this spec and
>    must not be documented as present.

---

## 1. Vision

A self-hosted engine that runs 24/7 on a Proxmox VM and conducts ongoing, per-campaign **job-search campaigns**. It agentically discovers postings matching evolving, human-editable, self-learning criteria; delivers a daily **digest** the user approves/declines with feedback; and for approved roles, **pre-fills as much of every application as is technically possible** — including account-creation forms and in-form screening questions — stopping only at irreducible human steps (CAPTCHA, email/SMS verification, final submit), which the user completes via a one-click live remote session. When a role warrants it, the engine **adapts the user's resume, writes a cover letter, and drafts answers to free-text screening questions**, all of which the user **reviews and revises interactively, and must approve, before any submission**. Everything is logged; the system **learns real conversion** (approval + submission) per campaign and optimizes future discovery and document selection accordingly. Architectural template: OpenHands' runtime pattern — local agent loop, cloud LLM via API key, execution isolation behind a swappable boundary.

---

## 2. Architectural principles (binding)

| Principle | Statement |
|---|---|
| Hexagonal | Pure core domain, no I/O; all external concerns are ports with swappable adapters. |
| BDD / TDD | Gherkin features mapped to requirement IDs drive implementation; failing test first. |
| Local-first, LLM cloud-or-local | Everything runs on Proxmox; embeddings run locally. LLM reasoning is the one component that may be **cloud** (OpenAI-compatible API) **or local** (network Ollama) — user's choice; the system can run fully local. No paid external service except an optional cloud LLM. |
| Durable execution | Mid-step crash resumption from day one via a lightweight Postgres-backed library (no separate server). |
| Token frugality | LLM is the last resort. Zero-token discovery + local scoring; LLM only for generation, ambiguous mapping, and reasoning. |
| Maximal pre-fill | Pre-fill every fillable field on every page of every ATS; never cut corners; stop only at irreducible human steps. |
| Human-in-the-loop | On any uncertainty, detection signal, missing attribute, or generated material — pause and notify; never guess; never auto-submit generated material without approval. |
| Pivot, don't block | One blocked/awaiting application never stalls unrelated work. |
| Truthfulness | Resume/cover-letter/answer adaptation reframes real experience; it never fabricates. |
| Zero-CLI operation | All setup, configuration, and updates happen through the UI; nothing logical requires a command line after install. |
| Campaign-scoped, multi-ready | Everything is campaign-scoped from day one; MVP-1 runs a single campaign but the data model and architecture make multi-campaign drop-in without rework. |
| Scaffold-and-gray | When a future control or surface isn't ready to be conceptualized or wired, build it visually, gray it out, and leave a stub spec to complete it later. |
| Extensibility | New discovery sources, ATS adapters, tools, models, channels, and UI surfaces add via adapters without core changes. |

---

## 3. Functional requirements

### 3.1 LLM / model access — `FR-LLM`
- **FR-LLM-1 (MUST — provider-agnostic, cloud or local):** The LLM port accepts **either** an OpenAI-compatible **cloud API** (OpenRouter → DeepSeek V4 Flash/Pro) **or** a **local/network Ollama endpoint** (e.g., `http://<gpu-host>:11434` or a Caddy HTTPS endpoint), **or both**. Both speak the OpenAI-compatible chat-completions API, so a configurable **base URL + optional key** covers all cases. Applicant's settings already expose the local-vs-API provider toggle (reused). The system can run **fully local** (no cloud dependency) if only Ollama is configured.
- **FR-LLM-2 (MUST):** When a provider is configured, **auto-populate the model list** from it — OpenRouter's catalog for cloud, the Ollama host's installed models (`/v1/models` or `/api/tags`) for local. Provider/model/endpoint/key are settable (when none is set) and editable later **through the UI** as part of the out-of-box setup (`FR-OOBE`).
- **FR-LLM-3 (MUST — tiered escalation ladder):** Instead of a fixed default/escalation pair, the user configures an **ordered, capability-ranked ladder of model tiers** (Level 1 → Level 2 → … → Level N) in the settings UI. **Each tier is assigned any model from any configured provider** — local Ollama or remote API — so tiers can mix local and cloud freely. The **user defines the order** (the system does not infer "intelligence"; the ranking is the user's assertion). Default example ladder: **L1 = Qwen ~27B (local), L2 = DeepSeek V4 Flash (cloud), L3 = DeepSeek V4 Pro (cloud)**. The ladder is reorderable and tiers can be added/removed (default 3, minimum 1). The UI MAY present this as a drag-to-rank stack or explicit Level slots — either is fine as long as the result is one ordered ladder (position = level).
- **FR-LLM-4 (MUST — escalation = climbing the ladder):** Work starts at the **lowest sufficient tier** and **climbs to a higher tier** when needed. Triggers: **low confidence** at the current tier; **context overflow** (the task exceeds the current tier's context window — climb to the next tier whose model has *sufficient context*, not blindly +1); and configurable **per-task-type starting tiers** (default: scoring and ambiguous field-mapping start above L1). The **top tier is the ceiling**: if even it cannot satisfy the need (e.g., context still overflows), handle gracefully and surface to the user rather than failing silently. For meaningful capability escalation the ladder should include at least one cloud tier near the top — a purely-local ladder is bounded by the GPU (~27B-class, ~72K context on a 2080 Ti 22GB).
- **FR-LLM-4a (MUST — model-capability variance):** The adapter MUST be robust to models that differ in native function-calling / JSON-mode / structured-output support and context size: parse/validate outputs defensively, fall back to prompt-based structured output where a model lacks native tool-calling, and never send a prompt exceeding the active model's context window (`FR-LLM-4`).
- **FR-LLM-5 (MUST):** Minimize tokens per `NFR-TOKEN-1`. With a local default, routine work is effectively free and private; only escalations incur cloud cost.

### 3.2 Discovery & pluggable sources — `FR-DISC`
- **FR-DISC-1 (MUST):** Agentically scan the internet on a schedule to gather postings.
- **FR-DISC-2 (MUST):** A **master aggregator over the easy sources** is built in **wave one** (JobSpy boards: LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter/etc.). Discovery sources are a **pluggable, user-selectable set** (toggle on/off in the UI) and **extensible** — new per-platform aggregation modules add as adapters without core changes (the user will brainstorm and add more later).
- **FR-DISC-3 (MUST):** Per-posting normalization: title, company, location, work mode (remote/hybrid/onsite), salary (if available), source URL, full description.
- **FR-DISC-4 (MUST):** Gather as much sensible data as possible; structured scraping and metasearch incur **zero LLM tokens**.
- **FR-DISC-5 (MUST):** **Source-yield learning** — track per-source effectiveness (matches → approvals → submissions) and reweight toward high-yield sources, down-weighting low-yield ones, with a learned **exploration budget** that periodically tries new/under-used sources and role-types.
- **FR-DISC-6 (SHOULD):** Hostile boards (LinkedIn/Indeed) throttle high-volume scraping from one residential IP (JobSpy notes LinkedIn needs proxies). Start with the easy sources; design a pluggable proxy hook for later without committing to a proxy now.

### 3.3 Search criteria & campaign scope — `FR-CRIT`
- **FR-CRIT-1 (MUST):** Criteria are dynamic, exploratory, and self-learning **per campaign**.
- **FR-CRIT-2 (MUST):** Criteria stay human-readable and UI-editable at all times; learned adjustments are surfaced transparently and overridable.
- **FR-CRIT-3 (MUST):** Mutable by the LLM (via learning/feedback) and directly by the user.
- **FR-CRIT-4 (MUST):** **Everything is campaign-scoped** — criteria, the attribute/answer cloud (`FR-ATTR`), the base resume and variants (`FR-RESUME`), credentials, learning state. MVP-1 runs **one** campaign; the model and ports MUST be campaign-scoped so multi-campaign (incl. cloning a campaign's setup) drops in later without rework. Concurrent campaigns are not required out of the gate.

### 3.4 Learning & optimization engine — `FR-LEARN` (first-class subsystem)
- **FR-LEARN-1 (MUST):** Learning is **per campaign**.
- **FR-LEARN-2 (MUST):** **Conversion** = **approval taste + final submission**. The engine learns *real conversion*, not only approval taste.
- **FR-LEARN-3 (MUST):** Learn from **every input**: digest approvals/declines (incl. decline feedback), final submissions, the user's resume/career data, chat, guided surveys, resume/answer-revision feedback, and all feedback from any direction.
- **FR-LEARN-4 (MUST):** Parsed input is **cross-referenced with the campaign's attribute cloud to keep it up to date** (auto-apply non-integral updates; integral changes require confirmation per `FR-FB-3`).
- **FR-LEARN-5 (MUST):** Learn the **signature of converting roles** and bias future discovery + scoring + resume-variant selection toward it.
- **FR-LEARN-6 (MUST):** Include the **exploration budget** (`FR-DISC-5`).
- **FR-LEARN-7 (SHOULD):** Keep learning cheap — statistical/local-embedding based; reserve the LLM for human-readable criteria summaries.

### 3.5 Daily digest — `FR-DIG`
- **FR-DIG-1 (MUST):** Produce a daily digest per campaign when matches are aggregated.
- **FR-DIG-2 (MUST):** Delivery is **email/webpage + a Discord notification that it's ready**. The digest is **exempt from the Applicant visual style**.
- **FR-DIG-3 (MUST):** Table, one row per role: brief summary, link to posting, work mode, fit/viability score, and **approve / decline** controls.
- **FR-DIG-4 (MUST):** Brief **"why this role was suggested"** rationale.
- **FR-DIG-5 (MUST):** **Decline-with-feedback** free-text, feeding `FR-LEARN` and next-run criteria.
- **FR-DIG-6 (SHOULD):** On an empty day, still send a short "no new matches; here's what I searched and why" note.

### 3.6 Feedback & confirmation — `FR-FB`
- **FR-FB-1 (MUST):** Decline-with-feedback is mandatory and tunes the next run per campaign.
- **FR-FB-2 (MUST):** Feedback also arrives via free-text/chat at any time and via guided survey.
- **FR-FB-3 (MUST):** Any **integral change** (core attribute value or core criterion) requires **explicit user confirmation** before commit. Non-integral updates may auto-apply.

### 3.7 Attribute / alias / value store (per campaign) — `FR-ATTR`
- **FR-ATTR-1 (MUST):** A dynamic, **per-campaign** cloud of attributes → values, each with aliases.
- **FR-ATTR-2 (MUST):** Each attribute/alias binds to a specific application form field for pre-fill. (ATS field-mapping knowledge may be learned/shared across campaigns, but values are per-campaign.)
- **FR-ATTR-3 (MUST):** UI-editable and feedback-editable (subject to `FR-FB-3`); auto-updated by `FR-LEARN-4`.
- **FR-ATTR-4 (MUST):** Dynamic — the AI may add attributes as applications require.
- **FR-ATTR-5 (MUST):** Missing-attribute during pre-fill → soft error to the user for detail; acquired detail is stored and reused for future applications in that campaign.
- **FR-ATTR-6 (MUST — sensitive fields):** Demographic / EEO / voluntary self-identification fields (race, gender, veteran, disability) are filled **only from the user's explicit stored answers, never AI-guessed**, defaulting to "decline to self-identify" unless the user sets otherwise.

### 3.8 Onboarding (Workday-ready intake) — `FR-ONBOARD`
- **FR-ONBOARD-1 (MUST):** The onboarding interview gathers a **comprehensive, Workday-ready** profile **from the very beginning**: identity/contact, work authorization, location & remote/work-mode preferences, target roles/titles, salary floor, full **work history with dates**, education, references, key attributes, the user's explicit EEO answers, the base resume, and initial campaign criteria — enough to complete a Workday application with minimal soft-error interruptions.
- **FR-ONBOARD-2 (MUST):** The interview is **persistent and resumable across steps** and **MUST be completed before any automated work begins**.
- **FR-ONBOARD-3 (MUST):** Bootstrap the campaign attribute cloud by parsing the uploaded base resume; reconcile parsed data with interview answers.

### 3.9 Out-of-box setup & zero-CLI operation — `FR-OOBE`
- **FR-OOBE-1 (MUST):** After install, **all configuration happens through the UI in a logical order** — there is **no reliance on the command line** for any setup once the product is installed and reachable.
- **FR-OOBE-2 (MUST):** The setup wizard sequences, at minimum: (1) **LLM** provider/model/key (`FR-LLM-2`); (2) **notification channels** — Discord bot token + invite, email/SMTP, and any others (`FR-NOTIF`); (3) **font upload/management** for resume fidelity (`FR-FONT`); (4) the **Workday-ready onboarding intake** (`FR-ONBOARD`). Steps light up as their backends land but the wizard framework and ordering are first-class.
- **FR-OOBE-3 (MUST):** Notifications and the digest/approval flow **cannot function until channels are configured**; the wizard treats channel setup as a gating step before automated work.
- **FR-OOBE-4 (SHOULD):** An in-settings **Update button** invokes the update script (`FR-INSTALL-2`) so updates don't require SSH/CLI either.

### 3.10 Font management — `FR-FONT`
- **FR-FONT-1 (MUST):** Provide a **font upload/management flow with system feedback** so the rendering/conversion environment has the exact fonts the base resume uses (e.g., Segoe UI). On base-resume upload, **detect required fonts and prompt the user to upload any that are missing**, confirming once installed.
- **FR-FONT-2 (MUST):** Uploaded fonts are installed into the conversion environment and the font cache refreshed at runtime (no rebuild).

### 3.11 Browser pre-fill & ATS strategy — `FR-PREFILL`
- **FR-PREFILL-1 (MUST):** On approval, spin up an isolated browser sandbox on the host (`FR-SANDBOX`).
- **FR-PREFILL-2 (MUST — standard set at Workday):** **Pre-fill every fillable field on every page of every ATS**, including **account-creation forms** and **in-form screening questions** (`FR-ANSWER`). Never cut corners on any ATS software. MVP-1 MUST work on **Workday** from the start; the ATS layer is an adapter abstraction so others follow.
- **FR-PREFILL-3 (MUST):** Use the campaign attribute cloud, mapping attributes/aliases to detected fields; escalate ambiguous mappings to the LLM (or soft-error to the user). Sensitive fields per `FR-ATTR-6`.
- **FR-PREFILL-4 (MUST — irreducible-human-step boundary):** The engine **stops and hands off** at any step only a human can do: CAPTCHA, email/SMS verification, and the **final submit**. It pre-fills account-creation forms but does **not** click the account-creating submit; it notifies with a VNC link and the user presses it and completes verification.
- **FR-PREFILL-5 (MUST):** At the job application's final-submit step, the user may **submit themselves in the live session** or **authorize the engine to click final submit** (friction-free cases). Where a CAPTCHA or verification intervenes, the user completes it.
- **FR-PREFILL-6 (MUST):** **Cautious mode** — on automation-detection signals (CAPTCHA/Turnstile, Cloudflare/DataDome interstitials, 403/429, anomalous redirects, account-creation friction), checkpoint, pause, and notify with the live-session handoff. Never bypass or solve a CAPTCHA.
- **FR-PREFILL-7 (MUST):** **Data-handoff mode is emergency-only** — copy/paste of pre-filled values into the user's own browser is offered **only** when the agent reports it tried to fill the form and failed. Never the default.

### 3.12 Resume, cover letter & screening-answer generation — `FR-RESUME` / `FR-ANSWER` (first-class subsystem)
- **FR-RESUME-1 (MUST):** The engine MAY decide a resume adaptation and/or a cover letter is needed for a given role.
- **FR-RESUME-2 (MUST — truthfulness, hard guardrail):** Adaptation **reframes, reorders, re-emphasizes, and re-terms real experience** and surfaces relevant true history. It **never fabricates** qualifications, titles, dates, or skills. The fit-scorer is a *coverage* check, not a target to game.
- **FR-RESUME-3 (MUST — rendering engine: LaTeX primary, docx fallback, pluggable):** The resume renderer is **pluggable behind the `ResumeTailoring` port**, with two engines selected **per campaign at onboarding**:
  - **LaTeX (primary):** the user's uploaded base resume is **auto-converted** (content extracted from the docx — the user never hand-authors `.tex`) into a **proven LaTeX template** — moderncv "banking" style by default (the template the user's own repo already produces); the system MAY additionally attempt an AI-generated custom class approximating the base design. Variants/revisions are generated by editing the **LaTeX source** (plain text → trivial diffing for the redline). **Content fidelity (nothing dropped) is guaranteed; design fidelity is the user's judgment via the accept/fallback gate (`FR-RESUME-3a`).**
  - **docx (fallback):** if the converted LaTeX look is not accepted, the engine edits the **uploaded docx's OOXML (`document.xml`)** in place — preserving run properties, fonts, and layout, cloning bullet/run nodes when adding/removing — anchored to the base XML template.
  - Either engine runs a **page-fit check**; overflow surfaces as a soft error.
- **FR-RESUME-3a (MUST — conversion preview & selection at onboarding):** During onboarding, after the base resume is uploaded and fonts resolved (`FR-FONT`), the system **compiles the LaTeX conversion and presents it for the user to accept** (LaTeX becomes the campaign's primary engine) **or reject** (fall back to the docx engine on the uploaded docx, or whatever the user uploads). The choice is a per-campaign setting and MAY be switchable later.
- **FR-RESUME-4 (MUST — output fidelity):** The final artifact must **upload correctly and look correct**. **LaTeX engine:** compile with **xelatex/lualatex + fontspec** (fonts embedded natively) to PDF — deterministic, no rendering drift. **docx engine:** **docx→PDF with embedded fonts** or **docx upload** — whichever the ATS field accepts. Both depend on `FR-FONT` for the build environment's fonts. A **fidelity check (compile + visually inspect the rendered output, exact page count, no orphaned section titles — "looks fine in source is not acceptable")** guards every artifact before review.
- **FR-RESUME-5 (MUST — non-AI-looking):** Output must be intentionally non-AI-looking. **Em dashes are forbidden** and stripped/replaced by a **deterministic post-filter** (not left to the model); en-dashes used as em are normalized. A UI-editable banned-phrase list and **voice-matching to the user's own resume corpus** constrain generation to sound like the user, on **every revision pass**. (No tool can *guarantee* defeating AI-text detectors; the mandatory human review is the safeguard.)
- **FR-RESUME-6 (MUST — variant library & lineage):** The user provides a base resume at campaign start. Forked variants are created organically by engine decisions, **scored against each JD**, stored, reused, and re-forked. Track lineage. **Only user-approved variants become reusable parents.** Cluster/cap to prevent sprawl.
- **FR-RESUME-7 (MUST — selection & generation):** At the resume-upload step, score existing variants against the JD (cheap/local). If one clears the **fit threshold** (configurable), reuse the best. If **all score below threshold**, **intelligently choose the best parent** and **generate an adaptation that best meets the fit requirements**, then route to review. Budget: one LLM pass + a small bounded number (default 2) of refinements, then hand to the user.
- **FR-RESUME-8 (MUST — interactive review & revision feedback engine):** Any application carrying an **edited resume, generated cover letter, or generated screening answer** MUST go to the user for review **before any submission**, as an **interactive loop, not blind approve/reject**:
  - Documents are presented as a **redline against the base — additions highlighted and subtractions/deletions highlighted**.
  - The user can **add** (free-text instruction), **subtract** (mark content to remove), or give **free-text feedback**. The AI revises in the active engine's source (**LaTeX source** on the primary path — plain text, so the additions/subtractions diff is trivial; the **docx XML** on the fallback path), applies the em-dash filter + truthfulness + voice-matching, re-renders the redline, and repeats.
  - The back-and-forth MUST be **very easy**. Submission is impossible until the user **approves** (the user may approve, decline, or send back with revisions).
  - **Default sequencing:** bundle document approval into the final-submit approval (one stop). Heavy edits MAY trigger an earlier gate. Surface lives in the **main app, Applicant design system** (document-editor aesthetic reusable).
- **FR-RESUME-9 (MUST — aggressiveness / job-getting optimization):** Adaptation optimizes for the **effective potential of getting the job**, within truthfulness (`FR-RESUME-2`) and visual-template/page-fit (`FR-RESUME-3`). A UI **aggressiveness/tuning control** MUST be built but **grayed out** for now; ship a stub spec to complete it later (scaffold-and-gray).
- **FR-RESUME-10 (MUST — cover letters):** Generated on-demand when an application requests/offers one. Same truthfulness, non-AI, review, and revision rules. **Default format:** plain text for paste-in fields; for attached cover letters, the **active engine** — a LaTeX cover class (e.g. the `cover.cls` in the user's repo) on the primary path, or a styled docx matching the resume on the fallback path. A base cover-letter template MAY be supplied; otherwise generate in the user's voice.
- **FR-ANSWER-1 (MUST — screening questions):** For in-application free-text/screening questions: **factual** ones (work authorization, availability, etc.) fill from stored attributes; **essay-style** ones ("Why do you want this role?", "Describe a time when…") get a **high-scoring answer generated in the user's professional voice** (from resume + self-framing), routed through the **same review/revision gate** as cover letters (`FR-RESUME-8`). Never auto-submitted without approval.

### 3.13 Sandbox + remote view/takeover — `FR-SANDBOX`
- **FR-SANDBOX-1 (MUST):** Each active application runs in an isolated browser sandbox on the host.
- **FR-SANDBOX-2 (MUST):** A **one-click live remote session** (Neko/WebRTC default) shows the browser the engine is working in; **the remote-view provider is its own swappable sub-port** (Neko ↔ noVNC ↔ future).
- **FR-SANDBOX-3 (MUST):** From the live session the user can submit themselves or authorize the engine to finish (`FR-PREFILL-5`).
- **FR-SANDBOX-4 (MUST):** Multi-session and independently controllable; ephemeral per application.

### 3.14 Cautious mode, fingerprint normalization & egress — `FR-STEALTH`
- **FR-STEALTH-1 (MUST):** Present a **coherent, honest browser identity** (consistent UA + locale `en-US` + timezone America/Phoenix + realistic resolution + a non-obviously-software WebGL/Canvas renderer; internally consistent — never spoof an OS the WebGL contradicts). Use patchright to remove automation/headless tells.
- **FR-STEALTH-2 (MUST):** **Human-like interaction** — realistic timing, typing cadence, mouse movement, scrolling, jitter, within and across sessions.
- **FR-STEALTH-3 (MUST):** **Persistent per-site/tenant browser profile** so the user appears as a returning real user. (Workday accounts are per-tenant; profiles and credentials multiply across tenants.)
- **FR-STEALTH-4 (MUST):** **Egress via the user's residential connection** (the system runs on the home Proxmox node — a key "looks real" advantage). Do not route automation through a datacenter exit. Tailscale-based access is a later enhancement.
- **FR-STEALTH-5 (MUST):** Honest caveat in UX: anti-detection is best-effort; the strongest legitimacy guarantee is the user personally performing irreducible steps in a real, returning session.

### 3.15 Durable orchestration — `FR-DUR`
- **FR-DUR-1 (MUST):** **Mid-step crash resumption from day one.** A crash resumes from the last completed step; no lost long-running work.
- **FR-DUR-2 (MUST):** The agent runs 24/7, queuing and processing approvals continuously.
- **FR-DUR-3 (MUST — chosen engine: DBOS Transact):** Use **DBOS Transact** (MIT, open-source, free, self-hosted) — a lightweight durable-execution **library** that stores workflow/step state in the **same Postgres we already deploy**, with **no separate orchestration server** (chosen over Temporal, whose self-hosted server is free but operationally heavy; Inngest leans SaaS; Camunda is heavy JVM/BPMN; ZenML is ML-pipeline only). Mapping:
  - **Each application = a durable DBOS workflow;** each small idempotent step (navigate, fill field, screenshot, score, generate) is individually checkpointed → true mid-step resumption.
  - **DBOS durable queues** enforce the **sandbox concurrency cap** and **per-provider LLM rate limiting**.
  - **DBOS `send`/`recv`** implement the **approval gates** and revision-loop hand-offs.
  - **DBOS scheduling** drives cron-like work (digests, discovery). LangGraph is the reasoning loop *within* steps. Restate MAY be evaluated as a lighter alternative; DBOS is the default.
- **FR-DUR-4 (MUST):** Pivot-around-blocker (`FR-AGENT-6`).

### 3.16 Application logging & conversion capture — `FR-LOG`
- **FR-LOG-1 (MUST):** On completion, log every detail: attributes/values used, resume variant used, role name, job title, work mode, link back to the root application URL.
- **FR-LOG-2 (MUST):** Archive **per-page screenshots** of each pre-filled page.
- **FR-LOG-3 (MUST):** All logged data retrievable via a UI.
- **FR-LOG-4 (MUST — submission detection):** Detect final submission **automatically when it occurs in the controlled session** (confirmation-page heuristics). Where it cannot be auto-detected (e.g., emergency data-handoff), provide a **one-tap "mark submitted"** control. (A browser-extension capture is a later option.) Submission events feed `FR-LEARN-2`.

### 3.17 Agent behavior — `FR-AGENT`
- **FR-AGENT-1 (MUST):** Tunable throughput (target ~15/day default, hard cap 30/day, fully tunable).
- **FR-AGENT-2 (MUST):** Run modes: 24/7 continuous, fixed duration, or until N viable roles — selectable.
- **FR-AGENT-3 (MUST):** Viability scoring from the JD: roles the user could reasonably get. *(Distinct from the resume-fit scorer in `FR-RESUME-7`.)*
- **FR-AGENT-4 (MUST):** On any question, pause and notify, hold for input.
- **FR-AGENT-5 (MUST):** Never continue on an uncertain response.
- **FR-AGENT-6 (MUST):** Pivot around blockers.
- **FR-AGENT-7 (MUST):** Each run logs a single sentence about what it intends to do next.

### 3.18 Notifications & approval ladder — `FR-NOTIF`
- **FR-NOTIF-1 (MUST):** Channels: **Discord (primary, one-click), web UI, email** via Apprise; extensible. Configured through the setup wizard (`FR-OOBE-2`).
- **FR-NOTIF-2 (MUST — escalation ladder):** Decision created server-side. **Discord fires always, unless approved on the web portal first; hold the Discord push 30 seconds.** If the user is **verifiably present** in the web UI (focused tab + input activity within ~90s + open socket), surface it in-app. If undecided after **15 minutes (UI-configurable)**, send email.
- **FR-NOTIF-3 (MUST — idempotency):** The same decision on multiple channels is idempotent — acting on one expires/no-ops the others.
- **FR-NOTIF-4 (MUST):** Document/answer-review notifications link to the redline review/revision surface; one-click approve only after viewing.
- **FR-NOTIF-5 (MUST):** All errors surface immediately, any hour. Approvals/digests MAY respect optional quiet hours unless 24/7.

### 3.19 UI, pending-actions portal & tool toggles — `FR-UI`
- **FR-UI-1 (MUST — pixel-perfect clone):** The frontend is a **pixel-by-pixel visual replica of Applicant's design system** (vendor its `static/` — CSS, vanilla JS, fonts, icons — under MIT with notice preserved, served from our FastAPI backend, wired to our APIs). **Exact visual replica for now.** A frontend code refactor is sensible later; the clone MUST be **extensible**.
- **FR-UI-2 (MUST — dormant surfaces):** Surfaces not yet wired are **grayed out, visually present but dormant**. Claude Code produces a **Dormant Surface Wiring Backlog**: one stub spec per surface. No dead UI shipped as if live.
- **FR-UI-3 (MUST — pending-actions portal):** A **primary surface listing everything awaiting the user's input** — digest approvals, document/cover-letter/screening-answer reviews, soft errors, agent questions, and final-submit approvals — each actionable from there. This is the user's home base for the 24/7 queue of pending decisions/actions.
- **FR-UI-4 (MUST):** Many agent tools, **toggled on/off in the UI** (Applicant per-tool pattern). Initial registry: Discovery, Scoring, Pre-fill, Account-Creation, Web-Research, Resume-Tailoring, Cover-Letter-Generation, Screening-Answer-Generation, Chat, Notifications.
- **FR-UI-5 (MUST):** First UI deliverable = the **setup wizard** beginning with the **LLM-settings gate** (`FR-OOBE`, `FR-LLM-2`), gating features until configured.
- **FR-UI-6 (MUST):** UI exposes criteria editing, the attribute-cloud editor, application history retrieval, the resume variant library + redline review/revision surface, the debug surface, the chatbot, the onboarding wizard, and the in-settings Update button.

### 3.20 Chatbot — `FR-CHAT`
- **FR-CHAT-1 (MUST):** A dynamic chatbot assists input and dynamically identifies gaps; can update attributes and criteria (subject to `FR-FB-3`).

### 3.21 Credential vault — `FR-VAULT`
- **FR-VAULT-1 (MUST):** A `CredentialStorePort` with a default **encrypted-Postgres** adapter (per-site/tenant credentials sealed with libsodium); structured for many credential sets (Workday is per-tenant). Vaultwarden adapter is a later option.
- **FR-VAULT-2 (MUST):** Support **both** banking mechanisms: **manual entry in the vault UI (preferred upfront)** and **auto-capture** of credentials entered during a human account-creation in the live session.
- **FR-VAULT-3 (MUST):** Master key is a **key-file with strict permissions** on disk (clean unattended 24/7 restart). Secrets never logged.

### 3.22 Observability / debugging — `FR-OBS`
- **FR-OBS-1 (MUST):** structlog (JSON prod / pretty dev) with per-run/per-application correlation IDs; secret redaction. DBOS emits OTel traces/metrics for workflow visibility.
- **FR-OBS-2 (MUST):** A dedicated debug surface to inspect logs, per-page screenshots, per-application history, and durable-workflow state.

### 3.23 Install & update — `FR-INSTALL`
- **FR-INSTALL-1 (MUST):** A **one-liner install script** on the Proxmox node, Proxmox-VE-helper-script style, targeting a **Proxmox VM** (decided), with default settings as editable variables during install, root password preset, and **auto-import of detectable SSH keys**. After install, all further configuration is via the UI (`FR-OOBE`).
- **FR-INSTALL-2 (MUST):** A matching **one-liner update script** that backs up the DB, runs migrations, and supports rollback — also invokable via the in-settings **Update button** (`FR-OOBE-4`).
- **FR-INSTALL-3 (MUST):** Ships the whole stack (FastAPI app + vendored frontend, Postgres + DBOS, SearXNG, Apprise, on-demand Neko sandboxes, font-install support) inside the VM via Docker Compose.

---

## 4. Non-functional requirements
- **NFR-LOCAL-1 (MUST):** Everything local on Proxmox; embeddings local. LLM reasoning may be **cloud (OpenAI-compatible API) or local (network Ollama)** — the system supports fully-local operation. The only optional paid external service is a cloud LLM (e.g., for escalation).
- **NFR-TOKEN-1 (MUST):** Three-layer frugality: zero-token discovery + local scoring (incl. resume-variant shortlisting); deterministic pre-fill where possible; LLM only for generation, ambiguous mapping, and reasoning. Cheap model default; escalate per `FR-LLM-4`.
- **NFR-247-1 (MUST):** 24/7, accessible at any time, durable mid-step resumption.
- **NFR-CAUTION-1 (MUST):** Pre-fill maximally; stop at irreducible human steps; pause-and-notify on detection; data-handoff emergency-only.
- **NFR-EXT-1 (MUST):** Extensible across sources, ATS adapters, tools, models, channels, UI surfaces, and to multi-campaign.
- **NFR-ARCH-1 (MUST):** Hexagonal + BDD + TDD.
- **NFR-ZEROCLI-1 (MUST):** No logical setup/config/update step requires the command line after install.
- **NFR-PRIV-1 (SHOULD):** Banked credentials and PII encrypted at rest; PII sent to the cloud LLM only when a step requires it (opt-in tailoring), default minimal.
- **NFR-TRUTH-1 (MUST):** No fabricated content in any generated application material.

---

## 5. Recommended stack

| Component | Default | License | Satisfies |
|---|---|---|---|
| Language / runtime | Python 3.11+ | — | all |
| API + web | FastAPI + vendored Applicant `static/` (vanilla HTML5/CSS/JS) | MIT | `FR-UI` |
| Durable execution | **DBOS Transact** (Postgres-backed library, no separate server) | MIT | `FR-DUR` |
| Agent reasoning (within steps) | LangGraph | MIT | `FR-AGENT`, `FR-LEARN` |
| Browser automation | patchright/Playwright | Apache-2.0 | `FR-PREFILL`, `FR-STEALTH` |
| AI browser fallback | browser-use / Skyvern | MIT / AGPL-3.0 | unknown forms |
| Sandbox + remote takeover | Neko + neko-rooms (CDP), swappable | Apache-2.0 | `FR-SANDBOX` |
| Discovery (structured) | JobSpy / python-jobspy (master aggregator) | MIT | `FR-DISC` |
| Discovery (exploratory) | SearXNG (self-hosted) | AGPL-3.0 | `FR-DISC` |
| Database | PostgreSQL + JSONB (also hosts DBOS state) | PostgreSQL | `FR-ATTR`, `FR-LOG`, `FR-DUR` |
| ORM / migrations | SQLAlchemy + Alembic | MIT | persistence |
| Embeddings (dedup, variant scoring, conversion model) | local embedding model | — | `NFR-LOCAL-1` |
| Resume engine | LaTeX (xelatex/lualatex + fontspec, moderncv) primary via auto-converted docx; OOXML docx-XML fallback; redline diff on source (docx skill for fallback) | — | `FR-RESUME`, `FR-FONT` |
| Notifications | Apprise (+ Discord gateway bot) | BSD-2 | `FR-NOTIF` |
| Credential vault | encrypted Postgres (libsodium), key-file master key | — | `FR-VAULT` |
| Logging | structlog (+ DBOS OTel) | MIT/Apache | `FR-OBS` |
| LLM provider | OpenRouter (cloud: DeepSeek V4 Flash/Pro) and/or **network Ollama** (local: Qwen ~27B or other); OpenAI-compatible; **ordered capability-tier ladder** (e.g., L1 local Qwen → L2 DeepSeek Flash → L3 DeepSeek Pro), each tier any provider | — | `FR-LLM` |
| Install/update | Proxmox-helper-script-style one-liner → VM; UI setup + Update button | — | `FR-INSTALL`, `FR-OOBE` |

**Frontend note:** Applicant is MIT, no-build vanilla HTML5/CSS/JS (one ~37k-line `style.css`, ~157 JS modules incl. `windowDrag.js`/`tileManager.js`/`modalManager.js`/`providers.js`/`models.js`/`settings.js`, custom `GohuFont.ttf`). **Clone `https://github.com/pewdiepie-archdaemon/applicant` and vendor its `static/` directory verbatim** for pixel fidelity; new screens (setup wizard, pending-actions portal, resume redline/revision surface) are built with the same CSS classes/components. Dormant surfaces grayed with a wiring-backlog stub each. Digest exempt (separate email/webpage).

---

## 5.1 Reference repositories (clone and consult at the start)

Both are public; clone both before building.

**Applicant — UI source (clone and vendor):** `https://github.com/pewdiepie-archdaemon/applicant` (MIT)
Required for the pixel-perfect UI (`FR-UI-1`). Clone it and **vendor its `static/` directory verbatim** — the ~37k-line `style.css`, the ~157 vanilla JS modules (`windowDrag.js`, `tileManager.js`, `modalManager.js`, `providers.js`, `models.js`, `settings.js`, etc.), fonts incl. `GohuFont.ttf`, and icons. Preserve the MIT notice. Re-point its JS at our FastAPI APIs and build every new screen with the same CSS classes/components so inherited and new surfaces are indistinguishable.

> **As-built (see the [Reconciliation note](#reconciliation-note-front-door--ui-vendoring)):**
> this external repo is **not** used. The operator UI is the owner's own no-build *workspace*
> app (`workspace/`), white-labeled as Applicant and run as a separate public service in
> front of the engine. FR-UI-1 is satisfied by vendoring/white-labeling that workspace app
> and wiring it to the engine through the bridge — not by an engine-served clone.

**`kevinhirsch/ai-job-search` — domain inspiration (consult; do not copy wholesale):** `https://github.com/kevinhirsch/ai-job-search`
A Claude Code job-application workspace (a fork of `MadsLorentzen/ai-job-search`). It is a **manual, CLI-driven document-prep tool, not a model for our autonomous service architecture** — but several artifacts are directly reusable:
- `CLAUDE.md` **candidate-profile schema** (Identity, Education, Experience, Skills, Certifications, Behavioral Profile, Target Sectors, Deal-breakers) → a near-ready template for the Workday-ready onboarding intake (`FR-ONBOARD`) and the campaign attribute cloud (`FR-ATTR`).
- Its **Verification Checklist** (in `CLAUDE.md`) → almost a line-for-line statement of our guardrails: truthfulness (`FR-RESUME-2`: "no fabricated skills/experience/achievements"; independently verify company-specific claims via web before trusting reviewer output) and render-and-inspect fidelity (`FR-RESUME-3/4`: compile, **visually inspect the PDF**, exact page count, no orphaned section titles — "looks fine in source is not acceptable"). Adopt this checklist's rigor for our docx→PDF path.
- The **drafter→reviewer** pipeline and **fit-evaluation-first** workflow → our generate→review→revise loop (`FR-RESUME-8`) and viability scoring (`FR-AGENT-3`).
- `.claude/skills/` (numbered modules incl. `03-writing-style`) and `.claude/commands/` (`setup`, `apply`, `expand`) → idioms for structuring our own Claude-Code-built skills/commands; `03-writing-style` informs voice-matching (`FR-RESUME-5`). `salary_lookup.py` informs salary-floor/desired-salary handling.

**Its LaTeX/moderncv toolchain is now directly relevant** (the resume engine's primary path auto-converts the uploaded docx into a moderncv "banking" template — the very template this repo produces). Reuse its `.cls`, its hard-won LaTeX gotchas (lualatex for fontawesome5, xelatex for fontspec, `\needspace`/`\enlargethispage` for page-fit, the itemize/font-wrapping fix), and its compile-and-inspect Verification Checklist for both generation and the fidelity check (`FR-RESUME-3/3a/4`). The user does **not** hand-author `.tex` — conversion is automated, gated by visual accept/reject, with a docx-XML fallback. **Do NOT adopt** its Danish job-portal skills (replaced by our JobSpy master aggregator + Workday focus, `FR-DISC-2`) or its manual CLI workflow (our product is an autonomous service). Take the **patterns, the LaTeX template, and the validation rigor; not the boards or the CLI model**.

---

## 6. Hexagonal architecture

**Core domain (pure):** Campaign (scopes everything), SearchCriteria, JobPosting, ViabilityScoring, ResumeVariant (+ lineage), ResumeFitScoring, GeneratedDocument (resume/cover-letter/answer), RevisionSession, AttributeStore (per-campaign, confirmation gate, sensitive-field policy), Decision, OutcomeEvent, LearningModel (per-campaign), AgentIntent, DetectionEvent, OnboardingProfile, PendingAction.

**Driving ports:** SetupWizard/OOBE, CampaignManagement, AttributeEditing, DigestReview, DocumentReview (redline + add/subtract/free-text revision; covers resume/cover-letter/answer), Chat, RemoteSessionControl, OutcomeLogging (mark-submitted), PendingActionsQuery, AdminQuery, UpdateTrigger.

**Driven ports:** LLM (OpenRouter), Discovery (pluggable sources), BrowserAutomation (patchright; browser-use/Skyvern fallback), DetectionMonitor, Sandbox (Neko) + RemoteView sub-port, ResumeTailoring (pluggable renderers — LaTeX primary, docx-XML fallback; redline + embedded-font export), FontInstall, Embedding (local), Storage (Postgres/JSONB + screenshots), CredentialStore (encrypted Postgres / Vaultwarden), Notification (Apprise/Discord), DurableOrchestration (DBOS), ToolRegistry.

**Rules:** core depends only on port interfaces; each adapter has a contract test; truthfulness, pre-fill-stop boundary, sensitive-field policy, confirmation-on-integral-change, and the mandatory review-before-submission gate are **domain rules** enforced in the core.

---

## 7. Application lifecycle (state machine)

```
DISCOVERED -> SCORED -> DIGESTED
  -> DECLINED (terminal; feedback -> FR-LEARN + criteria delta)
  -> APPROVED -> SANDBOX_PROVISIONING -> ACCOUNT_PREFILL --(form filled)--> AWAITING_ACCOUNT_HUMAN_STEP <-> (user: button/CAPTCHA/email-verify)
  -> PREFILLING
       <-> BLOCKED_DETECTION        (cautious-mode pause; notify + VNC)
       <-> BLOCKED_MISSING_ATTR     (soft error; attribute reused after resolve)
       <-> BLOCKED_QUESTION         (uncertainty; hold)
  -> MATERIAL_PREP                  (resume variant pick/generate; cover letter; screening answers; page-fit + fidelity check)
       <-> MATERIAL_REVIEW          (redline w/ add+subtract highlights; interactive add/subtract/free-text revision loop; approve/decline/revise)
  -> AWAITING_FINAL_APPROVAL        (bundled material approval + final-submit gate; notify + VNC)
  -> SUBMITTED_BY_USER (terminal)   -> log + OutcomeEvent(submitted)
  -> FINISHED_BY_ENGINE (terminal)  -> log + OutcomeEvent(submitted)   [friction-free, user-authorized]
  -> EMERGENCY_DATA_HANDOFF         (only when agent reports fill failed; user pastes into own browser; then mark-submitted)
  -> FAILED (terminal)              (unrecoverable; error surfaced)
```
Every `BLOCKED_*`/`AWAITING_*`/`MATERIAL_REVIEW` emits a notification, lands in the pending-actions portal, and yields capacity (pivot). The engine never clicks an account-creating submit, never solves a CAPTCHA, never auto-fills sensitive EEO fields, and never submits generated material without approval. Every step is a small idempotent DBOS step (mid-step resumption); approval waits use DBOS `recv`.

---

## 8. Data model (Postgres + JSONB — highlights; DBOS state co-resides)
- **campaigns**: criteria JSONB, schedule JSONB, run_mode, throughput_target, learning_state JSONB, exploration_budget. (One active in MVP-1; schema multi-ready.)
- **onboarding_profiles**: resumable wizard state per campaign, completion flag (gate), full Workday-ready intake.
- **attributes / field_mappings**: **per-campaign** cloud + aliases + per-site field bindings; `is_integral`; `is_sensitive` (EEO policy). ATS field-mapping knowledge MAY be learned globally.
- **fonts**: uploaded font assets + install status, per environment.
- **discovery_sources**: source key, enabled, yield_stats JSONB (decayed).
- **job_postings**: normalized fields, viability score + rationale.
- **resume_variants**: storage_path (docx), parent_id (lineage), targeted_jd_signature, fit_scores JSONB, approved bool (approved = reusable parent).
- **generated_materials**: type (resume/cover_letter/screening_answer), application_id, content/storage_path, redline state, approved bool.
- **revision_sessions**: material_id, redline state, turns JSONB (add/subtract/free-text + AI response), status.
- **applications**: posting_id, role_name, job_title, work_mode, root_url, attributes_used JSONB, resume_variant_id, status (§7), sandbox_session_url, timestamps.
- **application_screenshots**, **decisions** (approve/decline, feedback_text, criteria_delta JSONB), **outcome_events** (type, source auto/manual), **agent_runs** (intent_sentence), **detection_events**, **tool_settings**, **dormant_surface_backlog**, **app_config** (provider/model/channels; secrets via key-file-encrypted store).
- **pending_actions** (derived/materialized): every item awaiting user input, for `FR-UI-3`.

---

## 9. Work packages (phased for sub-agents; each TDD/BDD, requirement-tagged)

**Phase 0 — Foundation, gates & OOBE:** core domain + lifecycle + truthfulness/pre-fill-stop/sensitive-field/confirmation domain rules (`NFR-ARCH`); **campaign-scoped** Postgres/JSONB schema (multi-ready); **DBOS durable backbone** (`FR-DUR`); OpenRouter LLM adapter + auto-pull (`FR-LLM`); structlog; **frontend clone shell** + grayed dormant surfaces (`FR-UI-1/2`); **setup wizard framework** starting with the LLM gate (`FR-OOBE`, `FR-UI-5`); **comprehensive Workday-ready onboarding intake** + base-resume parse + **font upload flow** (`FR-ONBOARD`, `FR-FONT`). Exit: domain >90% covered with ports mocked; gates enforced; a trivial DBOS workflow resumes after a kill; no CLI needed post-install for setup.

**Phase 1 — Discovery, scoring, digest, feedback, learning, pending-actions:** **master aggregator over easy sources** + toggles + extensible source adapters (`FR-DISC`); viability scoring (`FR-AGENT-3`); **channel setup wired into the wizard** (Discord bot + email) (`FR-OOBE-2`,`FR-NOTIF`); digest email/webpage + Discord-ready + approve/decline-with-feedback (`FR-DIG`); **pending-actions portal** (`FR-UI-3`); per-campaign attribute cloud + confirmation gate + sensitive-field policy (`FR-ATTR`); **learning engine v1** (`FR-LEARN`); local embeddings.

**Phase 2 — Pre-fill + Workday + sandbox + stealth + takeover + conversion:** BrowserAutomation (patchright) + ATS abstraction + **Workday adapter** (`FR-PREFILL-2`); maximal pre-fill incl. account-creation + screening-question detection + EEO stored-answer fill (`FR-PREFILL`,`FR-ATTR-6`); fingerprint normalization + residential egress (`FR-STEALTH`); Neko sandbox + swappable remote-view (`FR-SANDBOX`); cautious mode (`FR-PREFILL-6`); final-approval gate via DBOS `recv` + ladder (`FR-NOTIF`); submission detection + mark-submitted (`FR-LOG-4`); credential vault, both banking modes (`FR-VAULT`); DBOS queues for concurrency + rate limits. *(Phase 2 uploads the base resume as-is to prove the end-to-end Workday flow.)*

**Phase 3 — Material generation + interactive feedback engine:** OOXML resume engine + page-fit + **font-embedded PDF/docx fidelity** (`FR-RESUME-3/4`,`FR-FONT`); truthfulness guardrail (`FR-RESUME-2`); em-dash filter + banned-phrase list + voice extraction (`FR-RESUME-5`); variant scoring/selection/generation + library/lineage (`FR-RESUME-6/7`); cover letters (`FR-RESUME-10`); **screening-answer generation** (`FR-ANSWER`); **redline review + interactive add/subtract/free-text revision loop** for all material (`FR-RESUME-8`,`FR-NOTIF-4`); job-getting optimization + grayed aggressiveness control (`FR-RESUME-9`).

**Phase 4 — Learning depth, breadth, polish, packaging:** real-conversion learning across all inputs + attribute cross-referencing (`FR-LEARN-2/3/4`); additional ATS adapters + additional discovery modules (`NFR-EXT-1`); tool registry/toggles (`FR-UI-4`); debug surface (`FR-OBS-2`); history + variant library UI (`FR-UI-6`); **Dormant Surface Wiring Backlog** (`FR-UI-2`); **one-liner install/update → VM + in-UI Update button** (`FR-INSTALL`,`FR-OOBE-4`); multi-campaign architecture readiness verification; Tailscale access + browser-extension capture (later).

---

## 10. BDD acceptance anchors (seed; expand per WP)
```gherkin
Feature: Zero-CLI out-of-box setup                            # FR-OOBE-1
  Scenario: First run after install
    Given the product is installed and reachable in the browser
    Then the user configures the LLM, Discord/channels, fonts, and the Workday-ready intake entirely in the UI
    And no command line is required for any setup step
    And automated work cannot begin until channels are configured and onboarding is complete

Feature: Per-campaign attribute cloud                         # FR-CRIT-4, FR-ATTR-1
  Scenario: Data scoping
    Given a campaign
    Then its attribute/answer cloud, base resume, variants, credentials, and learning are scoped to that campaign
    And the schema supports adding more campaigns without rework

Feature: Resume uploads right and looks right                 # FR-RESUME-4, FR-FONT-1
  Scenario: Required fonts are missing on the target environment
    When the base resume is uploaded
    Then the system detects required fonts and prompts the user to upload missing ones
    And the final artifact (PDF with embedded fonts or docx) preserves the exact visual style
    And a fidelity check guards against conversion drift

Feature: Screening answers go through review                  # FR-ANSWER-1, FR-RESUME-8
  Scenario: An essay-style application question
    When the application asks "Why do you want this role?"
    Then a high-scoring answer is generated in the user's professional voice
    And it is routed to review where the user may approve, decline, or send back with revisions
    And it is never submitted without approval

Feature: Sensitive fields are never AI-guessed                # FR-ATTR-6
  Scenario: An EEO self-identification field
    Then it is filled only from the user's explicit stored answer
    And it defaults to "decline to self-identify" unless the user set otherwise

Feature: Pending-actions portal                               # FR-UI-3
  Scenario: Items await the user
    Then a primary portal lists every pending decision and action (approvals, reviews, soft errors, questions)
    And each is actionable from there

Feature: Maximal pre-fill, stop at irreducible human steps    # FR-PREFILL-2/4
  Scenario: Workday account creation
    Given an approved role on a Workday tenant requiring an account
    When the engine reaches the account-creation form
    Then it pre-fills every fillable field
    And it does not click the account-creating submit
    And it notifies the user with a one-click VNC link to complete the button, CAPTCHA, and email verification

Feature: Interactive resume review with highlighted edits     # FR-RESUME-8
  Scenario: A generated resume is reviewed and revised
    Given an application whose resume was adapted from the base
    Then additions and deletions are both highlighted against the base
    And the user can add, subtract, or give free-text feedback
    And the AI revises within the base XML template and re-renders the redline
    And no submission is possible until the user approves

Feature: Adaptation never fabricates                          # FR-RESUME-2, NFR-TRUTH-1
  Scenario: Improving a low fit score
    Given a JD requiring a skill the user does not have
    Then the engine reframes and surfaces real experience and matching terminology
    And it does not add the missing skill or any false claim

Feature: Mid-step crash resumption                            # FR-DUR-1/3
  Scenario: Worker dies mid-application
    When the worker process is killed and restarts
    Then the DBOS workflow resumes from the last completed step without losing prior progress

Feature: Conversion is approval plus submission               # FR-LEARN-2, FR-LOG-4
  Scenario: A submitted application
    Then submission is auto-detected from the confirmation page (or one-tap "mark submitted" when it cannot be)
    And an outcome event marks it converted for that campaign's learning

Feature: Discord-first with 30s hold and web pre-empt         # FR-NOTIF-2/3
  Scenario: User approves on web before Discord fires
    When the user approves within 30 seconds, the Discord push is suppressed
  Scenario: No response anywhere
    Then email is sent after the configurable 15-minute timeout and acting on any channel expires the others

Feature: Master aggregator in wave one                        # FR-DISC-2
  Scenario: Discovery in MVP-1
    Then the easy sources are aggregated by a master aggregator
    And new per-platform source modules can be added as adapters without core changes

Feature: Source-yield learning with exploration               # FR-DISC-5, FR-LEARN-6
  Scenario: A source consistently underperforms
    Then discovery weight shifts toward higher-yield sources
    And the exploration budget still periodically tries under-used sources
```

---

## 11. Constraints & caveats (binding)
- **Workday-ready onboarding is heavier by design.** Pulling full work history, education, references, work authorization, and EEO answers into the upfront intake makes setup longer in exchange for far fewer soft-error interruptions on early applications — a deliberate trade for a Workday-first MVP.
- **Workday is the hardest mainstream ATS** (per-tenant subdomains, account-required, long dynamic multi-step flows, detection-sensitive). MVP-1 targeting it is ambitious; the maximal-pre-fill + irreducible-human-step model fits, but expect iteration. The ATS abstraction lets simpler portals follow.
- **Resume rendering: LaTeX primary, with a load-bearing docx fallback.** The docx→LaTeX conversion reliably carries *content* but does **not** guarantee a match to the user's exact hand-tuned design; the onboarding accept/reject gate (`FR-RESUME-3a`) lets the user keep LaTeX (deterministic output, trivial source-level redline diffing, native font embedding) or fall back to in-place docx-XML editing of their uploaded file. **Expect genuine use of the fallback** when the converted look doesn't satisfy the user — that is the safety net working, not a failure. The font subsystem (`FR-FONT`) + embedding + a compile-and-visually-inspect fidelity check guard every artifact. "Uploads right and looks right" is the acceptance bar.
- **Anti-detection is best-effort;** residential egress + persistent profiles + the user performing irreducible steps in a real session are the strongest levers. No CAPTCHA solving, ever.
- **Truthfulness is non-negotiable** (`NFR-TRUTH-1`); the fit-scorer must not become a fabrication target. Sensitive EEO fields are never AI-guessed.
- **Durable execution is lightweight here** — DBOS runs in-process on the existing Postgres, no separate server.
- **Local LLM has a real capability/context ceiling; the tier ladder is the mitigation.** A 2080 Ti 22GB runs ~27B-class dense models at roughly a 72K-token context ceiling — fine for routine agentic work, but with no headroom to escalate to something *more capable* locally. So the capability ladder (`FR-LLM-3`) should include at least one cloud tier near the top; escalation climbs the ladder on low confidence, hard task type, and **context overflow** (`FR-LLM-4`). A purely-local ladder is supported but bounded by the card. Local models also vary in tool-calling/structured-output reliability, so the adapter parses defensively and falls back to prompt-based structured output (`FR-LLM-4a`).
- **Discovery scraping at volume** from one residential IP risks throttling on hostile boards; start with easy sources, keep a proxy hook for later.
- **AGPL deps** (Skyvern, SearXNG, MinIO if used) carry distribution obligations — immaterial for personal self-hosted use; keep private or swap if distributed. Applicant, JobSpy, LangGraph, Neko, patchright, FastAPI, Apprise, DBOS are permissive; preserve Applicant's MIT notice.
- **AI-text detectors cannot be reliably defeated;** the mandatory review/revision loop is the safeguard.

---

## 12. Open items (defaults in place — non-blocking)
- **Codename** — placeholder **Applicant**; rename cascades.
- **Resume aggressiveness tuning** — deferred: optimize for job-getting potential now; ship the UI control **grayed out** with a stub spec (`FR-RESUME-9`).
- **Resume-fit "badly" threshold** and **viability threshold** — default ≥70, configurable.
- **Quiet hours** — errors always immediate; approvals/digests respect optional quiet hours unless 24/7.
- **Resolved through v4:** durable engine = DBOS; deployment = Proxmox VM; per-campaign attribute cloud; resume feedback/revision engine; resume fidelity via font subsystem + embedded-font PDF/docx; full zero-CLI OOBE wizard + in-UI Update button; screening-answer generation with review; pending-actions portal; EEO stored-answers policy; single-campaign MVP-1 with multi-campaign-ready architecture; both credential-banking modes; Workday-ready onboarding; master aggregator in wave one.

---

## 13. Traceability
Claude Code MUST maintain a matrix: **Requirement ID -> Work Package -> BDD Feature(s) -> adapter/contract test.** Any requirement lacking a downstream feature and test is a spec gap to flag, not drop. Any new ambiguity goes to §12 with a recommended default.
