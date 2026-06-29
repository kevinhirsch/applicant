Feature: Automation refuses to egress from a datacenter exit
  # FR-STEALTH-4 — adapter: src/applicant/adapters/browser/stealth.py (EgressPolicy)
  # Requirement: The egress policy MUST refuse to launch through a self-flagged
  # datacenter exit and MUST allow a residential (direct) connection.

  Scenario: A self-flagged datacenter exit is refused
    Given an egress policy configured with a non-residential exit
    When the egress policy is validated
    Then the datacenter egress is refused

  Scenario: A residential connection is allowed
    Given an egress policy on the residential connection
    When the egress policy is validated
    Then the egress is permitted
