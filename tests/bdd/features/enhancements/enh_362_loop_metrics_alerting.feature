Feature: The 24/7 loop emits operational metrics and alerts on consecutive tick failures
  # Issue #362 — observability/ (only logging.py today), application/services/scheduler.py
  # Requirement: The engine MUST emit operational metrics (tick success/failure, scheduler
  # liveness/heartbeat, queue depth, LLM call count, prefill outcomes) and MUST surface an
  # operator alert when the loop stalls or fails N consecutive ticks, through the existing
  # notification ladder where possible — not merely a log line.
  #
  # observability/ contains only logging.py; a search for prometheus/opentelemetry/statsd/
  # histogram emitters returns 0. The first scenario is GREEN: structured logging of each
  # scheduler tick already ships. The metrics surface and the consecutive-failure alert are
  # @pending.

  Scenario: Each scheduler tick is recorded through structured logging
    Given the engine structured-logging surface
    When a scheduler tick completes
    Then the tick is captured as a redacted structured log event

  @pending
  Scenario: A metrics/heartbeat surface exists and updates on every tick
    Given the observability metrics surface
    When the loop ticks
    Then a tick counter and a scheduler-liveness heartbeat are updated for that tick

  @pending
  Scenario: N consecutive failed ticks raise a surfaced operator alert
    Given the loop has failed several consecutive ticks
    When the consecutive-failure threshold is crossed
    Then a surfaced operator alert is raised rather than only a log line
