# Work Packages (Phases 0-4)

Source: master spec §9. Each phase is delivered by implementer sub-agents using TDD/BDD, with every sub-task tagged to requirement IDs (§ engineering mandate). Phases build on each other; later phases assume earlier exit criteria hold.

---

## Phase 0 — Foundation, gates & OOBE

**Goal:** Stand up the pure core, the durable backbone, the LLM port, and the zero-CLI setup wizard through onboarding — so that nothing downstream can violate the domain rules and a killed worker resumes mid-step.

**Sub-tasks:**
- Pure core domain + §7 lifecycle state machine, with the domain rules wired in: truthfulness, pre-fill-stop boundary, sensitive-field policy, confirmation-on-integral-change (NFR-ARCH-1).
- Campaign-scoped Postgres/JSONB schema (multi-ready) with SQLAlchemy + Alembic (FR-CRIT-4).
- DBOS durable backbone: workflows, idempotent steps, `send`/`recv`, scheduling, queues skeleton (FR-DUR-1/2/3).
- OpenRouter LLM adapter + auto-pull model list; tier-ladder config; defensive structured-output parsing (FR-LLM-1/2/3/4/4a/5).
- structlog with correlation IDs + secret redaction; DBOS OTel (FR-OBS-1).
- Frontend clone shell: vendor Odysseus `static/` verbatim, MIT notice preserved, served from FastAPI; grayed dormant surfaces (FR-UI-1/2).
- Setup wizard framework starting with the LLM-settings gate (FR-OOBE-1/2, FR-UI-5).
- Comprehensive Workday-ready onboarding intake + base-resume parse + reconciliation (FR-ONBOARD-1/2/3).
- Font upload flow with detection of required fonts and runtime cache refresh (FR-FONT-1/2).
- LaTeX conversion preview + accept/reject gate at onboarding (FR-RESUME-3a).
- NFR foundations: local-first (NFR-LOCAL-1), token-frugality posture (NFR-TOKEN-1), 24/7 durability (NFR-247-1), zero-CLI (NFR-ZEROCLI-1), extensibility (NFR-EXT-1), truthfulness (NFR-TRUTH-1).

**Requirement IDs covered:** FR-LLM-1..5, FR-LLM-4a, FR-CRIT-4, FR-FB-3 (rule), FR-ATTR-6 (rule), FR-ONBOARD-1/2/3, FR-OOBE-1/2 (framework), FR-FONT-1/2, FR-RESUME-2 (rule), FR-RESUME-3a (gate), FR-RESUME-5 (post-filter rule), FR-RESUME-8 (gate rule), FR-DUR-1/2/3/4 (rule), FR-AGENT-4/5/6 (rules), FR-UI-1/2 (shell), FR-UI-5, FR-OBS-1, NFR-LOCAL-1, NFR-ARCH-1, NFR-247-1, NFR-ZEROCLI-1 (rule), NFR-EXT-1 (rule), NFR-TRUTH-1 (rule), NFR-TOKEN-1.

**Exit gate (explicit, §9):**
- Domain **>90% covered** with ports mocked.
- Gates enforced (truthfulness / pre-fill-stop / sensitive-field / confirmation-on-integral-change / review-before-submission).
- A trivial **DBOS workflow resumes after a kill**.
- **No CLI needed post-install** for setup.

---

## Phase 1 — Discovery, scoring, digest, feedback, learning, pending-actions

**Goal:** Find and score postings, deliver the approve/decline digest, capture feedback, run learning v1, and stand up the pending-actions home base — wiring notification channels into the wizard.

**Sub-tasks:**
- Master aggregator over easy sources + UI toggles + extensible source adapters (FR-DISC-1/2/3/4); proxy hook design (FR-DISC-6).
- Source-yield learning + exploration budget (FR-DISC-5, FR-LEARN-6).
- Per-campaign criteria, human-readable/UI-editable/LLM-mutable (FR-CRIT-1/2/3).
- Viability scoring from the JD (FR-AGENT-3); throughput tuning + run modes + intent sentence (FR-AGENT-1/2/7).
- Channel setup wired into the wizard: Discord bot + email via Apprise (FR-OOBE-2/3, FR-NOTIF-1).
- Daily digest email/webpage + Discord-ready + approve/decline-with-feedback + rationale + empty-day note (FR-DIG-1..6).
- Notification escalation ladder + idempotency + error immediacy/quiet hours (FR-NOTIF-2/3/5).
- Decline-with-feedback + chat/survey feedback + integral-change confirmation UI (FR-FB-1/2/3).
- Per-campaign attribute cloud + confirmation gate + sensitive-field policy + dynamic add + missing-attr soft error (FR-ATTR-1/3/4); attribute binding scaffolding (FR-ATTR-2).
- Learning engine v1: per-campaign, learn from every input, cross-reference attribute cloud, learn converting-role signature, keep it cheap (FR-LEARN-1/3/4/5/7); local embeddings (NFR-LOCAL-1).
- Pending-actions portal (FR-UI-3).

**Requirement IDs covered:** FR-DISC-1..6, FR-CRIT-1/2/3, FR-LEARN-1/3/4/5/6/7, FR-DIG-1..6, FR-FB-1/2/3, FR-ATTR-1/2/3/4, FR-AGENT-1/2/3/7, FR-NOTIF-1/2/3/5, FR-OOBE-2/3 (channels), FR-UI-3, plus learning-feeds-of FR-LEARN-2 (partial).

**Exit criteria:** A campaign discovers and scores real postings; a daily digest is delivered across channels and approve/decline-with-feedback round-trips into learning and the next run's criteria; the pending-actions portal lists live items; channel setup gates automated work.

---

## Phase 2 — Pre-fill + Workday + sandbox + stealth + takeover + conversion capture

**Goal:** Prove the end-to-end Workday flow: maximal pre-fill in an isolated, stealthy sandbox, stopping at irreducible human steps, with live takeover, the credential vault, conversion capture, and DBOS queues. (Uses the base resume as-is; generation comes in Phase 3.)

**Sub-tasks:**
- BrowserAutomation (patchright) + ATS abstraction + Workday adapter (FR-PREFILL-1/2).
- Maximal pre-fill incl. account-creation + screening-question detection + EEO stored-answer fill (FR-PREFILL-2/3, FR-ATTR-5/6).
- Irreducible-human-step boundary + final-submit handoff + cautious mode + emergency data-handoff (FR-PREFILL-4/5/6/7, NFR-CAUTION-1).
- Fingerprint normalization + human-like interaction + persistent per-tenant profiles + residential egress + honest caveat (FR-STEALTH-1..5).
- Neko sandbox + swappable remote-view sub-port + multi-session (FR-SANDBOX-1/2/3/4).
- Final-approval gate via DBOS `recv` + escalation ladder for final approval (FR-NOTIF-2/4).
- Submission detection + one-tap mark-submitted; per-application logging + per-page screenshots (FR-LOG-1/2/4, FR-LEARN-2).
- Credential vault, both banking modes, key-file master key, no secret logging (FR-VAULT-1/2/3, NFR-PRIV-1).
- DBOS queues for sandbox concurrency cap + per-provider LLM rate limits (FR-DUR-2/3); live pivot-around-blocker (FR-DUR-4, FR-AGENT-6).

**Requirement IDs covered:** FR-PREFILL-1..7, FR-ATTR-5/6 (fill), FR-STEALTH-1..5, FR-SANDBOX-1..4, FR-NOTIF-2/4, FR-LOG-1/2/4 (capture), FR-LEARN-2, FR-VAULT-1/2/3, FR-DUR-2/4, FR-AGENT-6, NFR-CAUTION-1, NFR-PRIV-1.

**Exit criteria:** An approved Workday role is pre-filled across every page in a sandbox; the engine stops at account-creating submit / CAPTCHA / verification and hands off via one-click VNC; cautious mode pauses on detection; submission is detected (or marked) and logged with screenshots; credentials are banked both ways.

---

## Phase 3 — Material generation + interactive feedback engine

**Goal:** Generate truthful, non-AI-looking, fidelity-checked resumes, cover letters, and screening answers, all routed through the interactive redline review/revision gate.

**Sub-tasks:**
- ResumeTailoring port: LaTeX primary (xelatex/lualatex+fontspec, moderncv) + docx-XML fallback + page-fit + font-embedded PDF/docx fidelity check (FR-RESUME-3/4, FR-FONT-2).
- Truthfulness guardrail enforcement (FR-RESUME-2, NFR-TRUTH-1).
- Em-dash deterministic post-filter + banned-phrase list + voice extraction/matching on every revision pass (FR-RESUME-5).
- Variant scoring/selection/generation + library/lineage + cluster/cap (FR-RESUME-6/7).
- Cover letters on demand (FR-RESUME-10); screening-answer generation factual vs essay (FR-ANSWER-1).
- Redline review with add+subtract highlights + interactive add/subtract/free-text revision loop for all material; review-notification linkage; bundled-into-final-submit default (FR-RESUME-1/8, FR-NOTIF-4).
- Job-getting optimization within truthfulness + grayed aggressiveness control stub (FR-RESUME-9).

**Requirement IDs covered:** FR-RESUME-1/2/3/4/5/6/7/8/9/10, FR-ANSWER-1, FR-FONT-2, FR-NOTIF-4, NFR-TRUTH-1, NFR-TOKEN-1 (generation frugality).

**Exit criteria:** For a role warranting it, the engine selects or generates a resume variant and/or cover letter and/or screening answers; em-dashes are stripped deterministically; output passes the compile-and-visually-inspect fidelity check; the user runs the add/subtract/free-text redline loop and approves before any submission.

---

## Phase 4 — Learning depth, breadth, polish, packaging

**Goal:** Deepen real-conversion learning, broaden adapters, finish the toggle/debug/history surfaces, ship the one-liner install/update, and verify multi-campaign readiness.

**Sub-tasks:**
- Real-conversion learning across all inputs + attribute cross-referencing depth (FR-LEARN-2/3/4).
- Additional ATS adapters + additional discovery modules (NFR-EXT-1).
- Tool registry/toggles (FR-UI-4).
- Debug surface: logs, screenshots, per-application history, durable-workflow state (FR-OBS-2).
- History + variant library UI + remaining FR-UI-6 surfaces (FR-UI-6, FR-LOG-3).
- Dormant Surface Wiring Backlog finalized (FR-UI-2).
- One-liner install/update → VM, Docker Compose stack, in-UI Update button (FR-INSTALL-1/2/3, FR-OOBE-4, NFR-ZEROCLI-1).
- Multi-campaign architecture readiness verification (NFR-EXT-1); Tailscale access + browser-extension capture (later).

**Requirement IDs covered:** FR-LEARN-2/3/4 (depth), FR-UI-2/4/6, FR-OBS-2, FR-LOG-3, FR-INSTALL-1/2/3, FR-OOBE-4, FR-CHAT-1, NFR-EXT-1, NFR-ZEROCLI-1 (update).

**Exit criteria:** Conversion learning closes the loop across every input; the tool registry, debug surface, and history/variant-library UIs are live; the one-liner install and in-UI Update button work end-to-end with DB backup/migration/rollback; multi-campaign readiness is verified.

> **Note on FR-CHAT-1:** §3.20 mandates the chatbot; §9 does not name it in any phase explicitly. It is placed in Phase 4 (alongside the remaining FR-UI-6 surfaces, which include "the chatbot") and flagged as a soft mapping in [traceability.md](traceability.md).
