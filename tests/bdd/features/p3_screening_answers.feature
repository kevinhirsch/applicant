Feature: Screening answers go through review
  # master spec §10 (FR-ANSWER-1, FR-RESUME-8)

  Scenario: A generated screening answer is not submittable until reviewed and approved
    Given a screening question and the candidate's true source material
    When the engine generates an essay screening answer
    Then the answer is stored unapproved
    And submission is blocked while the screening answer is unapproved
    When the user opens the redline review
    And the user approves the screening answer
    Then submission is no longer blocked by the review gate

  Scenario: A factual screening answer is taken directly from the true source
    Given a factual screening question and the candidate's true source material
    When the engine generates a factual screening answer
    Then the answer contains no em-dash
    And the answer is stored unapproved
