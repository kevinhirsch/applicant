Feature: Interactive resume review with highlighted edits
  # master spec §10 (FR-RESUME-8, FR-NOTIF-4)

  Scenario: The user runs the add/subtract/free-text redline loop and approves before submission
    Given a generated resume document awaiting review
    And the application carries that unapproved generated document
    When the user opens the redline review
    And the user submits an add revision turn
    And the user submits a subtract revision turn
    Then the redline shows additions and deletions highlighted
    And submission is blocked while the document is unapproved
    When the user approves the document
    Then the document is approved
    And submission is no longer blocked by the review gate
