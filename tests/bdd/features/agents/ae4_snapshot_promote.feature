# EPIC AGENTS / AE4 — Snapshot + promote
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer snapshots before every promotion

  @pending
  Scenario: A snapshot is taken immediately before promotion
    Given a change has passed canary
    When the Automation Engineer promotes it to production
    Then a snapshot of the pre-promotion image and database state is taken first
    And the snapshot is retained and addressable for a rollback

  @pending
  Scenario: Promotion without a snapshot never happens
    Given the snapshot step fails for any reason
    When promotion would otherwise proceed
    Then promotion is blocked
    And the failure is recorded and the user is proactively notified
