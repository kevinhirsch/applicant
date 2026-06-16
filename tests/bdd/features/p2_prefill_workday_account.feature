Feature: Maximal pre-fill, stop at irreducible human steps
  # master spec §10 (Maximal pre-fill, stop at irreducible human steps; Workday
  # account creation) — FR-PREFILL-2/3/4, FR-ATTR-6, FR-SANDBOX-2, FR-NOTIF-2

  Scenario: Workday account creation
    Given an approved role on a Workday tenant requiring an account
    And the campaign attribute cloud holds the user's stored answers
    When the engine reaches the account-creation form
    Then it pre-fills every fillable field on the account form
    And it does not click the account-creating submit
    And it notifies the user with a one-click VNC link to complete the human step
    And the application is awaiting the account human step

  Scenario: Sensitive EEO fields are never AI-guessed during pre-fill
    Given an approved role on a Workday tenant requiring an account
    And the campaign attribute cloud holds the user's stored answers
    When the engine pre-fills the full application after the account step
    Then every fillable application field is pre-filled
    And sensitive EEO fields are filled only from explicit stored answers
    And unanswered sensitive fields default to decline to self-identify
    And the application is awaiting final approval

  # FR-ATTR-5: missing-attribute soft error during pre-fill
  Scenario: A missing required attribute raises a soft error and is reused after resolve
    Given an approved role on a Workday tenant requiring an account
    And the campaign attribute cloud is missing a required detail
    When the engine pre-fills the full application after the account step
    Then pre-fill pauses with a missing-detail soft error
    And a provide-missing-detail pending action is created
    When the user supplies the missing detail
    Then pre-fill resumes and reaches awaiting final approval

  # FR-ANSWER-1: essay screening questions are deferred to Phase 3
  Scenario: Essay screening questions are deferred, factual ones are filled
    Given an approved role on a Workday tenant requiring an account
    And the campaign attribute cloud holds the user's stored answers
    When the engine pre-fills the full application after the account step
    Then factual screening questions are filled from stored answers
    And essay screening questions are deferred to material generation
