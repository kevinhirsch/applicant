Feature: The app_api loopback tool is bounded by an explicit allowlist, not a blocklist
  # Issue #313 — workspace/src/tool_implementations.py:2607-2760 (do_app_api)
  # Requirement: The app_api LLM tool MUST gate reachable endpoints with an explicit
  # allowlist of permitted path prefixes so a newly-added route is NOT reachable by
  # default; a path outside the allowlist is refused.

  Scenario: Auth, user, and admin endpoints are refused today
    Given the app_api loopback tool blocklist
    When a sensitive endpoint prefix is checked against it
    Then the auth, user, and admin prefixes are refused

  Scenario: A newly added endpoint is denied by default under an allowlist
    Given the app_api loopback tool exposes an explicit allowlist of permitted prefixes
    When a brand-new endpoint that nobody allowlisted is requested
    Then the request is refused because it is not on the allowlist

  # Regression coverage for the method-suffix fence added alongside the
  # allowlist: the applicant engine's two final-submit stop-boundary
  # controls (submit-self / authorize-engine-finish) sit after a dynamic
  # {application_id} segment, so only a suffix match can fence them off.
  Scenario: The submit-self stop-boundary control is refused via the generic loopback
    Given the app_api loopback tool's final-submit stop-boundary suffix fence
    When a POST call to an application's submit-self path is attempted
    Then the call is refused with the final-submit stop-boundary error and no request reaches the network

  Scenario: The authorize-engine-finish stop-boundary control is refused via the generic loopback
    Given the app_api loopback tool's final-submit stop-boundary suffix fence
    When a POST call to an application's authorize-engine-finish path is attempted
    Then the call is refused with the final-submit stop-boundary error and no request reaches the network

  Scenario: A non-terminal allowlisted applicant path is not blocked by the suffix fence
    Given the app_api loopback tool's final-submit stop-boundary suffix fence
    When a call to a non-terminal applicant control path is attempted
    Then the call is not refused by the suffix fence and reaches the network dispatch stage

  Scenario: Endpoint discovery excludes the two final-submit stop-boundary paths
    Given the app_api loopback tool's final-submit stop-boundary suffix fence
    When the endpoints discovery action is requested over a sample OpenAPI listing containing both stop-boundary paths
    Then the submit-self and authorize-engine-finish entries are excluded from the discovered endpoints
