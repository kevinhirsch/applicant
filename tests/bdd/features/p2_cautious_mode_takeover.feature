Feature: Cautious mode pauses on detection and hands off for takeover
  # master spec §10 / FR-PREFILL-6, FR-STEALTH, FR-SANDBOX-2/3, FR-NOTIF-2

  Scenario: A detection signal pauses pre-fill and hands off via VNC
    Given an approved role being pre-filled in a sandbox
    And cautious mode is enabled
    When an automation-detection signal appears on the page
    Then pre-fill pauses in a detection-blocked state
    And a take-over pending action with a live-session link is created
    And the engine never solves the challenge

  Scenario: From the live session the user authorizes the engine to finish
    Given an application awaiting final approval in a live session
    When the user authorizes the engine to finish
    Then the engine finishes friction-free and a submitted outcome is recorded

  Scenario: From the live session the user submits themselves
    Given an application awaiting final approval in a live session
    When the user submits themselves in the live session
    Then a user-submitted outcome is recorded
