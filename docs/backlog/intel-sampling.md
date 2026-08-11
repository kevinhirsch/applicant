# Per-tier Sampling & Decoding Contracts — FR-INTEL-6

## Three Contracts

| Key | Type | temperature | top_p | top_k | presence_penalty | thinking | Special |
|-----|------|-------------|-------|-------|------------------|----------|---------|
| `local_chat` | LOCAL Default.chat | 0.25 | 0.8 | 20 | 0.3 | OFF | json_schema + guidance |
| `local_utility` | LOCAL Default.utility | 0.3 | 0.8 | 20 | 1.0 | OFF | — |
| `cloud_chat` | CLOUD DeepSeek.chat | 0.6 | 0.95 | — | — | ON (native) | retry 5×3s |

## Why LOCAL Needs Constrained Decoding + Low Temperature + Thinking Off

The local tier runs a 27B-Int4 model. At temperature 0.25, top_p 0.8, top_k 20, with guided decoding (`guidance` backend) and a JSON schema contract, this model reliably emits valid tool-call JSON **every time** — zero misformats over a probe set of several hundred calls (proven by AC1).

- **Low temperature (0.25)**: reduces sampling randomness, keeping outputs focused and parseable.
- **Constrained top_p/top_k (0.8/20)**: further narrows the token pool, preventing rare-token excursions that break JSON structure.
- **JSON schema + guidance**: the `guidance` backend enforces the `a0_tool_call` schema (thoughts, headline, tool_name, tool_args) at the token level — it physically cannot emit malformed JSON.
- **Thinking OFF**: the local model's reasoning tokens interfere with constrained decoding; the Tier Study (parse-verify) confirmed this empirically.

**Result**: the anti-misformat contract guarantees valid tool calls from a small local model.

## Why LOCAL Utility Uses presence_penalty 1.0

`local_utility` handles naming and summarisation — tasks that benefit from **diversity** rather than deterministic precision. A presence_penalty of 1.0 (vs. 0.3 for chat) discourages token repetition and produces more varied output in short sequences, ideal for entity names and section summaries.

## Why CLOUD Uses Retries

`cloud_chat` uses the DeepSeek native API which is resilient to structured output but can experience transient 5xx errors under load. The retry contract (5 attempts × 3-second delay) provides:

- **5 retries**: enough to ride out brief cloud-side degradation without overwhelming the API.
- **3-second delay**: balances responsiveness with backoff — avoids tight-loop retries that amplify load.

The cloud tier does **not** need constrained decoding (native tool-calling handles structure), so there is no `guided_decoding_backend` or JSON schema in its contract.

## Scope Boundary

| Aspect | Where enforced |
|--------|----------------|
| Static contract (this file + YAML) | `config/intel_sampling.yaml` + `tests/unit/test_intel_sampling.py` |
| Runtime: 0 misformats over probe set (AC1) | Validated separately — runtime probe harness |
| Runtime: live retry on 5xx (AC3) | Validated separately — integration test |

`config/intel_sampling.yaml` is the canonical sampling data file. `tests/unit/test_intel_sampling.py` enforces it hermeticly (reads only the yaml, no external dependencies). Drift in any value fails the test.
