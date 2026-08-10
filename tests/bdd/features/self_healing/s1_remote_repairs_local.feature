# Slice S1 — Remote-repairs-local LLM. docs/stories/self-healing.md#s1-remote-repairs-local-llm
# Grounds: src/applicant/adapters/llm/openai_compatible.py (tier ladder), src/applicant/
# application/services/model_endpoint_service.py (endpoint ping), MODEL-RESILIENCY fallback
# tier (docs/APPLICANT-BACKLOG.md), the new scoped restart control-plane channel (gap — see
# ADR-0008 Consequences).
#
# NOT YET WIRED — see epic_self_healing.feature header for the collection/@pending convention.

Feature: Remote LLM repairs the local LLM

  @pending
  Scenario: Inference escalates to remote when local is unreachable
    Given the local vLLM endpoint is unreachable
    When a scoring or chat call is dispatched through the tier ladder
    Then the call escalates to the remote fallback tier
    And the caller receives a valid result without LLMLadderExhausted being raised

  @pending
  Scenario: The remote-tier remediator restarts the wedged local model
    Given the local vLLM endpoint has been reported unreachable for more than one detector cycle
    When the remediator, itself running on the remote tier since local is down, diagnoses the endpoint
    Then it issues a bounded restart request against the local model service
    And the local endpoint eventually reports online again
    And zero human action was required
    And an audit entry links the detection, the restart action, and the recovery

  @pending
  Scenario: Restart attempts are bounded and fail safe
    Given the local model restart action has failed its bounded retry budget
    When the budget is exhausted
    Then the system stops attempting restarts
    And it alerts via the existing notification path
    And it continues serving inference from the remote fallback tier in the meantime
