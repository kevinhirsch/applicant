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
