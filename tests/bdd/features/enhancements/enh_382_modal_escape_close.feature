Feature: Dismissible Applicant modals close on the Escape key
  # Issue #382 — workspace/static/js/applicant{Portal,Vault,Remote,Mind}.js
  # Requirement: Every dismissible Applicant modal MUST close on the Escape key.

  Scenario: The digest dialog closes on the Escape key
    Given the email digest dialog module
    When the dialog key handling is inspected
    Then pressing Escape dismisses the dialog

  Scenario: The Portal, Vault, Remote and Mind overlays close on the Escape key
    Given the Applicant overlay modules
    When their key handling is inspected for an Escape dismiss
    Then each dismissible overlay binds an Escape handler that closes it
