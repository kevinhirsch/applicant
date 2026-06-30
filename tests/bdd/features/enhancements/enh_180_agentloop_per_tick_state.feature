# Issue #180 — application/services/agent_loop.py (ResumeLedger) + app/container.py
# The scheduler rebuilds a fresh AgentLoop every tick, so per-instance state is
# discarded. The resume backoff/failure ledger is a process-lived object injected
# into every loop, so it survives the rebuild — that is GREEN. The residual footgun
# (a NEW instance variable silently resets, with nothing to catch it) has no
# enforcement mechanism yet → @pending.

  Feature: Cross-tick agent-loop state survives the per-tick loop rebuild

  Scenario: The resume ledger persists across a rebuilt loop instance
    Given a process-lived resume ledger injected into one agent loop
    When a fresh agent loop is rebuilt for the next tick with the same ledger
    Then the recorded backoff and failure counts are still visible

  Scenario: Each rebuilt loop gets its own state lock but shares the ledger lock
    Given two agent loops rebuilt around the same resume ledger
    Then the two loops have distinct per-loop locks
    And they share the one ledger lock that guards cross-tick state

  Scenario: New per-instance loop state is protected from silent reset
    Given the agent loop module
    Then it declares which instance state is allowed to live only for one tick
