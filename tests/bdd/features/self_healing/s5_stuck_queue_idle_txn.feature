# Slice S5 — Stuck-queue / idle-txn auto-heal. docs/stories/self-healing.md#s5-stuck-queue--idle-txn-auto-heal
# Grounds: src/applicant/application/services/agent_loop.py (_record_approval_start_failure,
# _record_resume_failure — existing bounded-retry-then-notify-human paths). The idle-in-
# transaction probe itself is a new build (no existing detector — see the story doc's Gap 2).
#
# NOT YET WIRED — see epic_self_healing.feature header for the collection/@pending convention.

Feature: Stuck applications and idle DB sessions self-heal

  @pending
  Scenario: A stuck application start is remediated before the human-notify cap
    Given an application has failed to start on consecutive ticks, short of the failure cap
    When the remediator diagnoses the failure across sandbox capacity, orchestrator health, and workflow logs
    Then it applies a bounded corrective action such as releasing and retrying the sandbox slot
    And it only falls through to the existing human notification if that action doesn't clear the streak

  @pending
  Scenario: An idle-in-transaction session is detected and safely terminated
    Given a database session has been idle-in-transaction past the configured age threshold
    When the probe detects it
    Then the remediator terminates the offending session
    And it never terminates a session with in-flight, uncommitted user-authored work
    And the action is recorded in the audit trail

  @pending
  Scenario: Exhausted remediation still fails safe exactly as today
    Given a stuck application's remediation attempts are exhausted
    When the existing failure cap is reached
    Then the existing deduped notify_error alert fires, unchanged
    And no infinite retry loop occurs
