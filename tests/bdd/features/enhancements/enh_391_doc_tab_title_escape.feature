Feature: Document titles are HTML-escaped before they reach the tab bar
  # Issue #391 — workspace/static/js/document.js:283 / :284 (sink), title from email/agent/shared
  # Requirement: The front-door MUST HTML-escape doc.title / shortTitle before interpolating
  # them into the tab-bar innerHTML string.

  Scenario: Sibling title sinks in the document module already escape user text
    Given the document browser module
    When the language-picker and suggestion-reason sinks are inspected
    Then both escape their interpolated text with the escaping helper

  @pending
  Scenario: The tab-bar title and short title are escaped before interpolation
    Given the document browser module
    When the tab-bar title interpolation is inspected
    Then the title and short title are escaped before they are placed into the tab markup
