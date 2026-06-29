Feature: Version-history summary and source are HTML-escaped at the list sink
  # Issue #395 — workspace/static/js/document.js:9203 (summary) / :9201 (source) sink
  # Requirement: The front-door MUST pass v.summary and v.source through the HTML escaper
  # before interpolating them into the version-history innerHTML, like the diff sibling already does.

  Scenario: The diff column in the same version row is already escaped
    Given the document browser module
    When the version-history diff builder is inspected
    Then each diff line is escaped with the escaping helper

  @pending
  Scenario: The version summary and source are escaped at the list sink
    Given the document browser module
    When the version-history list interpolation is inspected
    Then the summary and source values are escaped before interpolation
