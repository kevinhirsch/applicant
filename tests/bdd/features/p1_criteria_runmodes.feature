Feature: Per-campaign criteria, run controls, and converting-role bias
  # master spec §10 — FR-CRIT-2/3, FR-AGENT-1/2/7, FR-LEARN-5

  Scenario: A user edits human-readable criteria at any time
    Given a campaign exists
    When the user edits the campaign keywords through the API
    Then the criteria reflect the user's edit

  Scenario: An integral criteria change requires confirmation
    Given a campaign exists
    When the user changes an integral criterion without confirmation
    Then the criteria change is rejected with a confirmation-required response

  Scenario: A learned criteria adjustment is surfaced transparently
    Given a campaign exists
    When learning proposes a non-integral criteria adjustment
    Then the adjustment is applied and surfaced with a human-readable summary

  Scenario: Throughput is clamped to the daily hard cap
    Given a campaign exists
    When the user sets the throughput target above the hard cap
    Then the persisted throughput target is clamped to thirty

  Scenario: A run records a single-sentence intent
    Given a campaign exists
    When an agent run is started with an intent sentence
    Then the latest intent for the campaign is that sentence
