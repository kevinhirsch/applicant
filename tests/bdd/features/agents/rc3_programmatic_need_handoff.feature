# EPIC AGENTS / RC3 — Programmatic-need handoff to the Automation Engineer
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Reflection Coach files programmatic needs to the Automation Engineer

  @pending
  Scenario: A routine programmatic need is queued
    Given the effectiveness assessment identifies a need only a code or config change can fix
    When it is not marked urgent
    Then a ProgrammaticNeedRaised event is filed onto the shared backlog queue
    And it is visible to the Automation Engineer's task intake without further action

  @pending
  Scenario: An urgent programmatic need bypasses the queue
    Given the effectiveness assessment identifies an urgent programmatic need (e.g. a source
      newly broken, blocking the whole funnel)
    When it is marked urgent
    Then it is handed directly to the Automation Engineer's task intake
    And it does not wait for a queue poll cycle
