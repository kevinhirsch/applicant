# Issue #336 — browser crash recovery / adapters/browser/page_source.py (PlaywrightPageSource)
#   + application/services/prefill_service.py:_continue_pages
# Requirement: The engine MUST catch browser-disconnection failures (TimeoutError /
#   TargetClosedError) raised during the pre-fill page walk and return a structured
#   FAILED pre-fill result, never letting the raw browser exception escape the loop.
# Related existing issues: #207 (no browser health check before the walk), #212
#   (_settle swallows the load-state timeout).
# GREEN: a healthy in-memory browser walks the flow and yields a structured result.
# PENDING: a browser that crashes mid-walk yields a FAILED result rather than an escape.

Feature: A browser crash during pre-fill yields a structured failure, not an escape

  Scenario: A healthy browser walk returns a structured pre-fill result
    Given a healthy in-memory browser walking the application flow
    When the engine runs the pre-fill page walk
    Then a structured pre-fill result is returned

  Scenario: A browser tab crash returns a failed result instead of propagating
    Given a browser whose tab closes unexpectedly partway through the walk
    When the engine runs the pre-fill page walk
    Then a failed pre-fill result is returned rather than the browser error escaping

  Scenario: A hung browser operation is bounded rather than hanging the pipeline
    Given a browser whose page operation times out mid-walk
    When the engine runs the pre-fill page walk
    Then the timeout is caught and a failed pre-fill result is returned
