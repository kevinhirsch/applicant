# Issue #185 — app/config.py SCHEDULER_ENABLED + app/lifespan.py
# SCHEDULER_ENABLED defaults to false so the hermetic test lane / TestClient never
# spins a live background loop. That default is intentional and documented, so the
# default value + the lifespan gate are GREEN. The residual concern — a local run
# is dormant out of the box with no profile that auto-enables it for a real deploy —
# is not addressed → @pending.

  Feature: The 24/7 scheduler is gated on an explicit opt-in

  Scenario: The scheduler is off by default so the hermetic lane never auto-ticks
    Given default engine settings
    Then the scheduler is disabled
    And a sensible tick interval is still configured

  Scenario: Setting the env flag enables the scheduler
    Given settings with the scheduler env flag turned on
    Then the scheduler is enabled

  @pending
  Scenario: A production profile auto-enables the loop without a manual env flag
    Given default engine settings
    Then a deployment profile reports the scheduler should run
