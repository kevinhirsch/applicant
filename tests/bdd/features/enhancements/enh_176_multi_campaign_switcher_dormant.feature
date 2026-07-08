Feature: Multi-campaign switcher front-door wiring
  # Issue #176 — src/applicant/dormant.py + workspace/src/applicant_features.py
  # The data model is campaign-scoped and cross-campaign isolation is tested. P1-10
  # un-locked the switcher: the registry entry is LIVE (campaign create/clone with
  # per-campaign base résumés; Today/Tracker filter by campaign; the daily-updates
  # panel keeps its own per-campaign picker) and a front-door section gates off it.

  Scenario: The multi-campaign switcher is honestly registered as live
    Given the engine dormant-surface registry
    When the multi-campaign switcher entry is read
    Then it reports a live status so the front door can light the switcher up

  Scenario: The front door exposes a campaign switcher section
    Given the workspace Applicant section map
    When the sections are inspected for a multi-campaign switcher
    Then a section grays itself off the multi-campaign switcher surface key
