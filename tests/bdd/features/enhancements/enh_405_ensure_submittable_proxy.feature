Feature: The review gate's submittability check is reachable from the front-door
  # Issue #405 — engine POST /api/documents/applications/{id}/ensure-submittable
  # (documents.py:389); no proxy/client/JS. Requirement: The front-door SHOULD be able to
  # query submittability explicitly (to drive the review UI), backed by the existing endpoint.

  Scenario: The engine enforces the submittability gate today
    Given the engine review-gate boot smoke
    When the ensure-submittable endpoint is inspected on the engine
    Then the engine exposes the ensure-submittable review gate

  @pending
  Scenario: A front-door path queries ensure-submittable
    Given the front-door documents engine client
    When submittability is queried through the front-door
    Then the engine client exposes an ensure-submittable method
