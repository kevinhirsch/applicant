Feature: The frozen port and container contract is enforced, not just commented
  # Issue #183 — app/container.py, ports/driven, ports/driving, ports/__init__.py
  # The DI container and both port packages are marked "FROZEN for phase agents", but the
  # constraint is purely a comment: no contract test diffs the port Protocol signatures
  # against a baseline, and nothing fails CI when a port method or the container wiring
  # changes. The marker is documented (GREEN) but unenforced (PENDING probe at the seam).

  Scenario: The freeze intent is documented on the ports and container
    Given the port packages and the composition root
    When their freeze markers are inspected
    Then each declares that its definitions are frozen for downstream agents

  Scenario: A drift in a frozen port signature is caught by a contract test
    Given a recorded baseline of the driven and driving port signatures
    When a port Protocol method signature drifts from that baseline
    Then a contract test fails rather than letting the change land silently
