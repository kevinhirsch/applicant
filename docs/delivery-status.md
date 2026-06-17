# Delivery Status

Single source of "done" truth: a per-phase delivery summary for the Applicant engine.
**All five phases (0–4) are merged to `main`, plus a production-hardening remediation pass
that followed an honest re-audit.** The hermetic default test lane is green —
`uv run pytest -q` reports **613 passed** with 14 integration-gated skips.

See [traceability.md](traceability.md) for the re-verified requirement-level coverage and
[work-packages.md](work-packages.md) for the original phase plan and exit criteria.

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
| Production-hardening re-audit (current) | **613** |

(14 integration tests skip by default — they require live external boundaries.)

## What is and isn't proven by the test suite

The **613 hermetic tests prove the logic** of every requirement against fakes / in-memory
adapters — gates, state transitions, learning math, escalation cadence, sealing/unsealing,
conversion rendering, etc. They do **not** exercise the real external boundaries end-to-end;
the **14 integration-gated skips** cover those and run only on a live deployment with the
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
adapter), structlog observability with correlation IDs + redaction, vendored Applicant UI
shell with grayed dormant surfaces, truthfulness / em-dash / confirmation-gate core rules.
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
code; the only un-exercised paths are the integration-gated boundaries above (environment
dependencies, not requirement gaps).

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

## Boundaries that require a live deployment

The 14 default skips are not gaps — they exercise real external systems behind
integration-gated boundaries: DBOS/Postgres durable execution, real browser
(patchright/playwright), live job boards, real TeX (lualatex/xelatex) + LibreOffice docx
conversion, a live Neko remote session, and live Discord/SMTP delivery. The hermetic lane
proves the same logic with fakes; these run only when the toolchain/service is present.
