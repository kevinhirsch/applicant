Feature: Sensitive fields are never AI-guessed
  # master spec §10 (FR-ATTR-6)

  Scenario: An EEO self-identification field with no stored answer
    Given an EEO self-identification field
    When the engine decides what to fill with no explicit stored answer
    Then it defaults to "decline to self-identify"
    And it never AI-guesses the value
