# Issue #232 — workspace/routes/applicant_email_routes.py + applicant_chat_routes.py
# The email route guards the engine's campaign response with isinstance(data, list)
# before handing it to the frontend, so an engine shape change degrades to an empty
# list instead of leaking a dict — that guard IS GREEN. The chat route returns
# `campaigns or []` with NO isinstance guard, so a dict-shaped engine response would
# pass straight through and crash the frontend iteration → @pending.

  Feature: Campaign-list proxies validate the engine response shape

  Scenario: The email route coerces a non-list engine response to an empty list
    Given the campaign-list shape guard used by the email route
    When the engine returns a dict instead of a bare list
    Then the guard yields an empty list

  Scenario: The email route passes a real list through unchanged
    Given the campaign-list shape guard used by the email route
    When the engine returns a bare list of campaigns
    Then the guard yields that same list

  Scenario: The chat route also guards a non-list engine response
    Given the chat campaign-list route source
    Then it validates the campaign response is a list before returning it
