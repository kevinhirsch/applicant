# Applicant — Working Backlog

**North star:** Kevin wakes to a review-ready queue of tailored, drafted job applications for high-fit roles — produced automatically, durable across a fresh install, no manual babysitting.

**Conventions** — DoR: ready to start (scoped, unblocked, testable). DoD: fixed *in source*, committed + pushed, verified on the running 10.0.1.11 instance, resilient to a fresh install. P0 blocks the north star; P1 robustness; P2 polish.

**STANDING PRINCIPLE — reuse-first, no redundancy (ONGOING):** Never build a component, service, or endpoint that duplicates one that already exists — reuse it. A new UI view is a THIN layer over existing data/actions (e.g. landing-page gadgets read the same scored Digest data + reuse the same review actions; they do not re-derive them). Any new endpoint/service must justify why an existing one didn't suffice. Check for redundancy in EVERY review (use `/simplify`) — a component that re-implements or re-derives what another already provides is a defect, and features silently drift/drop between the copies (e.g. the match-score badge lost when Pending Reviews forked from the Digest).
Env: prod `10.0.1.11:8000` · model vLLM `10.0.1.225:8000` (qwen3.6:27b) · branch `claude/refactor-agent-zero-applicant-xn7xoc`.

_Last updated: 2026-08-10 (midday)_

---

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

## 🔜 IN PROGRESS

- **APP-LP-1 Landing-page overhaul** — signed off (`docs/stories/landing-page-overhaul.md`). Dedicated build agent implementing: 4 gadgets (Pending Reviews, Top New Matches, Pipeline Funnel, Daily Progress) in priority order, act-inline + keep chat, cut AI-accounts/Channels clutter, keep notifications + System Resources. Browser-verified, baked. **This delivers B5 (end-to-end review UX).**

## ⏳ TODO

- **B4-deep (P2)** digest cold build still ~15s (first call after restart / cache-invalidation); warm is 1.5s. Optional: warnings only need the ~5 apps' postings, not all 5376 — make it size-independent.
- **RESEARCH-503 (P1)** with owner fixed, `/research` now 503s: the COMPANION has no research/default LLM endpoint. Mirror the engine's auto-register on the companion so research enrichment actually runs. (Enrichment only — not a draft blocker.)
- **B7 (P1) model_endpoints proxy JSON→Form** — engine `add_endpoint` uses Form; the plugin proxy sends JSON → UI "Add endpoint" fails. (Endpoint auto-registers now, so lower urgency.)
- **B8 (P1) idle-in-transaction sessions** — boot/tick sessions leave transactions open (ClientRead ~6 min), blocking VACUUM on job_postings. (NOT the digest cause — that was the per-row scans, fixed. Separate hygiene item.)
- **B10 branding (P2)** — logo wordmark + `.js` substitution done in source; bakes on the next a0 rebuild (landing-page agent's rebuild). Verify no "Agent Zero" post-bake.
- **B12 (P2) modal titles show raw file paths** (e.g. `/plugins/applicant/webui/digest.html`) — give panels friendly titles.
- **B13 (P2) full visual QA re-pass** — after landing page + branding land, re-run the visual crawl in light + dark.
- **New-draft quality re-check (P1)** — with scoring bounded + vLLM headroom, confirm NEW auto-drafts come back LLM-tailored (not deterministic fallback).

## Done earlier (foundation)
- Fresh install on 10.0.1.11; campaign recreated; OOM root-caused (sequential builds); install/update system + fork-safe Update button; discovery resilience (Greenhouse/Lever + circuit breaker).
