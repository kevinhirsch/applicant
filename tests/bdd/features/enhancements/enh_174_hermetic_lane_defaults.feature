Feature: Real integrations are opt-in and a production preset could flip them together
  # Issue #174 — app/config.py: default lane is entirely hermetic (5 separate flags)
# The engine ships every real integration defaulting to fake/stub, so a new user must
# discover and set BROWSER_REAL, DISCOVERY_LIVE, NOTIFICATIONS_LIVE,
# ORCHESTRATOR_BACKEND=dbos and SCHEDULER_ENABLED before anything real happens.
# GREEN: the safe-by-default postures are real, shipped behaviour. PENDING: a single
# production-mode preset (APPLICANT_MODE=production) that flips them together now exists.

  Scenario: A fresh install does no real outbound work until each integration is opted in
    Given default engine settings
    Then the live browser, live discovery and live notifications are all off by default
    And the orchestrator runs the in-process shim and the scheduler is enabled

  Scenario: A single production-mode preset flips every real integration on at once
    Given an operator wants the engine to do real work
    When a combined production-mode preset is requested
    Then one setting enables the live browser, live discovery, live notifications, durable orchestration and the scheduler together
