# FR-INTEL-2: Local Inference Envelope & Hardware-Profile Declaration

## The Hardware Envelope

The envelope captures what a local inference box **can and cannot do** as three numbers plus a modality flag:

| Metric | Description |
|---|---|
| concurrency | Max simultaneous sequences the server handles (`--max-num-seqs-seqs`) |
| ctx_cap | **Usable** context window (the A0 preset `ctx_length`, NOT the raw `max-model-len`) |
| decode_tok_s | Decode throughput (tokens/second, measured) |
| prefill_tok_s | Prefill throughput (tokens/second, measured) |
| vision | Whether the local server accepts vision/image inputs |

See `tests/unit/test_intel_envelope.py` for contract enforcement.

## Shipped Hardware Profiles

| Profile | concurrency | ctx_cap | decode_tok_s | prefill_tok_s | vision | Notes |
|---|---|---|---|---|---|---|
| reference | 2 | 96000 | 75 | 1600 | false | This building instance (§0.1) — dual TP worker |
| byo-endpoint | 1 | 32000 | 30 | 500 | false | Self-declared template defaults; user overrides at setup |
| cloud-only | 0 | 0 | 0 | 0 | false | No local tier → every step routes cloud |

> **Important:** `ctx_cap` is the **usable** A0 preset context window, not the physical `max-model-len` (which is 256000 on this deploy). The lower usable value prevents prompt overflow that would kill both TP workers.

## Known Cliff: Continuation-Prefill Scratch Buffer

The TurboQuant continuation-prefill has a CUDA-graph-fixed scratch buffer. Long prompts exceeding it can kill **both** TP workers. Mitigation: set the environment variable `VLLM_TURBOQUANT_CONTINUATION_WORKSPACE_RESERVE_TOKENS=131072` to increase the reserve.

## Routing Semantics

- **cloud-only**: `concurrency=0` → `is_local_capable()` always returns `False` → every step routes to a cloud tier.
- **reference**: Concurrency=2 means up to 2 local workers can run in parallel, as long as each stays within `ctx_cap`.
- **byo-endpoint**: Concurrency=1 means fan-out can never pair two local workers; at most one local task at a time.
