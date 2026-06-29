Feature: Desktop co-working targets windows in the background, never stealing focus
  # FR-CUA-7 — port + adapter: ports/driven/computer_use.py, adapters/sandbox/computer_use/
  # Requirement: The computer-use port MUST document a background, no-foreground-steal
  # contract for window targeting, and the sandbox adapter MUST honor it (record the
  # focus call without actually foregrounding).

  Scenario: The port contract is background, no foreground steal
    Given the computer-use desktop port
    When the window-targeting action contract is inspected
    Then the contract states the window is targeted in the background without stealing focus

  Scenario: The sandbox adapter records a background focus without foregrounding
    Given a sandboxed desktop backend
    When a window is targeted for co-working
    Then the focus action is recorded as performed without taking the foreground
