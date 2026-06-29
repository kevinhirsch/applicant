Feature: The email escalation delay can never be driven to an instant zero-second blast
  # Issue #236 — adapters/notification/apprise_notifier.py __init__ / configure — FR-NOTIF-2
  # configure() clamps email_timeout_seconds to a 60s floor, but __init__ assigns it raw.
  # A constructor passing 0 makes the email rung due immediately, turning the staged ladder
  # into a simultaneous blast alongside the in-app notification. GREEN pins the configure()
  # clamp that already works; @pending probes the constructor bypass — a 0s timeout via the
  # constructor must still floor the email rung so it does not fire on the same tick as in-app.

  Scenario: Reconfiguring with a sub-floor email timeout is clamped to the minimum
    Given a notifier reconfigured through configure with a zero-second email timeout
    When a normal approval is queued
    Then the email rung is not due immediately

  @pending
  Scenario: A zero-second email timeout passed to the constructor is also floored
    Given a notifier constructed directly with a zero-second email timeout
    When a normal approval is queued
    Then the email rung is not due on the same tick as the in-app surface
