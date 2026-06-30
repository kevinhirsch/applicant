# Issue #198 — _force_status bypasses the state machine (application/services/agent_loop.py) — §7 state machine
# GREEN: regression proving the validated path (with_status) DOES enforce §7, and proving
#        the documented bypass — dataclasses.replace lands an illegal state with no check.
# PENDING: the fix — a force/sync path that still validates §7 so no caller can jump
#          straight to a terminal state silently.

Feature: Forcing an application status still honors the legal transition table

  Scenario: The validated path rejects an illegal jump to a terminal state
    Given an application in the discovered state
    When it is advanced through the validated status path to a terminal state directly
    Then the illegal transition is refused

  Scenario: A raw dataclass replace bypasses the state machine entirely
    Given an application in the discovered state
    When its status is set with a raw dataclass replace to a terminal state
    Then the status changed with no transition validation

  Scenario: The status-sync path validates the transition before persisting
    Given an application in the discovered state
    When the engine syncs it to a terminal state through a validated force path
    Then the illegal jump is refused rather than silently forced
