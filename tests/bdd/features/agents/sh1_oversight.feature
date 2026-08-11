# EPIC AGENTS / SH1 — Activity feed, revert buttons, kill switch, per-action veto
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Shared oversight for the Reflection Coach and the Automation Engineer

  @pending
  Scenario: The activity feed shows every RC/AE action with a working revert
    Given the Reflection Coach or the Automation Engineer has taken a recorded action
    When the user views the activity feed
    Then the action is listed with its audit detail
    And a revert control is available and functional for reversible actions

  @pending
  Scenario: The kill switch halts both agents
    Given the global kill switch is engaged
    Then the Reflection Coach performs no further evaluations or auto-applies
    And the Automation Engineer performs no further build, canary, or promote steps
    And re-engaging the switch resumes normal operation without requiring a restart

  @pending
  Scenario: A per-action veto blocks exactly one action
    Given multiple actions are queued or pending across both agents
    When the user vetoes one specific action
    Then that action does not proceed
    And every other action continues on its normal path

  @pending
  Scenario: A daily digest summarizes both agents' activity
    Given a day of Reflection Coach and Automation Engineer activity
    When the daily digest is delivered
    Then it includes a summary of tweaks applied, tasks built/shipped, and anything vetoed or
      rolled back
