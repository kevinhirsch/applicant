Feature: Every Applicant overlay exposes a dialog role and accessible name
  # Issue #385 — workspace/static/js/applicant*.js (only Onboarding + Mind ship it)
  # Requirement: Every Applicant overlay MUST carry role="dialog", aria-modal="true", and an accessible name.

  Scenario: The setup wizard and the memory dialog expose the dialog contract
    Given the setup wizard and memory dialog modules
    When their overlay markup is inspected
    Then each declares role dialog, aria-modal true, and an accessible name

  Scenario: The Portal, Remote and Vault overlays expose the dialog contract
    Given the Applicant overlay modules
    When their overlay markup is inspected for the dialog contract
    Then each declares role dialog, aria-modal true, and an accessible name too
