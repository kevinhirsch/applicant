Feature: Resource-id path parameters are format-validated before the service layer
  # Issue #320 — src/applicant/core/ids.py + every router's bare-str path params
  # Requirement: Resource-id path parameters MUST be format-validated (non-empty,
  # restricted to an id charset, no path-traversal/NUL) before the service layer,
  # rather than accepting any bare string and relying on a later 404.

  Scenario: Domain ids are opaque string NewTypes today
    Given the domain id type definitions
    When a campaign id type is constructed from a string
    Then it behaves as a plain string at runtime

  Scenario: A traversal-shaped id is rejected by a shared validator
    Given a shared id-format validator
    When an id containing path-traversal or a NUL byte is validated
    Then the malformed id is rejected before any lookup
