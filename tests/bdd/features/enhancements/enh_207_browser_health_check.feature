# Issue #207 — prefill loop resilience / application/services/prefill_service.py:_continue_pages
# The page-walk loop wraps no browser call in try/except. A browser crash propagates a raw
# exception to the orchestrator: no PrefillResult, no FAILED state, no pending action.
# GREEN: a healthy walk returns a structured PrefillResult. @pending: a browser crash mid-
# loop is caught and returned as a FAILED PrefillResult instead of propagating.

Feature: A browser crash in the pre-fill loop yields a structured failure

  Scenario: A healthy pre-fill walk returns a structured result
    Given a healthy in-memory browser walking the application flow
    When the engine runs the pre-fill loop
    Then a structured pre-fill result is returned

  Scenario: A browser crash mid-loop returns a failed result, not a raw exception
    Given a browser that crashes partway through the page walk
    When the engine runs the pre-fill loop
    Then a failed pre-fill result is returned rather than the exception escaping
