Feature: Cookie-authed state-changing requests are protected against cross-site forgery
  # Issue #381 — workspace/core/middleware.py, workspace/routes/auth_routes.py:140
  # Requirement: The front-door MUST CSRF-protect cookie-authenticated non-GET /api/*
  # requests server-side (a same-origin Origin/Referer allowlist in middleware OR a
  # per-session double-submit token).
  #
  # GREEN regression: clickjacking IS handled today — X-Frame-Options DENY
  # (middleware.py:83) + CSP frame-ancestors 'none' (middleware.py:99), and script-src
  # is nonce-based with no 'unsafe-inline' (middleware.py:92). The @pending scenario
  # probes the missing CSRF seam (no Origin/Referer check, no token anywhere today).

  Scenario: Pages cannot be framed by another origin
    Given the front-door security-headers middleware
    When the response headers for a normal page are produced
    Then framing is denied for any other origin

  Scenario: Inline scripts cannot execute under the page policy
    Given the front-door security-headers middleware
    When the content-security policy for a normal page is produced
    Then the script policy is nonce-based and does not allow inline scripts

  @pending
  Scenario: A cross-site forged state change is refused
    Given a cookie-authenticated state-changing request from a foreign origin
    When the request reaches the front-door request guard
    Then the forged cross-origin request is refused by a server-side CSRF guard
