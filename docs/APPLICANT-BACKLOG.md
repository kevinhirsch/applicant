# Applicant — Working Backlog

**North star:** Kevin wakes to a review-ready queue of tailored, drafted job applications for high-fit roles — produced automatically, durable across a fresh install, no manual babysitting.

**Conventions (STANDING — every item MUST carry all three):**
- **DoR** (Definition of Ready): scoped, unblocked, testable; failing tests/scenarios can be written first.
- **AC** (Acceptance Criteria): written as **BDD** Gherkin `Given/When/Then` scenarios — these are the executable spec.
- **DoD** (Definition of Done): fixed *in source*, committed + pushed, **all AC scenarios green**, verified on the running 10.0.1.11 instance, resilient to a fresh install.
- **Delivery = full TDD + BDD (STANDING).** Write the failing unit test (TDD) and the failing BDD scenario (AC) BEFORE the implementation; red → green → refactor. No item is Done without both green.
- **Priorities:** P0 blocks the north star; P1 robustness; P2 polish.
- **Fully-agentic product (STANDING):** the human NEVER has to fix the product. Anything the system can detect deterministically, the system must be able to remediate agentically (see EPIC SELF-HEAL / ADR-0008).

**STANDING PRINCIPLE — reuse-first, no redundancy (ONGOING):** Never build a component, service, or endpoint that duplicates one that already exists — reuse it. A new UI view is a THIN layer over existing data/actions (e.g. landing-page gadgets read the same scored Digest data + reuse the same review actions; they do not re-derive them). Any new endpoint/service must justify why an existing one didn't suffice. Check for redundancy in EVERY review (use `/simplify`) — a component that re-implements or re-derives what another already provides is a defect, and features silently drift/drop between the copies (e.g. the match-score badge lost when Pending Reviews forked from the Digest).
Env: prod `10.0.1.11:8000` · model vLLM `10.0.1.225:8000` (qwen3.6:27b) · branch `claude/refactor-agent-zero-applicant-xn7xoc`.

_Last updated: 2026-08-10 (midday)_

---

## 🧱 EPICS

### EPIC SELF-HEAL — Autonomous self-healing (deterministic detection → agentic remediation; human NEVER fixes) · see ADR-0008
**Principle:** The product detects its own failures **deterministically** (typed health checks / invariants / error signatures / watchdogs) and invokes an **AI agent with full tool access** to troubleshoot and correct them at runtime. The human is *never* required to fix the product — the AI does all the fixing because it has all the tools. Includes: **the remote/cloud LLM repairs the local LLM** when the local model is degraded/unavailable/wedged. This is a **fully agentic product**. (Officially: *self-healing system / autonomous closed-loop remediation / agentic auto-remediation*.)

- **DoR:** ADR-0008 accepted (detection signals catalogued; remediator authority + guardrails defined; remote→local repair path specified; audit + fail-safe defined); each slice scoped with BDD AC; fault-injection harness identified.
- **AC (BDD — executable spec):**
  - *Remote-repairs-local:* **Given** the local LLM is wedged/unreachable, **When** an inference/scoring call fails deterministically, **Then** the system escalates inference to the remote LLM **and** triggers a remediation action that restores the local LLM (e.g. restart/reload/reconfigure), with zero human action, and records an audit entry.
  - *Detect→remediate loop:* **Given** a deterministic error signature fires (panel JS error, migration failure, endpoint 5xx, stuck/starved queue, scorer degrade-to-embeddings, discovery circuit-open), **When** it is detected, **Then** an AI remediator is invoked with tools to diagnose + correct, and the action + outcome are audited.
  - *Bounded + fail-safe:* **Given** remediation is attempted, **When** N bounded retries are exhausted, **Then** it fails safe (degrade + alert), never loops infinitely, never loses data.
  - *Guardrails inviolable:* **Given** any remediation, **Then** no user application is ever auto-submitted and no user data is ever deleted as a side effect (the safety rails hold even inside self-repair).
  - *No-human-required:* **Given** any failure class covered by a detector, **When** it occurs unattended overnight, **Then** the product returns to a healthy state with no human intervention, evidenced by the audit trail.
- **DoD:** deterministic detectors for the known failure classes emit typed events; an agentic remediator consumes them and applies bounded, audited corrective actions via available tools; remote LLM can repair the local LLM; all guardrails enforced; **TDD unit + BDD scenario coverage green**; verified on 10.0.1.11 by **fault injection** (e.g. kill vLLM → system self-recovers, drafting resumes, zero human action); resilient across a fresh install. Delivered in slices, each independently meeting DoR/AC/DoD.
- **First slices (candidates):** S1 remote-repairs-local LLM (compose w/ MODEL-RESILIENCY fallback tier already in flight); S2 detector bus + audit store; S3 scorer-degrade self-heal (re-score poisoned postings automatically); S4 panel-error self-heal; S5 stuck-queue / idle-txn self-heal.

## ✅ DONE + verified this cycle (P0/P1)

- **B1 Digest reads stored scores** — build_digest no longer LLM-re-scores in the hot path. Committed + baked. (Part of the perf story below.)
- **B2 Auto-register local LLM endpoint on boot** — a fresh install now gets a working chat/routing endpoint with no manual step. Verified `endpoints_online: 1` on a clean boot.
- **B3 vLLM stops wedging** — router is qwen-only (GLM swaps disabled); no re-wedge. (Kevin's box, backup kept.)
- **B4 Bound per-tick scoring + digest perf (the thundering-herd)** — scorer walked the whole 4k backlog every tick AND build_digest did 266 full posting-scans per build (167s). Fixed: per-tick scoring cap (SCORING_BATCH_PER_TICK, default 20) + hoisted the campaign-wide reads out of the per-row warnings loop. **Digest 167s → 1.5s warm.** Verified.
- **B6 Rebuild prod from source** — api rebuilt from HEAD, migration applied, data intact; all fixes baked. (a0 rebuild pending the landing page.)
- **RESEARCH-400 (owner attribution)** — engine never sent `X-Applicant-Owner`; companion 400'd every callback. Fixed via `default_owner` (APPLICANT_OWNER, default "applicant") — clears research + calendar/emails/memory lanes. Committed + baked.
- **Latest build on remote** — all 370+ commits pushed to GitHub; prod == HEAD (was ~370 behind).
- **UI monkey crawl** — 23 broken panels → 0 (campaigns API shape, undefined callJsonApi, Alpine x-for crashes, /api/setup/automation 404, tiers config path). Committed + baked.
- **Self-drafting works** — 5 DIGESTED drafts for top-fit roles with genuinely tailored materials (verified real Wells Fargo/Slalom/Ally content); Today shows a 22-item review queue. Review-gated, never auto-submitted.

## ✅ DONE this cycle (cont.)

- **APP-LP-1 Landing-page overhaul** — DONE + verified (`4ee732e1`). Command-center root: Pending Reviews (score badges, sorted best-fit, inline Review/Approve/Snooze) → Top New Matches (score + why + Draft/Skip) → Pipeline Funnel → Daily Progress → notifications-connect + System Resources; clutter cut; chat kept. Reused digest/pending endpoints; 1 justified new endpoint (pipeline-summary). Contrast measured (5–11:1) light+dark; **also fixed an app-wide light-mode theme freeze** (buttons/badges/cards) + the sidebar white-on-white + the branding logo. Delivers B5 (review UX). Baked (a0+api image rebuild).

## 🔜 IN PROGRESS (delegated agents, overseer integrates+deploys)

- **SCORE-P0 — transient LLM failure poisons viability scores (FROZEN PIPELINE).** *Root-caused 2026-08-10 midday.* Live: 5376 postings / 1266 scored / **0 viable (>=70)** → auto-draft starved → review queue frozen at 4 old drafts. Cause: `scoring_service._base_score` catches any LLM exception (cold-start/loaded-vLLM call >60s HTTP timeout) and **degrades to embedding similarity, which ~never reaches 70, then persists it** — and `agent_loop` only scores UNSCORED postings, so the poisoned score is never retried. Config is CORRECT (tier qwen3.6:27b @10.0.1.225/v1; a warm `complete()` scores real roles 75-85). **DoR:** root-caused w/ file anchors; config confirmed good. **DoD:** (1) transient LLM failure leaves posting UNSCORED/retryable (never persist embedding score when an LLM is configured) w/ bounded-retry safety valve; (2) LLM HTTP timeout raised + env-configurable + defaulted in compose; (3) test proving it; committed. THEN overseer: deploy + live re-score of poisoned postings + verify viable>0 + queue grows. *(Agent running.)*
- **MODEL-RESILIENCY — local-primary + deterministic DeepSeek(-compatible) cloud FALLBACK tier.** Kevin: "if local fails or is unavailable, deterministic fallback to DeepSeek API (or compatible endpoint), IN ADDITION to the existing auto-escalation." Folded into SCORE-P0 (same ladder subsystem; a real fallback tier is the robust cure — the ladder climbs to cloud on local failure instead of degrading to embeddings). **DoD:** ladder holds local-primary + optional cloud tier, env-configured (`LLM_FALLBACK_BASE_URL`/`_MODEL`/`_API_KEY`/`_PROVIDER`, default DeepSeek), OFF without a key (byte-identical to today), dropped under private/local-only mode, appended so existing escalation uses it; unit test; compose vars. THEN overseer: drop the real key on the box + activate + verify escalation live. Key exists in A0 stack (secret-injected; Kevin to supply the value — never handled in chat). *(Folded into running agent.)*
- **APP-LP-2 — posting date + freshness on Pending Reviews / role cards.** Kevin: a high-fit role posted a month ago is probably filled; the posted date is decision-critical. **DoR:** job_postings has a date field to surface. **DoD:** posted date + relative-freshness cue on every scored Pending Review row + Digest/Top-Matches cards, both themes, stale roles visually de-emphasized, reuses existing payload (no redundant endpoint), graceful when unknown; committed. *(Agent running.)*
- **APP-UIKIT-1 — design-system / UIKit standard (P2, "nice to have").** Kevin wants codified color/contrast/HIG standards for future UI consistency. **DoD:** `docs/UIKIT-STANDARDS.md` derived from real source (theme tokens light+dark, `.light-mode` leak trap, typography/spacing, component patterns, WCAG/HIG targets + do/don'ts, recipes + pre-ship checklist), file-cited; committed. *(Agent running.)*

- **DISCOVERY-BREADTH (P1, CRITICAL-TO-QUALITY) — maximize job-posting reach across the internet.** Kevin: "widen the net to as full a reach as I possibly can get — the most postings possible gives me the most edge." Baseline today = jobspy (US-remote) + 25 Greenhouse boards + 10 Lever companies. **DoR:** current discovery architecture mapped (sources, connector framework, dedup, circuit breaker, scheduling); candidate sources cataloged with feasibility (keyless vs keyed/API, anti-bot difficulty, cost); prioritized expansion plan w/ BDD AC. **AC (BDD):** (a) *Given* the expanded source set enabled, *When* a discovery cycle runs, *Then* unique postings ingested increases materially vs baseline (target Nx) from many more sources; (b) *Given* multiple sources return the same role, *Then* it is deduped (no double drafts); (c) *Given* a source is down/rate-limited/anti-bot-blocked, *Then* the circuit breaker isolates it and others continue (ties to SELF-HEAL); (d) *Given* a new source type, *Then* it plugs into the EXISTING connector framework (no bespoke one-off, reuse-first). **DoD:** expanded sources live + ingesting on 10.0.1.11; unique-posting count materially up; dedup + circuit-breaker resilience verified; TDD+BDD green; source config in repo/compose (fresh-install resilient). *(Scoping agent running; build in the post-P0 wave.)* See [[Applicant — ATS Discovery Connectors]].
- **Tech-Debt burn-down (PARALLEL, overseer)** — audit DONE → `docs/TECH-DEBT-REGISTER.md` (128 items: 21 UNEXPOSED / 18 PARTIAL / 7 DUP / 7 UNWIRED; 4 P0). Now: parallel per-domain FIX agents (isolated worktrees, commit only) → coordinator cherry-picks + ONE batched rebuild/deploy → verify. Covers the 4 P0s (base-résumé overwrite, easy-apply consent, model-endpoint JSON/Form=B7, ops-allowlist recovery) + P1 UNEXPOSED/PARTIAL + DUP. Deferred to a later serial wave: the 18-file `_engine_client` consolidation (conflicts with everyone).

### Landing page (APP-LP-1 shipped) — open follow-ups
- [ ] channels.html "Current configuration" display reads response fields the API no longer returns (now `*_configured` booleans, by design) — fix the display. (Agent-flagged, pre-existing.)
- [x] Coordinator live **light-mode self-verify** — DONE 2026-08-10: captured fresh live light + dark full-page from the deployed build, both fully readable (no white-on-white), match score restored on Pending Reviews, 0 console errors; screenshots sent to Kevin.
- [ ] Post-burndown **full visual re-pass** (light+dark, all panels) once fixes land.

## ⏳ TODO

- **B4-deep (P2)** digest cold build still ~15s (first call after restart / cache-invalidation); warm is 1.5s. Optional: warnings only need the ~5 apps' postings, not all 5376 — make it size-independent.
- **RESEARCH-503 (P1)** with owner fixed, `/research` now 503s: the COMPANION has no research/default LLM endpoint. Mirror the engine's auto-register on the companion so research enrichment actually runs. (Enrichment only — not a draft blocker.)
- **B7 (P1) model_endpoints proxy JSON→Form** — engine `add_endpoint` uses Form; the plugin proxy sends JSON → UI "Add endpoint" fails. (Endpoint auto-registers now, so lower urgency.)
- **B8 (P1) idle-in-transaction sessions** — boot/tick sessions leave transactions open (ClientRead ~6 min), blocking VACUUM on job_postings. (NOT the digest cause — that was the per-row scans, fixed. Separate hygiene item.)
- **B10 branding (P2)** — logo wordmark + `.js` substitution done in source; bakes on the next a0 rebuild (landing-page agent's rebuild). Verify no "Agent Zero" post-bake.
- **B12 (P2) modal titles show raw file paths** (e.g. `/plugins/applicant/webui/digest.html`) — give panels friendly titles.
- **B13 (P2) full visual QA re-pass** — after landing page + branding land, re-run the visual crawl in light + dark.
- **UI-DEBT-1 (P1 contrast, from UIKIT audit `e1009e937`)** — real WCAG fails found by cascade analysis: `--color-text-secondary` (#5a5a5a, one literal shared by both themes) = **2.7:1 on dark** (fail), used in nearly every panel's meta text; dark-mode primary buttons **4.35:1** (borderline AA); `.card/.item/.surface` inherit `--ap-color-text` + `--color-input-bg:#fff` declared only at `:root` (no `.light-mode` counterpart) → potential white-on-white card in dark default (static-analysis, **not yet screen-confirmed** — my live shots looked OK, so verify before fixing). **DoR/AC/DoD + TDD/BDD** per standing conventions. Fix = theme-scoped tokens per UIKIT-STANDARDS.md.
- **UI-DEBT-2 (P2, from UIKIT audit)** — three divergent status-badge color paths (canonical tokens vs `digest.html` typo'd `--color-warn-bg` that never resolves vs `documents.html` hardcoded literals); + design tokens adopted by 0/41 panels (all hardcode raw px/rem). Consolidate onto the UIKIT scale. Standing conventions apply.
- ~~**New-draft quality re-check (P1)**~~ — DONE 2026-08-10: verified live materials are real LLM-tailored content (cover letters avg 1721 chars w/ role-specific rationale; screening answers present; work-auth answers correctly use stored policy, never guessed). NOT deterministic fallback.

## Done earlier (foundation)
- Fresh install on 10.0.1.11; campaign recreated; OOM root-caused (sequential builds); install/update system + fork-safe Update button; discovery resilience (Greenhouse/Lever + circuit breaker).
