Feature: Applicant overlays manage keyboard focus on open and close
  # Issue #379 — workspace/static/js/applicant{Portal,Remote,Vault,Mind}.js
  # Requirement: Every Applicant overlay MUST move focus into the dialog on open and restore focus to the trigger on close.

  Scenario: The digest dialog moves focus into itself when it opens
    Given the email digest dialog module
    When the dialog open path is inspected
    Then it focuses a control inside the dialog on open

  Scenario: The Portal, Remote, Vault and Mind overlays restore focus to their trigger on close
    Given the Applicant overlay modules
    When their open and close paths are inspected for focus management
    Then each one captures the active element on open and restores it on close
