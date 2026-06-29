# Issue #208 — prefill state access / application/services/prefill_service.py:_check_detection etc.
# Several places chain attribute access on current_state(aid).url / .detection_signals. The
# port says current_state returns PageState, but a failing implementation that returns None
# makes every chain an AttributeError. GREEN: a well-behaved source returns a PageState the
# loop reads safely. @pending: a None-returning source is guarded rather than crashing.

Feature: Chained page-state access is guarded against a None page state

  Scenario: A well-behaved source returns a page state the loop reads
    Given a browser whose current state is a real page snapshot
    When the engine reads the current page state
    Then the page url is available

  @pending
  Scenario: A None page state is handled instead of raising an attribute error
    Given a browser whose current state returns nothing
    When the engine inspects the current page state during detection
    Then the engine handles the missing state rather than raising an attribute error
