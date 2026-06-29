Feature: Applicant modal overlays trap keyboard focus within the dialog
  # Issue #380 — workspace/static/js/applicantOnboarding.js:179
  # Requirement: Modal overlays (especially the blocking first-run wizard) MUST trap Tab and Shift+Tab within the dialog.

  Scenario: The blocking setup wizard presents itself as a modal dialog
    Given the first-run setup wizard module
    When the overlay markup is inspected
    Then it declares itself a modal dialog with an accessible name

  Scenario: The setup wizard keeps Tab focus inside the dialog
    Given the first-run setup wizard module
    When the wizard is inspected for a focus-trap handler
    Then a keydown handler wraps Tab and Shift+Tab focus within the dialog
