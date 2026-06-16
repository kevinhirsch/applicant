Feature: Generated material goes through review before submission
  # master spec §10 (FR-RESUME-8, FR-ANSWER-1)

  Scenario: A generated screening answer is not submitted without approval
    Given an application carrying a generated, unapproved screening answer
    When submission is attempted
    Then submission is refused
    When the user approves the material through the review gate
    Then submission is allowed
