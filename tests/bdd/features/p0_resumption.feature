Feature: Mid-step crash resumption
  # master spec §10 (FR-DUR-1, FR-DUR-3)

  Scenario: Worker dies mid-application and restarts
    Given a durable workflow that has completed its first step
    When the worker is killed and a new worker restarts the workflow
    Then the workflow resumes from the last completed step
    And the already-completed step does not run again
