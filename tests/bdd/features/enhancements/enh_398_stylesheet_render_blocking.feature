Feature: The main stylesheet does not block first paint
  # Issue #398 — workspace/static/index.html:216 (synchronous style.css link) / :203 (KaTeX media=print anchor)
  # Requirement: Critical above-the-fold CSS MUST be deliverable without blocking on the full ~1.1MB sheet, independent of any size reduction tracked by #265.

  Scenario: The KaTeX sheet uses the non-blocking deferral pattern (the pattern to match)
    Given the front-door index page
    When the KaTeX stylesheet link is inspected
    Then it is loaded with media print so it does not block first paint

  Scenario: The main stylesheet is not loaded render-blocking in the head
    Given the front-door index page
    When the main stylesheet link is inspected
    Then it is deferred, async, split, or its critical CSS is inlined rather than a synchronous blocking link
