# Issue #270 — _fetchJSON/esc/_toast duplicated identically across applicant modules
# Almost every applicant*.js module copy-pastes the same fetch helper, HTML-escape and
# toast helpers (and the _tk/_owner token storage). esc() already delegates to
# uiModule.esc when present, proving a shared utility belongs in one place. The fix is a
# shared applicantCore.js imported by the others. GREEN: prove the duplication exists
# today across many modules and that no shared core module exists yet. @pending: the
# cleanup acceptance criterion — a shared core module exists and the modules import it.

Feature: Shared applicant browser helpers are defined once

  Scenario: The fetch, escape and toast helpers are duplicated across modules
    Given the applicant browser modules
    When the modules are scanned for their own copy of the shared helpers
    Then many modules define their own identical copies

  Scenario: No shared applicant core module exists yet
    Given the applicant browser modules
    Then there is no shared applicant core helper module today

  @pending
  Scenario: The duplicated helpers live in a shared core module the others import
    Given the applicant browser modules
    Then a shared applicant core helper module exists
    And the other applicant modules import the shared helpers from it
