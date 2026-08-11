# EPIC SELF-HEAL — docs/APPLICANT-BACKLOG.md; architecture in docs/adr/0008-autonomous-self-healing.md
# Story: docs/stories/self-healing.md
#
# NOT YET WIRED: no tests/bdd/steps/*.py module calls scenarios() on this file, so pytest-bdd
# does not collect it (see the story doc's "BDD framework + scaffold status" section). Every
# scenario below is @pending in anticipation of that wiring — when a step module is added, keep
# @pending until the corresponding slice (S1-S5, docs/stories/self-healing.md) actually ships,
# then drop the tag scenario-by-scenario as behaviour lands (repo convention, see
# tests/bdd/conftest.py::pytest_bdd_apply_tag and tests/bdd/steps/test_enh_t12_cua_steps.py).

Feature: Autonomous self-healing — the product never needs a human to fix it

  @pending
  Scenario: The remote LLM repairs the local LLM
    Given the local LLM is wedged or unreachable
    When an inference or scoring call fails deterministically
    Then the system escalates inference to the remote LLM
    And a remediation action is triggered that restores the local LLM
    And zero human action was required
    And an audit entry records the detection, the action, and the outcome

  @pending
  Scenario: A deterministic failure signature triggers the detect-remediate-audit loop
    Given a deterministic error signature fires (panel JS error, migration failure, endpoint
      5xx, a stuck or starved queue, scorer degrade-to-embeddings, or an open discovery
      circuit breaker)
    When the signature is detected
    Then an AI remediator is invoked with tool access to diagnose and correct it
    And the action taken and its outcome are recorded in the audit trail

  @pending
  Scenario: Remediation is bounded and fails safe
    Given a remediation attempt is in progress
    When its bounded retry budget is exhausted
    Then the system fails safe — it degrades gracefully and alerts
    And it never loops infinitely
    And it never loses data as a result of the failed remediation

  @pending
  Scenario: Guardrails hold even inside self-repair
    Given any remediation action, successful or not
    Then no user application is ever auto-submitted as a side effect
    And no user data is ever deleted as a side effect

  @pending
  Scenario: No human is required overnight
    Given a failure class covered by a detector occurs while unattended overnight
    When the failure occurs
    Then the product returns to a healthy state with no human intervention
    And the audit trail evidences the full detect-remediate-recover sequence
