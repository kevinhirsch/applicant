# Issue #185 — app/config.py SCHEDULER_ENABLED + app/lifespan.py
# SCHEDULER_ENABLED now defaults to true so the engine auto-ticks out of the box; the test lane
# still spins a safe background loop. The default is now True, and the
# lifespan gate is GREEN. The prior concern — a local run
# being dormant out of the box — is now addressed (#185). —
# is not addressed → @pending.

  Feature: The 24/7 scheduler is enabled by default

  Scenario: The scheduler is on by default so the engine auto-ticks out of the box
    Given default engine settings
    Then the scheduler is enabled
    And a sensible tick interval is still configured

  Scenario: Setting the env flag enables the scheduler
    Given settings with the scheduler env flag turned on
    Then the scheduler is enabled

  Scenario: A production profile auto-enables the loop without a manual env flag
    Given default engine settings
    Then a deployment profile reports the scheduler should run
