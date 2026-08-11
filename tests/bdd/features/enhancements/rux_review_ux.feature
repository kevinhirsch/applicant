Feature: REVIEW-UX — the Pending-Reviews decision + refinement workflow (frontend)
  # docs/APPLICANT-BACKLOG.md §EPIC REVIEW-UX (RUX-1/2/3/5).
  # These scenarios pin the Review-modal + Digest frontend contract at the source
  # level (the browser E2E lives in the Playwright harness). The Review modal is a
  # THIN UX layer over the engine /api/review surface (proxy: plugins/applicant/review).

  Scenario: The Review modal opens the source posting and offers a cached snapshot
    # RUX-1
    Given the Review modal panel
    Then it links the shared applicant theme stylesheet
    And it exposes a "View source posting" link that opens in a new tab without opener leak
    And it shows a posted-date freshness cue
    And it offers a cached snapshot fallback via the review snapshot action

  Scenario: The digest row also surfaces the source posting and snapshot fallback
    # RUX-1 on the queue row itself
    Given the Digest panel
    Then each row exposes a source posting link opening in a new tab
    And each row offers a cached snapshot fallback via the review snapshot action
    And the digest Review button opens the Review modal carrying the posting id

  Scenario: The reviewer makes a three-way decision, with a reason required to discard
    # RUX-2
    Given the Review modal panel
    Then it offers Continue, Save for later, and Discard decisions via the review decide action
    And discarding requires a non-blank reason

  Scenario: The reviewer refines the generated answers per section and across the app
    # RUX-3
    Given the Review modal panel
    Then it renders the generated sections with their review status
    And it can inline-edit and save a section via the edit_section action
    And it can regenerate a single section via the regenerate_section action
    And it can apply feedback across sections via the apply_feedback action
    And it can regenerate the whole app via the regenerate_all action

  Scenario: The reviewer teaches the profile with transparent, reversible feedback
    # RUX-5
    Given the Review modal panel
    Then it exposes a freeform profile feedback box via the profile_feedback action
    And it shows what changed and lets the reviewer revert it
