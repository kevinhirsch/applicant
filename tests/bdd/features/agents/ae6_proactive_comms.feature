# EPIC AGENTS / AE6 — Proactive communication
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer communicates proactively, not after the fact

  @pending
  Scenario: Starting a build is announced immediately
    Given the Automation Engineer accepts a task and begins building it
    When the build starts
    Then a proactive notification is sent describing what is being built and why
    And this happens before the build completes, not after

  @pending
  Scenario: A shipped feature is announced on promotion
    Given a change is successfully promoted and passes its health checks
    When the promotion is confirmed healthy
    Then a proactive notification confirms what shipped
    And it is visible on the activity feed with the linked audit entries
