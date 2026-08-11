Feature: Review-UX — the Pending-Reviews decision + refinement workflow
  # EPIC REVIEW-UX (RUX-1/2/3): open the source posting -> decide
  # Continue / Save-for-later / Discard -> (if Continue) review + refine.
  # Thin UX over existing engines: MaterialService review gate,
  # PendingActionsService saved bucket, FeedbackService negative learning.

  Scenario: RUX-1 The review shows the live source posting plus a cached snapshot
    Given an application under review with a source posting
    When the reviewer opens the source posting
    Then the live source URL is shown
    And a cached snapshot of the listing is offered

  Scenario: RUX-2 Continue approves the generated materials through the review gate
    Given an application under review with a generated cover letter
    When the reviewer chooses Continue
    Then the generated cover letter is approved through the review gate

  Scenario: RUX-2 Save-for-later moves the app to a distinct bucket with a nudge
    Given an application under review with a source posting
    When the reviewer chooses Save-for-later
    Then the application appears in the Saved bucket
    And it is out of the active pending queue

  Scenario: RUX-2 Discard-with-reason declines reversibly and teaches negative learning
    Given an application under review with a generated cover letter
    When the reviewer discards it with a reason
    Then the material is declined but not deleted
    And the discard reason feeds a negative learning signal

  Scenario: RUX-3 A per-section regenerate stays review-gated until approval
    Given an application under review with a source posting
    When the reviewer regenerates the cover letter section
    Then a new cover letter is produced unapproved

  Scenario: RUX-3 One instruction applied across sections stays review-gated
    Given an application under review with a generated cover letter
    When the reviewer applies one instruction across all sections
    Then every section records the revision turn
    And no section is approved by the edit
