Feature: The session cookie can be marked Secure for TLS deployments
  # Issue #269 — workspace/routes/auth_routes.py session cookie (around line 136-146)
  # The login route now derives the cookie Secure flag from the SECURE_COOKIES env var, so an
  # operator behind HTTPS can opt the cookie into Secure (GREEN). The residual gap is that the
  # flag is not auto-derived from a forwarded HTTPS scheme (X-Forwarded-Proto), so a TLS
  # reverse-proxy deployment that forgets the env still emits an insecure cookie → @pending.

  Scenario: Enabling the secure-cookies setting marks the cookie Secure
    Given the session-cookie secure setting is enabled
    When the cookie secure flag is resolved from configuration
    Then the resolved cookie secure flag is true

  Scenario: Leaving the secure-cookies setting off keeps the localhost default
    Given the session-cookie secure setting is left at its default
    When the cookie secure flag is resolved from configuration
    Then the resolved cookie secure flag is false

  Scenario: A forwarded HTTPS scheme auto-marks the cookie Secure
    Given a request forwarded over HTTPS by a reverse proxy
    When the cookie secure flag is resolved from the request scheme
    Then the cookie is marked Secure even without the explicit setting
