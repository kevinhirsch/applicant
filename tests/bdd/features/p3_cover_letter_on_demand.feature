Feature: Cover letter on demand reviewed
  # master spec §10 (FR-RESUME-10, FR-RESUME-8, FR-RESUME-2, FR-NOTIF-4)

  Scenario: A role that does not warrant a cover letter generates none
    Given a campaign whose cover-letter default is off
    When the engine considers a cover letter for a role with no override
    Then no cover letter is generated

  Scenario: A role warranting a cover letter generates one routed through review
    Given a campaign whose cover-letter default is off
    And the candidate's true source for the cover letter
    When the engine generates a cover letter for a role that requires one
    Then the cover letter is stored unapproved
    And the cover letter contains no em-dash
    And a review-ready notification linked to the review surface is emitted
    And submission is blocked while the cover letter is unapproved
    When the user approves the cover letter
    Then submission is no longer blocked by the review gate
