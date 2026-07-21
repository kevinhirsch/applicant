# Two-Plane Reconciliation Contract (FR-INTEL-7)

## Capability → Plane Table

| Plane | Owner | Capabilities |
|-------|-------|--------------|
| **Plane A** (Shell/Agent) | FR-INTEL suite | `agent0`, `coder`, `explorer`, `test-engineer`, `coder-cloud`, `explorer-cloud`, `reviewer`, `security-auditor`, `debugger` (9 profiles from `config/intel_tiers.yaml`) |
| **Plane B** (Engine) | Engine tier-ladder (`/setup/llm/tiers`) | `parse_verify`, `material_tailoring`, `screening_answers`, `viability_scoring` (4 engine LLM capabilities) |

## Single-Connect-Configures-Both (AZ1-1)

One model-connect act configures **both** planes simultaneously:
- **Plane A**: presets from `/setup/llm/presets` are assigned to agent profiles.
- **Plane B**: the engine `POST /setup/llm` configures the tier-ladder.

There is never a two-prompt connect flow. This is enforced at runtime by the model-connect bridge (AZ1-1, #829).

## `LLM_LOCAL_ONLY` Spanning Both Planes

When `LLM_LOCAL_ONLY` is set:
- Both planes are forced to local models.
- Remote-only scenarios (R1–R5 from the orchestration doctrine) degrade to the best available local tier.
- A caveat is surfaced to the user when a remote-only capability cannot be satisfied locally.

## Scope: Static vs. Runtime

| Acceptance Criterion | Where Validated |
|---------------------|-----------------|
| **AC1**: Single connect → both plane side effects | Model-connect bridge (AZ1-1, #829) — runtime |
| **AC2**: No capability appears in both planes (disjoint) | `tests/unit/test_intel_planes.py` — **static** |
| **AC3**: `LLM_LOCAL_ONLY` blocks all cloud in both planes | Engine setup + bridge — runtime |
| **AC4**: Tiers editor shows both planes' live bindings | Tiers editor (AZ3-1, #839) — runtime |

This file plus `test_intel_planes.py` enforces the **static disjoint-ownership contract**. The runtime behaviors are validated where the bridge and editor live (referenced above).

## Canonical Sources

- **Static contract**: `config/intel_planes.yaml` (this directory)
- **Profile definitions**: `config/intel_tiers.yaml`
- **Test suite**: `tests/unit/test_intel_planes.py`

## §1 → Real-Name Mapping

The Ground Truth §1 label "taste model" maps to **`viability_scoring`** in the real engine (`src/applicant/application/services/scoring_service.py` — LLM semantic viability judgment).
