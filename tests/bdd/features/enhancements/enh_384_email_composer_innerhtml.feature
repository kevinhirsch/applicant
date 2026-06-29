Feature: Received-email HTML is sanitized before the composer renders it
  # Issue #384 — workspace/static/js/document.js:2525 (sink) via _emailBodyToHtml (:2245)
  # Requirement: The front-door MUST pass received-email HTML through an allowlist sanitizer
  # (or a script-disabled sandboxed iframe) before any innerHTML assignment in the email composer.

  Scenario: The email reader already sanitizes received bodies before display
    Given the email reader library module
    When the received-body render path is inspected
    Then it routes the body through the shared email sanitizer

  @pending
  Scenario: The composer sanitizes the body before assigning it to innerHTML
    Given the document composer module
    When the rich-body render path is inspected
    Then the email body is sanitized before the innerHTML assignment instead of being used verbatim
