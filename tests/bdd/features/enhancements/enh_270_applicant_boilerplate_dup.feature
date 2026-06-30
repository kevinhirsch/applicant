# Issue #270 — _fetchJSON/esc/_toast duplicated identically across applicant modules
# Almost every applicant*.js module copy-pastes the same fetch helper, HTML-escape and
# toast helpers (and the _tk/_owner token storage). esc() already delegates to
# uiModule.esc when present, proving a shared utility belongs in one place. The fix is a
# shared applicantCore.js imported by the others. Cleanup shipped.

Feature: Shared applicant browser helpers are defined once

  @pending
  Scenario: The fetch, escape and toast helpers are duplicated across modules
    Given the applicant browser modules
    When the modules are scanned for their own copy of the shared helpers
    Then many modules define their own identical copies

  @pending
  Scenario: No shared applicant core module exists yet
    Given the applicant browser modules
    Then there is no shared applicant core helper module today

  Scenario: The duplicated helpers live in a shared core module the others import
    Given the applicant browser modules
    Then a shared applicant core helper module exists
    And the other applicant modules import the shared helpers from it
