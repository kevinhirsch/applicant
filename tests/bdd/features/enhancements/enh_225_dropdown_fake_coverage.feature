# Issue #225 — Dropdown/combobox matching has zero fake-model coverage (adapters/browser/page_source.py) — FR-PREFILL-3
# GREEN: the underlying option-matching RULE is hermetically testable — exact/loose/
#        decline-synonym matching is exercised here as a pure function.
# PENDING: the FakePageSource's type_value just records the value; it never exercises the
#          real dropdown selection (option matching, decline synonyms) in CI.

Feature: Dropdown option matching is covered by hermetic tests

  Scenario: The option matcher resolves exact, loose, and decline-synonym options
    Given the dropdown option matcher
    When an exact option, a loose subset option, and a decline synonym are matched
    Then the exact match wins, the subset matches loosely, and the decline synonym matches

  Scenario: The option matcher rejects a misleading substring option
    Given the dropdown option matcher
    When the wanted value would only substring-match a different option
    Then no match is returned

  @pending
  Scenario: The fake page source actually validates a dropdown selection
    Given the fake page source standing in for a real combobox
    When a value is selected against an option set on the fake
    Then the fake verifies the value matched a real option rather than blindly recording it
