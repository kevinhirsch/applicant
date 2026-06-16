Feature: Decline-with-feedback round-trips into learning and next-run criteria
  # master spec §10 (Decline-with-feedback into learning) — FR-DIG-5, FR-FB-1, FR-CRIT-3, FR-LEARN-3

  Scenario: Declining a digested role feeds learning and biases the next run
    Given a campaign with seeded criteria and a surfaced application
    When the user declines the application with feedback and a criteria delta
    Then the decline is folded into the campaign learning model
    And the next-run criteria reflect the structured delta

  Scenario: The digest is delivered across channels with a ready ping
    Given a campaign with a viable discovered posting
    When the daily digest is delivered
    Then an email payload and a Discord ready ping are produced
    And a digest-approval item appears in the pending-actions portal
