# Intel Routing — Deterministic local↔remote context-sizing (FR-INTEL-3)

## Overview

Pure, deterministic routing module (`routing.py`) that estimates token count and selects a compute tier (`LOCAL`, `LOCAL-SINGLE`, or `CLOUD`) based on hardware-profile thresholds. No model calls, no network I/O, no engine logic.

## Thresholds (Three Bands)

Thresholds are derived from the hardware profile's `ctx_cap` and `concurrency` fields (read from the envelope module). The reference profile (`concurrency=2`, `ctx_cap=96000`) produces these bands:

| Recommendation  | Token Range          | Concurrency | Why                                   |
|-----------------|----------------------|-------------|---------------------------------------|
| `LOCAL`         | 0 .. <40,000         | Profile     | Below dual-local ceiling; concurrent OK |
| `LOCAL-SINGLE`  | 40,000 .. 90,000     | 1           | Above dual cap; run alone             |
| `CLOUD`         | >90,000              | 0           | Exceeds local single-cap; route to cloud |

### Threshold Derivation

- `base_tokens` default: **9,000** (fixed system-prompt + tool-schema budget added to every estimate).
- `local_single_below` = `ctx_cap` - `headroom` (reference: 96,000 - 6,000 = **90,000**).
- `local_dual_below` = **40,000** (fixed default, ≈ `ctx_cap` × 0.42 floor).

### Cloud-Only Collapse

A profile with `concurrency == 0` (e.g., `cloud-only`) always routes to `CLOUD`, regardless of token estimate. The `split_hint` recommends splitting oversized work into `<40,000`-token local chunks.

## Split Fallback

When a task exceeds the local single-cap, the recommendation is `CLOUD` and `split_hint` suggests splitting inputs into chunks under 40,000 tokens for local execution on the dual-capable tier.

## Deterministic / Pure

`estimate_tokens()` is a pure function using a **chars/4 heuristic** — not a real tokenizer. Same inputs always produce the same integer. No randomness, no model call, no network access.

## Files

| File | Purpose |
|------|---------|
| `src/applicant/ports/intel/routing.py` | Pure routing module |
| `tests/unit/test_intel_routing.py` | Hermetic test suite (11+ tests) |
