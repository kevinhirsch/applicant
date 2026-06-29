# Issue #205 — prefill field fill / application/services/prefill_service.py:_fill_current_page
# When fill_field raises, the handler emits an error then `continue`s, skipping the
# audit-trail updates (page_log, sensitive_filled_from_explicit / sensitive_declined). A
# sensitive field that fails to fill leaves no trace that the engine tried. GREEN: a soft
# fill failure still emits an error pending action and never crashes. @pending: the failed
# field is recorded in the page log before the continue.

Feature: A failed field fill leaves an audit trail

  Scenario: A soft fill failure emits an error and the loop keeps going
    Given a page where one field fill raises an error
    When the engine fills the page
    Then an error pending action names the failed field and the run continues

  @pending
  Scenario: A failed sensitive field is still recorded in the page log
    Given a page where a sensitive field fill raises an error
    When the engine fills the page
    Then the failed field is recorded in the page log audit trail
