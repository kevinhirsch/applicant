Feature: Multi-campaign switcher front-door wiring
  # Issue #176 — src/applicant/dormant.py + workspace/src/applicant_features.py
  # The data model is campaign-scoped and cross-campaign isolation is tested, but the
  # multi-campaign switcher UI is registered DORMANT and has no front-door section. The
  # registry entry is GREEN regression; the missing front-door switcher binding is the gap.

  Scenario: The multi-campaign switcher is honestly registered as dormant
    Given the engine dormant-surface registry
    When the multi-campaign switcher entry is read
    Then it reports a dormant status so no live switcher is implied

  Scenario: The front door exposes a campaign switcher section
    Given the workspace Applicant section map
    When the sections are inspected for a multi-campaign switcher
    Then a section grays itself off the multi-campaign switcher surface key
