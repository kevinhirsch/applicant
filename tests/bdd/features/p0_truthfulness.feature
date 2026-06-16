Feature: Adaptation never fabricates and never looks AI-written
  # master spec §10 (FR-RESUME-2, FR-RESUME-5, NFR-TRUTH-1)

  Scenario: Em-dashes are stripped by the deterministic post-filter
    Given generated resume text containing an em-dash
    When the truthfulness post-filter runs
    Then no em-dash remains in the output
    And the output is stable when filtered again
