# Study: LLM parse-verify layer over the deterministic résumé parse

**Date:** 2026-07-07 · **Status:** complete · **Feeds:** P1-1a (verify layer), P1-13
(truth policy), the model-tiering ladder.

## Question

Can the model-tier ladder's **free local floor** (qwen3.6-27b) reliably "slot" a real
résumé — correct the deterministic parser's draft so every value lands in the right
field — or does this task require escalation (GLM 5.2 / DeepSeek) as the owner
anticipated? And do models *invent* values while doing it?

## Method

- **Input:** the owner's real résumé (a modern, multi-column, sidebar-style PDF — the
  exact document class the deterministic parser struggles with).
- **Draft:** the deterministic parser's output *after* the PR #642 hardening.
- **Task:** given SOURCE (raw text) + DRAFT (JSON), return a corrected parse under a
  strict schema: contact, work history (title/company/location/dates), education
  *including certifications and school*, skills — plus per-area confidence 0–1 and a
  corrections list. Temperature 0.
- **Scoring:** hand-built ground truth from the actual PDF. Contact (3 checks), roles
  (4 roles × 4 fields = 16), education/certs (7 known entries), skills (9 known tools).
  **Fabrication counter:** any output string not present in the source text (normalized
  substring match) counts as invented.
- One attempt per model; a follow-up attempt for the floor model after a settings fix.

## Results

| Model | Contact | Roles | Edu/Certs | Skills | Invented strings | Latency | Tokens |
|---|---|---|---|---|---|---|---|
| qwen3.6-27b (reasoning **on**, default) | — | — | — | — | — | 50.6s | 2935+4000 — **failed**: spent the whole 4k budget on reasoning tokens, empty content |
| **qwen3.6-27b (reasoning off)** | 3/3 | **16/16** | **7/7** | 9/9 | **0** | **16.0s** | 2937+1212 |
| GLM 5.2 | 3/3 | 16/16 | 7/7 | 9/9 | 0 | 46.1s | 2696+3014 |
| DeepSeek V3.2 | 3/3 | 16/16 | 7/7 | 9/9 | 0 | 33.7s | 2701+1069 |
| Sonnet 5 (ceiling reference) | 3/3 | 16/16 | 7/7 | 9/9 | 0 | 24.5s | 4431+2813 |

Cost per verify call was on the order of **$0.01** via the router; effectively $0 when
the floor model runs locally.

## Findings

1. **The free local floor is sufficient for parse-verify.** qwen3.6-27b produced a
   *perfect* corrected parse — fastest of all four — once reasoning was disabled.
   No escalation required for this task.
2. **The one deployment trap is reasoning mode.** With default reasoning on, the same
   model burned its entire completion budget thinking and returned nothing. The verify
   layer MUST disable/cap reasoning (or budget far above it) for structured-output calls.
3. **Zero fabrication across all four models.** Told "every output string must exist in
   the source," no model invented a single value while re-slotting. The slotting task is
   safe to run autonomously; escalation triggers (malformed JSON, low confidence) are the
   right guardrail, not human ceremony.
4. **Confidence fields work as an escalation signal.** All models self-reported per-area
   confidence (0.9–1.0 on this clean input); the P1-1a wiring should escalate below ~0.8
   or on schema violations.

## Decisions taken

- **P1-1a:** wire the verify layer into onboarding ingest — deterministic parse →
  local-floor verify (reasoning off) → escalate one tier on low confidence / malformed
  output. Offline fallback = deterministic parse + a visible "not verified" notice.
- **Tier ladder confirmed** for this workload: local qwen floor → GLM 5.2 / DeepSeek →
  frontier ceiling, gated by *studies like this one* per workload class.
- **Next study:** tailoring/rewrite quality (feeds P2-6 eval harness) — the same
  method, applied to the generation side under the P1-13 truth policy.
