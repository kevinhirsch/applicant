Feature: Adaptation never fabricates
  # master spec §10 (FR-RESUME-2, FR-RESUME-5, NFR-TRUTH-1)

  Scenario: The engine reframes real experience but never adds a missing skill
    Given the candidate's true source mentions Python and SQL but not Kubernetes
    And a job description emphasizing Python and Kubernetes
    When the engine reframes the source toward the job description
    Then the reframed text still surfaces the real Python experience
    And the reframed text does not claim Kubernetes
    And attempting to inject a Kubernetes claim is rejected as a truthfulness violation

  Scenario: The em-dash filter strips em-dashes deterministically
    Given generated material containing an em-dash
    When the non-AI-looking post-filter runs
    Then no em-dash remains in the output
    And the output is stable when filtered again
