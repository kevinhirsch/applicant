# EPIC AGENTS / GATE-1 — Autonomous-deploy responsible gate (Q10)
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.
# GATE-1 is not a slice with independent value — it gates AE4/AE5's auto-promote path and should
# not be considered satisfied until AE5's forced-failure rollback drill has actually been run.

Feature: Autonomous deploy stays gated until the product and the harness are both proven

  @pending
  Scenario: Auto-promote is off by default
    Given the Automation Engineer has a canary-passed, snapshot-ready change
    When GATE-1's preconditions have not both been confirmed
    Then the change is proposed for a human to approve
    And it is not promoted automatically

  @pending
  Scenario: Auto-promote activates only after both preconditions are confirmed
    Given the core pipeline stability precondition and the independently-verified safety-harness
      precondition are both confirmed
    When the responsible gate is flipped
    Then subsequent canary-passed, snapshot-ready changes may be promoted automatically
    And every such automatic promotion still passes through AE2-AE5 unchanged
