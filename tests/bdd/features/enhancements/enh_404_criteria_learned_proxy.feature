Feature: A learned criteria adjustment can be applied from the front-door
  # Issue #404 — engine POST /api/criteria/{id}/learned (criteria.py:85); no proxy/client
  # Requirement: If learned adjustments are operator-applicable from the UI, the front-door
  # MUST expose them via a proxy + client method that POSTs to /api/criteria/{id}/learned.

  Scenario: The front-door applies a learned criteria adjustment
    Given the front-door criteria engine client
    When a learned criteria adjustment is applied through the front-door
    Then the engine client exposes an apply-learned-adjustment method
