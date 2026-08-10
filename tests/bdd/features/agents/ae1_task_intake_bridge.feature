# EPIC AGENTS / AE1 — Task intake + vendored coding-stack bridge
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Automation Engineer task intake and coding-stack bridge

  @pending
  Scenario: A user-initiated task reaches the bridge
    Given the user requests a change through the product
    When the request is submitted
    Then it is accepted as an Automation Engineer task
    And it is routed to the vendored agent0 overseer with a self-contained instruction

  @pending
  Scenario: A Reflection-Coach-filed task reaches the bridge
    Given a ProgrammaticNeedRaised event (queued or direct-handoff, RC3)
    When the Automation Engineer's intake consumes it
    Then it is accepted as an Automation Engineer task with the same shape as a user-initiated one

  @pending
  Scenario: A self-detected task reaches the bridge
    Given a RemediationRequested event (ADR-0008) or an Automation-Engineer-specific detector fires
    When the Automation Engineer's intake consumes it
    Then it is accepted as an Automation Engineer task

  @pending
  Scenario: The bridge delegates to the existing local/cloud tier roster, not a new one
    Given an accepted task requires implementation
    When the bridge dispatches it
    Then it uses the existing coder/explorer/test-engineer/reviewer/security-auditor/debugger
      profiles and the existing tier topology
    And no parallel coding-agent framework is instantiated
