Feature: Email inbox surfaces dynamic UI-module load failures
  # Issue #329 — workspace/static/js/emailInbox.js (lines 679, 710, 716, 883, 909, 1194, 1209)
  # Requirement: When the email inbox lazily imports ./ui.js to show a toast/error and that
  # import fails, the front-door MUST NOT silently discard the failure with an empty
  # .catch(() => {}); and localStorage access for the last-seen UID MUST be guarded so a
  # storage exception does not break the inbox.

  # GREEN — the unread-dot localStorage read is wrapped in a guarding try/catch.
  Scenario: Reading the last-seen UID is protected against storage errors
    Given the email inbox browser module
    When the unread-dot last-seen read is inspected
    Then the localStorage access is wrapped in a try block

  Scenario: A failed ui.js import for an inbox toast is not swallowed silently
    Given the email inbox browser module
    When the lazy ui.js imports are scanned
    Then none of them end in an empty catch handler

  Scenario: Persisting the last-seen UID is guarded against storage errors
    Given the email inbox browser module
    When the last-seen UID write is inspected
    Then the localStorage write is wrapped in a try block
