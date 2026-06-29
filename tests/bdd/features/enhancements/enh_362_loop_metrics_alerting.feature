Feature: The 24/7 loop emits operational metrics and alerts on consecutive tick failures
  # Issue #362 — observability/ (only logging.py today), application/services/scheduler.py
  # Requirement: The engine MUST emit operational metrics (tick success/failure, scheduler
  # liveness/heartbeat, queue depth, LLM call count, prefill outcomes) and MUST surface an
  # operator alert when the loop stalls or fails N consecutive ticks, through the existing
  # notification ladder where possible — not merely a log line.
  #
  # observability/ contains only logging.py; a search for prometheus/opentelemetry/statsd/
  # histogram emitters returned 0. All three scenarios are now GREEN: structured logging of
  # each scheduler tick already shipped; the metrics/heartbeat surface
  # (observability/metrics.py) and the consecutive-failure operator alert (wired into the
  # Scheduler through the existing NotificationService ladder) are now built and asserted
  # hermetically with an injected clock.

  Scenario: Each scheduler tick is recorded through structured logging
    Given the engine structured-logging surface
    When a scheduler tick completes
    Then the tick is captured as a redacted structured log event

  Scenario: A metrics/heartbeat surface exists and updates on every tick
    Given the observability metrics surface
    When the loop ticks
    Then a tick counter and a scheduler-liveness heartbeat are updated for that tick

  Scenario: N consecutive failed ticks raise a surfaced operator alert
    Given the loop has failed several consecutive ticks
    When the consecutive-failure threshold is crossed
    Then a surfaced operator alert is raised rather than only a log line

  Scenario: The scheduler raises one operator alert through the notification ladder on a sustained stall
    Given a scheduler whose every campaign tick fails
    When the failure threshold of consecutive ticks is crossed
    Then exactly one operator alert is surfaced through the notification ladder
