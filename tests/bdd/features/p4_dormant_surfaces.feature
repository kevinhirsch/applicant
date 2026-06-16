Feature: Dormant surfaces are present but grayed
  # master spec §10 / dormant-surfaces.md — FR-UI-2, FR-OBS-2, FR-OOBE-4

  Scenario: The debug surface ships every panel, graying the genuinely dormant ones
    Given the rendered debug surface
    Then the tool-toggle, history, and update panels are present and live
    And the logs, screenshots, and variant-library panels are present and live
    And the genuinely dormant surfaces are present but grayed

  Scenario: The wired observability endpoints return real data, not fabricated rows
    Given a campaign with a logged application
    Then the debug history reflects the real application
    And the logs endpoint returns recent redacted entries

  Scenario: The in-UI update button is safe by default
    Given the update trigger with no override set
    When the update is triggered
    Then it does not start a destructive update and explains why
