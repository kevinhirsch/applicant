# Issue #292 — Calendar write + availability — workspace/routes/applicant_internal_routes.py
# The read direction works (GREEN): the engine reads detected interviews over the internal
# channel. The full feature wants the engine to WRITE events (review blocks, follow-up
# reminders, deadlines, prep blocks) and READ availability (vacation -> pause discovery).
# Those write/availability seams do not exist yet, so they are @pending probes.

Feature: Calendar integration — engine creates events and reads availability

  Scenario: The engine reads detected interviews over the internal channel
    Given the front-door internal callback routes
    When the internal routes are inspected
    Then a calendar interviews read path is present

  @pending
  Scenario: The engine creates a follow-up reminder event
    Given the front-door internal callback routes
    When a calendar create-event channel is looked up
    Then an endpoint to create a calendar reminder is available

  @pending
  Scenario: The engine reads operator availability to throttle discovery
    Given the front-door internal callback routes
    When a calendar availability channel is looked up
    Then an endpoint that reports busy or away windows is available
