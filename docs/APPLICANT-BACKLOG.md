# Applicant — Working Backlog

**North star:** Kevin wakes to a review-ready queue of tailored, drafted job applications for high-fit roles — produced automatically, durable across a fresh install, no manual babysitting.

**Conventions**
- **DoR (Definition of Ready):** what must be true before work starts — scoped, unblocked, testable.
- **DoD (Definition of Done):** what must be true to close — fixed *in source*, committed + pushed, verified on the running 10.0.1.11 instance, and resilient to a fresh install.
- Priority: P0 = blocks the north star; P1 = quality/robustness; P2 = polish.
- Env: prod = `10.0.1.11:8000` (Applicant), model = vLLM `10.0.1.225:8000` (qwen3.6:27b). Source-of-truth branch = `claude/refactor-agent-zero-applicant-xn7xoc`.

_Last updated: 2026-08-10 (morning)_

---

## P0 — Core value: produce drafted applications

### B1 — Digest reads stored scores (unblock auto-draft) — ✅ CODE DONE, ⏳ VERIFYING
- **DoR:** Root cause confirmed (build_digest LLM-re-scored the whole backlog → digest GET timed out → auto-draft starved).
- **DoD:** `build_digest` never LLM-scores in the hot path; digest GET returns < 3s; a scheduler tick's auto-draft completes; `applications` count > 0 for the campaign; committed + pushed; survives fresh install.
- Status: committed (`005c41a5`). Needs deploy + verification that applications appear.

### B2 — Auto-register local LLM endpoint on boot — ✅ CODE DONE, ⏳ VERIFY ON FRESH INSTALL
- **DoR:** Confirmed a clean install logs `llm_router_no_endpoints` because the endpoint pool is empty (tier ladder alone doesn't populate it).
- **DoD:** On first boot with `llm_configured`, an endpoint is auto-registered from `settings.llm_base_url`; `endpoints_online >= 1` without manual action; idempotent; verified by clearing endpoints + rebooting (or on the next fresh install).
- Status: committed (`005c41a5`). Verify on a fresh boot with empty pool.

### B3 — vLLM stops wedging (qwen-only router) — ✅ DONE (Kevin infra)
- **DoR:** Confirmed GLM model-swaps wedge the shared router (health OK / completions hang), taking down Applicant + Hermes.
- **DoD:** Router never swaps; qwen stays loaded; no re-wedge under load; backup kept.
- Status: `~/.local/share/vllm-qwen27b/model-router.py` → `backend_for` returns qwen always; restarted; verified. NOTE: this is Kevin's box, not the Applicant repo.

### B4 — Engine resilient to vLLM flakiness under load — ⏳ TODO (P0/P1)
- **DoR:** Observed 500s/timeouts when the engine hammers vLLM scoring the backlog (thundering herd).
- **DoD:** Scoring uses bounded concurrency + retry/backoff so a transient 500/timeout doesn't drop a posting to embedding-only; steady-state scoring drains the backlog without saturating vLLM; verified scored-count climbs steadily.

### B5 — End-to-end proof: Kevin sees drafts in the UI — ⏳ TODO (the real DoD)
- **DoR:** B1–B2 verified (applications exist in DB).
- **DoD:** Open Today/Digest as a user → a review-ready queue of tailored applications (resume variant + cover letter + screening answers) for high-fit roles renders; each is DIGESTED/review-gated (never auto-submitted). Screenshotted.

---

## P1 — Robustness & correctness

### B6 — Rebuild prod from source (bake all fixes durably) — ⏳ TODO
- **DoR:** All P0 source fixes committed.
- **DoD:** a0 + api images rebuilt from HEAD (sequential/OOM-safe), migration run, stack recreated, data intact, no hot-patches remain; `git rev-parse HEAD` on the build source == origin HEAD.

### B7 — model_endpoints proxy JSON→Form mismatch — ⏳ TODO
- **DoR:** Confirmed engine `add_endpoint`/`test_endpoint` use `Form(...)` but the plugin proxy sends JSON → UI "Add endpoint" fails.
- **DoD:** UI can add + test an endpoint successfully (proxy sends form-encoded OR engine accepts JSON body); verified via the panel.

### B8 — Shared-session IllegalStateChangeError — ⏳ TODO
- **DoR:** Confirmed nested `commit()` (scheduler thread + HTTP request sharing the boot Session) 500s `POST /api/onboarding/{cid}/shown`.
- **DoD:** No `IllegalStateChangeError` in logs under concurrent load; onboarding "shown" returns 2xx; fix uses per-thread/scoped sessions or a guard; regression test.

### B9 — Discovery scoring backlog drains — ⏳ TODO
- **DoR:** ~5376 discovered, only ~1176 scored.
- **DoD:** Background scorer works through the backlog to near-complete; `scored` approaches `postings`; viable set (≥70) grows; verified over time with vLLM stable.

---

## P2 — Branding & polish (found by the visual monkey-crawl)

### B10 — "AGENT ZERO" branding regression — ⏳ TODO
- **DoR:** Visual crawl shows the sidebar logo renders the base agent-zero wordmark; `.js` files leak "Agent Zero"; overlay lacks branded logo SVGs.
- **DoD:** Logo reads "Applicant" (branded `a0-fullDark.svg`/`a0-collapsed.svg` in overlay); `apply-branding.sh` also rewrites `.js`; no visible "Agent Zero" on any user-facing page; verified in a screenshot; baked into the image.

### B11 — Off-brand upstream welcome cards — ⏳ TODO
- **DoR:** Root page shows base `_discovery` plugin cards (Connect WhatsApp/Telegram, Codex/Grok AI accounts) irrelevant to job search.
- **DoD:** Root page shows only Applicant-relevant content (Today + chat); upstream welcome cards hidden/removed cleanly; verified in a screenshot; durable.

### B12 — Modals show raw file path as title — ⏳ TODO
- **DoR:** Every panel modal titles as e.g. `/plugins/applicant/webui/digest.html`.
- **DoD:** Modals show a friendly title (e.g. "Daily Digest"); verified across panels.

### B13 — Full visual QA re-pass — ⏳ TODO
- **DoR:** B1–B12 addressed.
- **DoD:** Re-run the visual crawl; every user-facing page reviewed as a user; no rendering/empty-state/branding defects; report + screenshots.

---

## Done this cycle (for the record)
- Latest build pushed to GitHub (was ~370 commits behind) — remote/prod match HEAD.
- Rebuilt prod from source (durable, migration applied, data intact).
- UI monkey crawl: 23 broken panels → 0 (campaigns API shape, undefined `callJsonApi`, Alpine x-for crashes, `/api/setup/automation` 404, tiers config path).
- LLM pipeline diagnosed + restored (vLLM unwedged, endpoint registered, tiers online).
