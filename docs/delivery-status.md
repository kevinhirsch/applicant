# Delivery Status

Single source of "done" truth: a per-phase delivery summary for Applicant.
**All phases are merged to `main`:** engine phases 0–4, a production-hardening remediation
pass that followed an honest re-audit, the **front-door (Phase 5)** lift-and-shift of
the operator UI onto the white-labeled workspace app plus a reachability re-audit, and the
first slice of the **founder-trust track** (road-to-market Phase 1.5: truth policy,
parse-verify, honest wizard surfacing — see the section below). The engine's hermetic
lane is green — **3,794 passed** (2026-07-07, the unreachable-`DATABASE_URL` command in
`CLAUDE.md`) with 26 integration-gated skips on the full lane (count guarded by a
meta-test).

> **Done means reachable.** A requirement is delivered only when it is reachable/operable
> in the white-labeled workspace **front door** (`workspace/`), not merely when the engine
> implements it and its tests pass. The engine runs internal-only (`api:8000`); the
> operator only ever touches the front door (`applicant-ui` on `${APP_PORT}` → 7000), which
> proxies the engine. Earlier delivery claims measured the engine alone — that
> understated the work and overstated reachability. Both dimensions are now tracked here
> and in [traceability.md](traceability.md).

See [traceability.md](traceability.md) for the re-verified requirement-level coverage
(engine delivery **and** front-door reachability) and [work-packages.md](work-packages.md)
for the phase plan and exit criteria.

## Test count progression

| Milestone | Tests passing |
|---|---|
| Phase 0 | 191 |
| Phase 1 | 264 |
| Phase 2 | 339 |
| Phase 3 | 425 |
| Phase 3b (durable revision sessions) | 480 |
| Phase 4 | 539 |
| Production-hardening remediation | 594 |
| Production-hardening re-audit | 2436 |
| Front-door UX-hardening pass | 3704 engine + 2647 front-door |
| Founder-trust slice: truth policy + parse-verify + surfacing (current) | **3794 engine + 2714 front-door + 45 front-end JS** |

(Integration tests skip by default — they require live external boundaries. One engine test,
`test_the_secretstorage_layer_roundtrips…`, fails only in a CWD-relative-SQLite local env and
passes in CI.)

The **front-door UX-hardening pass** is the ongoing closure of the 12-lens `exhaustive2/`
audit backlog + the incidental-bug ledger — see
[design/audits/exhaustive2/CLOSURE-STATUS.md](design/audits/exhaustive2/CLOSURE-STATUS.md)
for per-lens status and [design/audits/discovered-issues.md](design/audits/discovered-issues.md)
for the bug ledger. It also closed the cross-user isolation thread (single-tenant engine: the
`pending/campaigns/tracker/activity` proxies are now owner-scoped on reads **and** writes).

## What is and isn't proven by the test suite

The **3704 hermetic engine tests prove the logic** of every requirement against fakes / in-memory
adapters — gates, state transitions, learning math, escalation cadence, sealing/unsealing,
conversion rendering, etc. They do **not** exercise the real external boundaries end-to-end;
the **26 integration-gated skips** cover those and run only on a live deployment with the
matching toolchain/service present (live Postgres/DBOS, a real browser + chromium binary,
live job boards, real TeX/LibreOffice, a live Neko session, live Discord/SMTP). The
production code paths for those boundaries exist and are wired — only their live execution is
gated. They are environment dependencies, not requirement gaps.

## Per-phase summary

### Phase 0 — Foundation, OOBE, durability (191 tests)
**Delivered:** hexagonal skeleton (core/ports/adapters), provider-agnostic LLM port
(OpenAI-compatible + Ollama) with tier ladder and escalation, zero-CLI setup wizard
(LLM-gate first), resumable onboarding intake, resume parser bootstrapping the attribute
cloud, font management, durable orchestration port (file-backed `shim` default + DBOS
adapter), structlog observability with correlation IDs + redaction, the engine-local
`frontend/static/` shell + dormant-surface registry (the real operator front door is the
workspace app delivered in Phase 5), truthfulness / em-dash / confirmation-gate core rules.
**Exit criteria:** met — boots with no Postgres, full suite hermetic, mid-step resumption proven.

### Phase 1 — Discovery, criteria, digest, learning, notifications (264 tests)
**Delivered:** JobSpy/SearXNG discovery with normalization and zero-token structured paths,
per-campaign self-learning criteria, dynamic attribute cloud, daily digest (rationale +
approve/decline-with-feedback), pending-actions portal, viability scoring, agent run modes /
throughput / intent log, source-yield + exploration learning, Apprise/Discord/web/email
notifications with the 30s-hold escalation ladder and idempotency.
**Exit criteria:** met — discovery→digest→approve/decline→learning loop closes per campaign.

### Phase 2 — Pre-fill, sandbox, stealth, vault, logging (339 tests)
**Delivered:** per-application ephemeral browser sandbox, Workday ATS adapter with maximal
pre-fill, deterministic field mapping + LLM escalation for ambiguity, stop-at-irreducible-
human-steps handoff, final-submit approval gate, one-click live remote session (Neko/noVNC),
cautious mode + detection monitor, encrypted credential vault (libsodium / `pynacl`,
key-file master key, redaction), per-page screenshot logging, submission detection +
mark-submitted feeding conversion learning.
**Exit criteria:** met — approval spins a sandbox, pre-fills, and hands off at irreducible steps.

### Phase 3 — Material generation & interactive review (425 tests; 480 with 3b)
**Delivered:** ResumeTailoring port (LaTeX-primary via Jinja2 + docx-XML fallback via
python-docx), fidelity check (compile + inspect), cover letters and screening answers,
truthfulness + non-AI-voice guardrails, variant library with lineage and local fit-scoring
(reuse-or-generate), interactive redline review. **Phase 3b** added the durable
`revision_sessions` repository so the revision loop survives restarts (FR-RESUME-8 + FR-DUR-1).
**Exit criteria:** met — material generated truthfully, reviewed via redline, never auto-submitted.

### Phase 4 — Conversion learning, tooling, debug, chatbot, install/update (539 tests)
**Delivered:** deepened real-conversion learning (AdvancedLearningService), per-tool toggle
registry (FR-UI-4), debug surface (AdminQueryService + admin router: logs / screenshots /
per-application history / durable-workflow state), confirmation-gated chatbot (ChatService +
chat router, FR-CHAT-1), history retrieval UI, in-UI Update button, and the one-liner
`scripts/install.sh` + `scripts/update.sh` (backup / migrate / restart / rollback).
**Exit criteria:** met. Every FR-*/NFR-* requirement is delivered and re-verified against the
engine code; the only un-exercised paths are the integration-gated boundaries above
(environment dependencies, not requirement gaps).

### Phase 5 — Front door: white-labeled workspace UI + bridge

**Delivered:** the operator-facing UI moved out of the engine and onto the **white-labeled
workspace app** (`workspace/`), the only surface the operator opens. Phase 5 stood up the
bridge (workspace→engine via `workspace/src/applicant_engine.py` / `ENGINE_URL`;
engine→workspace callbacks via `workspace/routes/applicant_internal_routes.py` /
`APPLICANT_INTERNAL_TOKEN`), the thin auth-protected `/api/applicant/*` **proxy routes**,
the per-surface **JS glue** (`workspace/static/js/applicant*.js`), and the **progressive
feature-activation** layer (`workspace/src/applicant_features.py`) that greys/locks/activates
each section from engine setup status. Surfaces were **lifted and shifted** onto existing
workspace components rather than rebuilt (the OOBE LLM step reuses the workspace's
Local/Remote model-endpoint manager). The production Compose stack became the two-app
topology: public `applicant-ui` (→ 7000) + internal `api` (8000) + postgres + searxng +
chromadb + ntfy (+ optional takeover-desktop / ollama). Removed during this focus pass:
Home Assistant, awareness/proactive, and "Nobody"/incognito mode.

**Reachable surfaces (front door → engine):** OOBE setup/onboarding wizard, pending-actions
portal, documents/résumé redline review, profile (criteria + attributes + learning), chat/
assistant + job actions, email/digest + feedback survey, activity/debug + history +
mark-submitted + Update button, live remote view/takeover + submit/authorize, credential
vault. **Compare** ships present-but-disabled. Calendar / Deep-Research / Cookbook stay
native workspace surfaces reached via the internal callback channel.

**Exit criteria:** met. Every operator-facing requirement family is reachable across the
chain spec → engine router → workspace proxy → JS → nav/section (see
[traceability.md](traceability.md#front-door-reachability) and
[dormant-surfaces.md](dormant-surfaces.md)).

### Assistant learning + desktop assist (FR-MIND / FR-CUA)

Two capabilities lifted-and-shifted from the Hermes Agent (MIT) substrate landed on `main`
behind their own specs ([agent-intelligence.md](spec/agent-intelligence.md) `FR-MIND`,
[computer-use.md](spec/computer-use.md) `FR-CUA`) and are now made **deploy-configurable and
documented** so the stack is shippable:

- **Assistant learning & memory (`FR-MIND`)** — curated memory ("what the assistant
  remembers"), saved playbooks, cross-session recall, and a periodic curation review whose
  proposed self-writes stage for approval. **Reachable and live** end-to-end: engine ports
  (`MemoryStore`/`SkillStore`/`RecallIndex`, in-process default + a `bridge` to the front-door
  store) → `app/routers/agent_memory.py` → workspace `/api/applicant/mind/*` proxy →
  `applicantMind.js` memory panel + portal curation approvals. The three surfaces are `live`
  in `src/applicant/dormant.py` (`assistant_memory`, `saved_playbooks`, `curation_approvals`).

  **The loop now actually learns, uses, and reports itself — end-to-end.** What changed in this
  wave:
  - **Curation learns from real signal.** The scheduled review nudge no longer proposes from a
    placeholder: it reviews REAL run history (`application/services/run_history.py`
    `RunHistoryProvider`) AND the user's own feedback (`application/services/feedback_history.py`
    `FeedbackSummaryProvider`, mined from digest declines + résumé/answer revision instructions),
    summarizes each run with a cheap optional LLM (`CURATION_MODEL`; degrades to a trivial
    summarizer so the hermetic lane stays green), and **populates cross-session recall** through
    the `RecallIndex.index()` write path. Every proposal still stages for review (FR-MIND-9),
    is advisory-only (FR-MIND-11), and is idempotent across the per-tick `AgentLoop` rebuild via
    the process-lived ledger (FR-MIND-10).
  - **Learned memory/skills feed back into work.** `material_service` (résumé/cover/answers) and
    `scoring_service` (viability) append a bounded, advisory "what the assistant has learned"
    block read fresh per call — it nudges output toward the user's taste without conferring
    authority and never relaxes the no-fabrication guard (FR-RESUME-2).
  - **The chatbot IS the autonomous agent.** One first-person identity (FR-MIND-4) that reports
    its own past/present/future from real read-only state (run status, scheduler estimate,
    application history — FR-AGENT-7 / FR-OBS-2; `chat_service.py`). Chat-driven steering is in
    progress.
  - **"What the agent is doing" is now operator-visible.** A read-only now/next/recent snapshot
    (`app/routers/agent_status.py` → `/api/applicant/activity/snapshot` → `applicantActivity.js`)
    plus a proactive **daily status update** (`status_update.py` `StatusUpdateService`) pushed
    through the existing notification ladder.
  - **LLM context management (FR-MIND-8).** Middle-turn compression past
    `CONTEXT_COMPRESS_THRESHOLD` + a provider-gated prefix cache (`PREFIX_CACHE`) at the LLM
    adapter (`adapters/llm/context_window.py`).

  **Wave 2 — deeper learning + onboarding** landed on `main` on top of the above:
  - **Agent-callable tools (FR-MIND-6).** A capability-gated tool-calling seam on the LLM
    port/adapter lets the chat assistant call `remember` / `forget` / `save_playbook` /
    `update_playbook` / `recall` / `desktop` mid-conversation (`chat_tools.py` `ChatToolbox`;
    opt-in via `CHAT_TOOLS`, default `off`). Writes route through review-before-write
    (FR-MIND-9) and stage for approval; a tool asserting `claims_authority` is refused
    (FR-MIND-11); `desktop` goes through the FR-CUA guards; each tool is gated by the FR-UI-4
    tool registry.
  - **Onboarding seed (FR-MIND-1/3).** Completing onboarding seeds a bounded curated-memory
    baseline and indexes cross-session recall from the user's own profile/résumé
    (`onboarding_seed.py`); idempotent, and a no-op when the substrate is absent.
  - **Learned-context provenance (FR-MIND-5/11).** Generation now records which learned
    memory / playbooks / recall it drew on (`GeneratedDocument.provenance`, migration `0006`);
    the document-review surface shows a "What I drew on" panel.
  - **Minimal onboarding + block-until-essentials gate (FR-ONBOARD/FR-OOBE).** A new core
    rule `core/rules/apply_readiness.py` defines the REQUIRED-TO-APPLY set (target roles, work
    mode, locations, salary floor, key skills, résumé). The onboarding form now requires
    ~only "connect a model"; the automated-work gate (`automated_work_allowed`) keys on
    `is_ready_to_apply()` and stays BLOCKED until those essentials exist. `/api/setup/status`
    emits `apply_ready` / `apply_missing` / `apply_blocked_reason`, and the wizard renders an
    honest "what's still needed to start applying" banner.

  **Proven green end-to-end** by the hermetic loop smoke `tests/unit/test_loop_end_to_end.py`,
  which runs discovery → scoring → digest → approval → pre-fill → stop-boundary WITH the learning
  hooks firing.

- **Desktop assist / computer use (`FR-CUA`)** — optional background desktop control,
  confined to the sandbox/takeover surface, complementing the browser path; it now also backs
  **native OS upload dialogs** the browser cannot reach during pre-fill (desktop self-use,
  #141). The port, the core safety guards (stop-boundary, hard-blocks, no-secrets), the
  live-session toggle, and the proxy routes are wired, but the surface ships
  **present-but-grayed** (`desktop_assist`, `dormant` in `src/applicant/dormant.py`): the safe
  no-side-effects backend boots, and the toggle stays locked with honest copy until the desktop
  driver + display stack are baked into the **sandbox** image and the health preflight passes.

The new deploy knobs are exposed in `.env.example` and passed through to the `api` service in
`docker/docker-compose.prod.yml` (`MIND_BACKEND`, `MEMORY_WRITE_APPROVAL`,
`SKILLS_WRITE_APPROVAL`, `MEMORY_MAX_CHARS`, `USER_MAX_CHARS`, `CURATION_SCHEDULE`,
`CURATION_MODEL`; `COMPUTER_USE_BACKEND`, `CUA_DRIVER_CMD`, `COMPUTER_USE_MODE`,
`COMPUTER_USE_APPROVALS`, `CUA_TELEMETRY`), all defaulting to the cautious config.py values
(in-process memory store, review-on, curation off, no-op desktop backend, telemetry off). The
context-management knobs (`CONTEXT_COMPRESS_THRESHOLD`, `PREFIX_CACHE`) read from `config.py`
defaults (compression off / prefix-cache auto) and are set via the environment when tuning is
needed. See
[traceability.md](traceability.md) (FR-MIND / FR-CUA groups) and
[dormant-surfaces.md](dormant-surfaces.md) for the reachability map.

### Production-hardening remediation (post-honest-re-audit)

An honest re-audit found the earlier traceability matrix materially **overstated**: it claimed
"all delivered" while several MUST behaviors were present-but-not-enforced, never driven, or
not persisted. The remediation below was implemented and merged; this re-audit re-verified
each against the actual `src/` code (file:line in [traceability.md](traceability.md)).

| What the audit found | How it was resolved |
|---|---|
| **Safety gates unenforced.** Review-before-submit, the automated-work dependency, mandatory decline feedback existed as rules but nothing called them. | Enforced at the service layer / dispatch boundary: `SubmissionService.ensure_submittable` → 409 (FR-RESUME-8); `require_automated_work` dependency → 409 until LLM+channels+onboarding (FR-ONBOARD-2/FR-OOBE-3); `DigestService.decline` rejects blank feedback (FR-FB-1); plus the digest-decision pending-action key bug fix. |
| **No run loop / nothing on a cadence.** Discovery, scoring, digest, escalation, pre-fill never fired on their own. | Real `AgentLoop.tick` drives the durable pipeline (registers + runs the workflow, enforces the 30/day cap, pivots/yields on blocks) + a `Scheduler` cadence advances campaigns, the daily digest, and the notification ladder; DBOS adapter activated behind the orchestration port (FR-AGENT-1/2/4/5/6/7, FR-DUR-1/2/3/4, FR-DIG-1, FR-NOTIF-2/3). |
| **Credentials / screenshots not persisted; digest email pull-only.** | `PgCredentialStore` persists libsodium-sealed rows to Postgres and a fresh instance unseals them (survives restart, FR-VAULT-1); screenshots persisted via the storage repo + migration (FR-LOG-2); digest email is actually SENT (FR-DIG-2); source-yield / converting-signature / attr-reuse producers wired (FR-DISC-5, FR-LEARN-5/6, FR-ATTR-5). |
| **Render fidelity was a passthrough; egress/redaction were seams only.** | Real docx→moderncv conversion via the vendored Jinja2 template + LaTeX escaping (FR-RESUME-3/3a/4); real `fc-cache` shell-out + auto compile/convert when the engine is present (FR-FONT-2); residential egress threaded into the real browser launch with a datacenter-refusal guardrail + honest caveat (FR-STEALTH-4/5); value-based secret redaction (FR-OBS-1); pending-action producers, criteria/attribute editor surfaces, per-task LLM tier (FR-UI-3/6, FR-LLM-4). |

### Founder-trust track — first slice (road-to-market Phase 1.5)

The master backlog is [backlog/road-to-market.md](backlog/road-to-market.md) (every story
with DoR/DoD and a live Status column); the honesty invariants H1–H5 + the PAG-1 personal
acceptance gate defined there govern launch. Landed so far:

- **Truth policy (P1-13 core, PR #643).** The fabrication guard became a server-side
  fact-gate: `TruthPolicy` (`core/rules/truthfulness.py`, `TRUTH_POLICY`) — `balanced`
  (default) surfaces flagged facts for review instead of blocking; `strict` keeps the hard
  fail. The injection / persists-nothing / bypass tests still run under strict. FE
  surfacing of flagged facts (one-tap add-to-profile) remains open.
- **Parse-verify layer (P1-1a, PR #644 — six adversarial review rounds).**
  `LLMVerifiedResumeParser` re-slots every base-résumé value through the tier ladder under
  the slotting contract: window-scoped grounding (nothing assembles across section
  boundaries), one-tier escalation on low confidence / malformed output, entry-scoped +
  heading-gated restoration (a partial correction can neither erase real history nor
  resurrect split-artifact junk), grounding holes refilled from the draft twin, per-area
  confidence validation. Live-proven repeatedly on a real résumé through the production
  ladder (both tiers observed answering; zero unsourced values; zero false restorations).
- **Honest surfacing (PR #727).** The upload response carries the persisted `verify` block
  and the wizard's post-upload message renders it: green "Double-checked" with per-area
  confidence + `corrections` + `restored_from_draft` (capped at 5 with "and N more"), or
  "Not double-checked (why)" — the absence of a check never renders as a check (H2).
- **Window-chrome baseline (P0-1, PR #640)** and the **road-to-market backlog itself
  (PR #641)** merged earlier in the same push.

## Boundaries that require a live deployment

The 26 default skips are not gaps — they exercise real external systems behind
integration-gated boundaries: DBOS/Postgres durable execution, real browser
(patchright/playwright), live job boards, real TeX (lualatex/xelatex) + LibreOffice docx
conversion, a live Neko remote session, and live Discord/SMTP delivery. The hermetic lane
proves the same logic with fakes; these run only when the toolchain/service is present.
