Feature: Email HTML uses an allowlist sanitizer that is idempotent and neutralizes tracking url()
  # Issue #389 — workspace/static/js/emailLibrary/utils.js:136 + emailLibrary.js:2570 / :2765
  # Requirement: The front-door MUST sanitize received email HTML with an allowlist sanitizer
  # (or sandboxed iframe), idempotent to a fixpoint before any re-parse, and MUST neutralize
  # url() in surviving inline styles so opening a message fires no tracking beacon.

  Scenario: The reader wires a sanitizer onto the received-body path
    Given the email reader library module
    When the received-body render path is inspected
    Then it routes the body through the shared email sanitizer

  @pending
  Scenario: The sanitizer is an allowlist rather than a fixed denylist of tags
    Given the email sanitizer helper
    When its strategy is inspected
    Then it keeps only an allowed set of tags rather than removing a fixed denylist

  @pending
  Scenario: Sanitized HTML is not re-parsed before the dangerous styles are neutralized
    Given the email reader library module
    When the thread and quote rendering passes are inspected
    Then the already-sanitized HTML is not handed to another raw DOM parse

  @pending
  Scenario: Inline style url() references are neutralized to block read-receipt beacons
    Given the email sanitizer helper
    When the inline-style scrubbing is inspected
    Then url() references in surviving styles are stripped or blocked
