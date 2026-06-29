Feature: CORS allowed-origins are parsed robustly with whitespace stripped and validated
  # Issue #346 — workspace/app.py:67 (ALLOWED_ORIGINS split)
  # Requirement: The CORS allowed-origins parser MUST strip surrounding whitespace
  # from each entry, drop empties, and accept only well-formed http(s) origins, so a
  # value like "http://foo, " never yields a malformed origin.

  @pending
  Scenario: Whitespace and empty entries are normalized out of the origin list
    Given a shared CORS origin parser
    When an ALLOWED_ORIGINS value with trailing whitespace and an empty entry is parsed
    Then each origin is trimmed and only well-formed origins remain
