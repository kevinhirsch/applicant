# EPIC AGENTS / AE3 — Canary harness (e2e instance + monkey-crawl)
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer canaries every change before promotion

  @pending
  Scenario: A change deploys to the disposable e2e instance first
    Given a change has passed the TDD/BDD gate
    When the Automation Engineer attempts to promote it
    Then it first builds and deploys the change to a disposable e2e instance
    And it does not touch the production instance yet

  @pending
  Scenario: The full suite and a monkey-crawl both gate promotion
    Given the change is running on the disposable e2e instance
    When the canary verification runs
    Then the full test suite runs against it
    And a browser monkey-crawl runs against it
    And promotion proceeds only if both are green

  @pending
  Scenario: A canary failure blocks promotion and is reported
    Given the canary verification fails (suite or monkey-crawl)
    When the failure is detected
    Then the change is not promoted
    And the disposable instance's failure detail is recorded in the audit trail
    And the user is proactively notified
