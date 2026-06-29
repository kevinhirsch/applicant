Feature: Pulse animations honor the reduced-motion preference
  # Issue #394 — workspace/static/style.css:34550 (applicantPulse guard at 34716 = GREEN)
  # Requirement: The status-strip pulse animation MUST be disabled under prefers-reduced-motion: reduce.

  Scenario: The Activity run-control pulse is disabled under reduced motion
    Given the front-door stylesheet
    When the run-control pulse animation is inspected
    Then a reduced-motion media query disables it

  @pending
  Scenario: The status-strip pulse is disabled under reduced motion
    Given the front-door stylesheet
    When the status-strip pulse animation is inspected
    Then a reduced-motion media query disables it too
