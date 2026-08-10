# EPIC AGENTS / AE5 — Health-gated auto-rollback
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer auto-rolls-back a failed promotion

  @pending
  Scenario: A healthy promotion is left in place
    Given a promotion completes
    When the post-deploy health checks pass through the monitoring window
    Then the promotion stands
    And no rollback occurs

  @pending
  Scenario: A failed health check triggers automatic rollback
    Given a promotion completes
    When a post-deploy health check fails within the monitoring window
    Then the Automation Engineer automatically reverts to the pre-promotion snapshot
    And zero human action was required
    And the rollback is recorded in the audit trail and the user is proactively notified

  @pending
  Scenario: Rollback itself is verified, not assumed
    Given an automatic rollback has been triggered
    When the rollback completes
    Then the production instance's health checks pass again against the restored snapshot
