Feature: Mark-submitted disables its button until the record is saved
  # Issue #396 — workspace/static/js/applicantDebug.js:295 (_markSubmitted)
  # Requirement: _markSubmitted MUST disable the triggering button (or guard re-entry by application id) until the POST resolves, so a manual submission cannot be recorded twice.

  Scenario: A sibling write action already disables its trigger in flight (the pattern to match)
    Given the Activity/Debug browser module
    When the Update click handler is inspected
    Then it disables its button before awaiting the request

  Scenario: The same manual submission cannot be recorded twice
    Given the Activity/Debug browser module
    When the mark-submitted handler is inspected
    Then it disables the triggering button or guards by application id until the record is saved
