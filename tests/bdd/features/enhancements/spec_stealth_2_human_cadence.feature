Feature: Automation types with a human-like cadence
  # FR-STEALTH-2 — adapter: src/applicant/adapters/browser/stealth.py
  # Requirement: The human-interaction toolkit MUST produce a per-key typing plan with
  # positive dwell times and an advancing logical clock, deterministic under an injected
  # seed (no wall-clock sleeps).

  Scenario: Typing a phrase yields positive per-key dwell and advances the clock
    Given a seeded human-interaction toolkit
    When a phrase is planned for typing
    Then every keystroke has a positive dwell time
    And the simulated typing time advances past zero
