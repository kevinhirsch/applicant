# Intel Tier Topology — FR-INTEL-1

## Three Tiers

| Tier | Locality | Description |
|------|----------|-------------|
| `local-fast` | local | Local Qwen-class inference for high-volume execution work |
| `cloud-flash` | remote | Fast cloud (DeepSeek flash) for planning, review, security audit |
| `cloud-pro` | remote | Max-intelligence cloud (DeepSeek pro) for debugger/escalation |

## Nine Reference Profiles

| Profile | Preset | Model | Tier | Locality |
|---------|--------|-------|------|----------|
| agent0 | DeepSeek-Chat | deepseek-v4-flash | cloud-flash | remote |
| coder | Default | Qwen3.6-27B | local-fast | local |
| explorer | Default | Qwen3.6-27B | local-fast | local |
| test-engineer | Default | Qwen3.6-27B | local-fast | local |
| coder-cloud | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | remote |
| explorer-cloud | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | remote |
| reviewer | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | remote |
| security-auditor | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | remote |
| debugger | DeepSeek-Pro | deepseek-v4-pro | cloud-pro | remote |

## Why agent0 is Cloud-Bound

The overseer (agent0) is pinned to `cloud-flash` because planning, decomposition, and verification judgment are remote-only reasoning work. This enforces the "think-here-build-there" discipline: the cloud brain plans and reviews; the local tier executes.

## Plane A / Plane B Boundary

- **Plane A** (this contract): governs shell/agent models — the models that run Agent Zero itself, its subordinate agents, and tool-calling. Defined in `config/intel_tiers.yaml`.
- **Plane B**: the engine tier-ladder — model routing for the applicant engine's LLM calls (panel inference). Governed separately. This contract does NOT constrain Plane B.

## Enforced Contract

`config/intel_tiers.yaml` is the canonical topology data file. `tests/unit/test_intel_tier_topology.py` enforces it hermeticly (reads only the yaml, no external dependencies). The test asserts tier count, profile count, tier-to-locality consistency, per-profile ground-truth equivalence, agent0's cloud binding, preset referential integrity, and the exact cloud-preset set.
