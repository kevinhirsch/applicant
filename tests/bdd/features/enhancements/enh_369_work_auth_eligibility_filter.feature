Feature: Captured work-authorization filters out ineligible postings
  # Issue #369 — onboarding work-auth (services/onboarding_seed.py:123) +
  # sponsorship lexicon (core/rules/materials.py); scoring eligibility filter is new.
  # Requirement: Scoring/discovery MUST down-rank or exclude postings whose stated
  # requirements (visa sponsorship, citizenship, security clearance) conflict with the
  # user's captured work-authorization, surfacing the reason; an eligible posting MUST
  # be unaffected. GREEN: onboarding captures work-auth and the materials lexicon
  # already knows sponsorship/visa phrasing. PENDING: nothing yet USES them to filter.

  Scenario: Onboarding has a dedicated work-authorization intake section
    Given the onboarding intake model
    When the required sections are listed
    Then work authorization is one of the captured sections

  Scenario: The materials lexicon recognizes sponsorship and visa phrasing
    Given the material-policy sponsorship lexicon
    When a sponsorship-requirement phrase is checked against it
    Then the phrase is recognized by the lexicon

  Scenario: A sponsorship-required posting is excluded for a user who can't be sponsored
    Given a user whose captured work-authorization does not allow sponsorship
    When a posting requiring visa sponsorship is scored against that work-authorization
    Then the eligibility filter excludes or flags it and surfaces the reason

  Scenario: An eligible posting is unaffected by the eligibility filter
    Given a user whose captured work-authorization needs no sponsorship
    When a posting with no sponsorship requirement is scored against that work-authorization
    Then the eligibility filter leaves the posting unaffected
