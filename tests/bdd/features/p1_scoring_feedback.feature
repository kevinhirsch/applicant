Feature: Viability scoring and decline-with-feedback round-trip
  # master spec §10 — FR-AGENT-3, FR-DIG-5, FR-FB-1, FR-FB-3 (confirmation gate)

  Scenario: Viability scoring applies a configurable threshold
    Given the viability threshold defaults to seventy
    When a posting is scored against matching criteria
    Then the score is reported on a zero-to-one scale with a rationale

  Scenario: Decline-with-feedback is recorded for learning
    Given an application surfaced in the digest
    When the user declines it with feedback
    Then a decline decision is recorded carrying the feedback text

  Scenario: An integral attribute change requires confirmation
    Given an integral attribute already exists
    When the value is changed without confirmation through the API
    Then the change is rejected with a confirmation-required response

  Scenario: A sensitive attribute refuses an AI-guessed value
    Given the LLM gate is open
    When an AI-guessed value is submitted for a sensitive attribute
    Then the sensitive-field policy rejects the guess
