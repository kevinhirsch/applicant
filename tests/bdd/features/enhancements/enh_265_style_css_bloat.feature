# Issue #265 — the 1.1MB style.css almost certainly contains substantial dead CSS
# style.css is over a megabyte after many iterations and the frontend/ replacement, so a
# conservative 20-40% of selectors are likely unused. The cleanup acceptance criterion
# is a meaningfully smaller stylesheet after an unused-selector audit. GREEN: pin the
# oversized baseline so any later trim is measurable. @pending: the stylesheet has been
# reduced below a conservative post-audit ceiling.

Feature: The main stylesheet is not carrying a megabyte of dead CSS

  Scenario: The stylesheet is over a megabyte today
    Given the workspace main stylesheet
    Then it is larger than one megabyte

  @pending
  Scenario: The stylesheet has been trimmed below the post-audit ceiling
    Given the workspace main stylesheet
    Then it is smaller than the post-audit size ceiling
