Feature: A catch-all exception handler enriches unhandled crashes
  # Issue #252 — workspace/app.py exception handlers (around lines 482-497)
  # Only four specific exception types are handled; there is no generic Exception handler, so
  # an unhandled crash returns a bare 500 with no logging enrichment or correlation context.
  # A catch-all handler registration does not exist yet → @pending probe on app.py.

  @pending
  Scenario: A generic unhandled-exception handler is registered
    Given the front-door application module source
    When its registered exception handlers are inspected
    Then a catch-all unhandled-exception handler is registered
