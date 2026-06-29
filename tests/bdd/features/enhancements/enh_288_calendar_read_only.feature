# Issue #288 — Calendar integration is read-only — workspace/routes/applicant_internal_routes.py
# The engine reads auto-detected interviews from the operator's calendar via the
# token-gated internal callback (GET /calendar/interviews). That passive detection ships
# (GREEN): the interview-detection rule is pure and the read endpoint exists. The engine
# cannot WRITE events (reminders, review blocks, deadlines) — the create direction is
# absent, so the @pending scenario probes the missing write seam.

Feature: Calendar integration detects interviews but cannot create events

  Scenario: Interview-like events are detected from raw calendar entries
    Given a set of raw calendar events including an interview invite
    When the interview-detection rule runs over them
    Then the interview event is detected and the plain meeting is not

  Scenario: The engine reads interviews over the internal calendar channel
    Given the front-door internal callback routes
    When the internal routes are inspected
    Then a calendar interviews read path is present

  @pending
  Scenario: The engine writes a calendar event for a review block
    Given the front-door internal callback routes
    When a calendar write channel is looked up
    Then an endpoint to create a calendar event is available
