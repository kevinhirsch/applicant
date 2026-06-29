Feature: Glyph-only buttons carry an explicit accessible name
  # Issue #393 — workspace/static/js/applicantMind.js:65 (ui.js:378 toast = GREEN)
  # Requirement: Icon and glyph-only buttons MUST carry an explicit aria-label as their accessible name.

  Scenario: The toast dismiss button has an explicit accessible name
    Given the shared toast helper module
    When the dismiss button is inspected
    Then it sets an explicit aria-label rather than relying on a tooltip

  @pending
  Scenario: The overlay glyph-only close buttons have an explicit accessible name
    Given the memory dialog module
    When its close button is inspected
    Then the glyph-only close button sets an explicit aria-label
