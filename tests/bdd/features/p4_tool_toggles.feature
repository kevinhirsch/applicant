Feature: Tool registry toggles
  # master spec §10 / dormant-surfaces.md §5 — FR-UI-4

  Scenario: The initial registry exposes every agent tool enabled by default
    Given a fresh tool registry
    Then all ten agent tools are present and enabled

  Scenario: Toggling a tool off persists and is enforced at dispatch
    Given a fresh tool registry
    When the operator toggles the discovery tool off
    Then the discovery tool reads as disabled
    And dispatching the discovery tool is rejected

  Scenario: Toggling a tool back on re-enables dispatch
    Given a fresh tool registry
    When the operator toggles the discovery tool off
    And the operator toggles the discovery tool back on
    Then dispatching the discovery tool is allowed
