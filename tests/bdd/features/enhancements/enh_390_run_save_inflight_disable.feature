Feature: Save run settings disables itself while saving
  # Issue #390 — workspace/static/js/applicantDebug.js:497 (#applicant-run-save)
  # Requirement: The Save run settings button MUST disable for the request duration and re-enable in a finally block, matching the Run-now and Pause controls.

  Scenario: Run-now and Pause disable in flight (the pattern to match)
    Given the Activity/Debug browser module
    When the Run-now and Pause click handlers are inspected
    Then each disables its button while the request is in flight and re-enables it afterwards

  @pending
  Scenario: The Save button guards against a double submit
    Given the Activity/Debug browser module
    When the Save run settings click handler is inspected
    Then it disables the Save button while saving and re-enables it in a finally block
