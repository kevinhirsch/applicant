Feature: Concurrent sandbox sessions are independent and ephemeral
  # FR-SANDBOX-4 — adapter: src/applicant/adapters/sandbox/local_sandbox.py
  # Requirement: The sandbox MUST support multiple concurrent, independently
  # controllable sessions, and tearing one down MUST leave the other live (ephemeral,
  # idempotent teardown).

  Scenario: Two applications run in independent, ephemeral sandboxes
    Given a local sandbox provider
    When sandboxes are provisioned for two different applications
    Then the two sessions are distinct and both live
    When one of the sandboxes is torn down
    Then only the other session remains live
