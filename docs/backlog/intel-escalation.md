# FR-INTEL-4: Failure-based Escalation Contract

## Summary

When a **local** agent struggles (modelled as N consecutive action failures), the `_model_escalate` A0 plugin promotes it to a max-intelligence cloud tier, then **reverts** on the first clean success. This prevents Claude Code from churning on a weak model.

## Contract (`config/intel_escalation.yaml`)

| Field | Value | Meaning |
|---|---|---|
| `threshold` | `2` | Escalate on the 3rd consecutive local struggle (`threshold+1`) |
| `target_preset` | `DeepSeek-Pro` | Escalate to the strongest cloud preset |
| `target_tier` | `cloud-pro` | The tier matching DeepSeek-Pro (verified by `test_intel_escalation.py` against `config/intel_tiers.yaml`) |
| `applies_to` | `local-only` | Only local agents self-escalate; cloud agents never double-escalate |
| `reverts_on_success` | `true` | A clean tool result + progress resets the counter to 0 and reverts to local |
| `fail_safe` | `true` | Any error leaves the agent on its default tier (escalation is an optimisation, never a foot-gun) |
| `observable` | `true` | H1 receipt: "escalated to DeepSeek-Pro after N local struggles" — never a silent swap |

## Live Implementation

The three Python extensions implementing this contract ship in `a0-applicant/extensions/python/`, one per A0 extension point:

- `chat_model_call_before/_30_model_escalate.py` — checks the struggle counter and escalates the call when the threshold is reached
- `tool_execute_after/_20_escalate_track.py` — resets the counter on a clean tool result (handles the revert-on-success)
- `hist_add_warning/end/_50_escalate_track.py` — surfaces an H1 receipt message when escalation occurs

**Ordering**: `_model_escalate` runs **before** `_failover` and `_local_concurrency`, so those hooks see an already-escalated call.

## Runtime Behaviours (validated at A0 level)

| AC | Behaviour |
|----|-----------|
| AC1 | 2 local misformats → 3rd call routes to `deepseek-v4-pro` |
| AC2 | A clean tool result resets the counter and reverts to local |
| AC3 | Cloud agents never double-escalate (`applies_to: local-only`) |
| AC4 | An injected exception in the tracker is fail-safe (agent stays on its default tier) |
| AC5 | `threshold` is a single named constant pinned to 2 (a change to 3 would escalate on call 4; the test asserts the pinned value) |

## Why It Matters

Claude Code doesn't churn on a weak model. This contract promotes a stuck local agent to the strongest tier exactly when needed, then reverts — keeping costs down while ensuring resilience.

## Enforced By

- `tests/unit/test_intel_escalation.py` — hermetic contract enforcement
- `config/intel_tiers.yaml` — referential integrity (FR-INTEL-1)
- FR-INTEL-7 — reconciliation of contract vs live `_model_escalate` plugin
