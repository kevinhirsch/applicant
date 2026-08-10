# EPIC AGENTS / AE2 — Hard TDD/BDD gate
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer TDD/BDD hard gate

  @pending
  Scenario: A change with failing tests is blocked from canary
    Given the Automation Engineer completes a task
    When its unit tests or its BDD scenarios fail
    Then the change is not eligible for canary or promotion
    And the failure is recorded in the audit trail with the specific failing check

  @pending
  Scenario: A change with all green checks proceeds
    Given the Automation Engineer completes a task
    When its unit tests and its BDD scenarios both pass
    Then the change becomes eligible to enter the canary stage
