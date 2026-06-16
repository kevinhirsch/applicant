Feature: Dormant surfaces are present but grayed
  # master spec §10 / dormant-surfaces.md — FR-UI-2, FR-OBS-2, FR-OOBE-4

  Scenario: The debug surface ships every panel, graying the not-yet-wired ones
    Given the rendered debug surface
    Then the tool-toggle, history, and update panels are present and live
    And the logs, screenshots, and variant-library panels are present but dormant

  Scenario: A not-yet-wired debug data endpoint reports pending rather than faking data
    Given a not-yet-wired observability endpoint
    Then it reports a pending status with no fabricated rows

  Scenario: The in-UI update button is safe by default
    Given the update trigger with no override set
    When the update is triggered
    Then it does not start a destructive update and explains why
