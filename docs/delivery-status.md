# Delivery Status

Single source of "done" truth: a per-phase delivery summary for the Applicant engine.
**All five phases (0–4) are implemented and merged to `main`.** The hermetic default test
lane is green — `uv run pytest -q` reports **539 passed** with 10 integration-gated skips.

See [traceability.md](traceability.md) for requirement-level coverage and
[work-packages.md](work-packages.md) for the original phase plan and exit criteria.

## Test count progression

| Milestone | Tests passing |
|---|---|
| Phase 0 | 191 |
| Phase 1 | 264 |
| Phase 2 | 339 |
| Phase 3 | 425 |
| Phase 3b (durable revision sessions) | 480 |
| Phase 4 | **539** |

(10 integration tests skip by default — they require live external boundaries.)

## Per-phase summary

### Phase 0 — Foundation, OOBE, durability (191 tests)
**Delivered:** hexagonal skeleton (core/ports/adapters), provider-agnostic LLM port
(OpenAI-compatible + Ollama) with tier ladder and escalation, zero-CLI setup wizard
(LLM-gate first), resumable onboarding intake, resume parser bootstrapping the attribute
cloud, font management, durable orchestration port (file-backed `shim` default + DBOS
adapter), structlog observability with correlation IDs + redaction, vendored Odysseus UI
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
**Exit criteria:** met — every FR-*/NFR-* requirement is delivered; no remaining gaps.

## Boundaries that require a live deployment

The 10 default skips are not gaps — they exercise real external systems behind
integration-gated boundaries: DBOS/Postgres durable execution, real browser
(patchright/playwright), live job boards, real TeX (lualatex/xelatex), live Neko remote
session, and live Discord/SMTP delivery. The hermetic lane proves the same logic with fakes.
