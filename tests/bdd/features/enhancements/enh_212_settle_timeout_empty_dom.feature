# Issue #212 — page settle / adapters/browser/page_source.py:_settle (PlaywrightPageSource)
# _settle swallows a wait_for_load_state timeout with a bare pass and proceeds on a
# possibly-empty DOM; detect_fields then finds zero fields and the loop reaches final
# approval with nothing filled. GREEN: a page that does settle yields its fields. @pending:
# a settle timeout is surfaced (warning / structured error) rather than silently passing.

Feature: A page-settle timeout is surfaced instead of yielding an empty form

  Scenario: A page that settles exposes its detected fields
    Given a fully rendered application page
    When the engine detects fields on the page
    Then the expected fields are returned

  @pending
  Scenario: A settle timeout reports the stall rather than passing silently
    Given a page whose load-state wait times out
    When the engine settles the page before inspecting it
    Then the timeout is surfaced rather than swallowed by a bare pass
