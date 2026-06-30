Feature: Externally-loaded scripts carry integrity protection and styles are policy-restricted
  # Issue #383 — workspace/static/index.html:204-205, workspace/core/middleware.py:90-93
  # Requirement: Externally-loaded scripts MUST carry a Subresource Integrity hash (or be
  # self-hosted), and the page style policy MUST migrate off 'unsafe-inline'.
  #
  # GREEN regression: script-src is already nonce-based with no 'unsafe-inline'
  # (middleware.py:92). The @pending scenarios probe the residual gaps: the CDN
  # script tags lack integrity= today, and style-src still allows 'unsafe-inline'.

  Scenario: Inline scripts cannot execute under the page policy
    Given the front-door security-headers middleware
    When the content-security policy for a normal page is produced
    Then the script policy is nonce-based and does not allow inline scripts

  Scenario: Every external script declares an integrity hash
    Given the front-door application HTML shell
    When its externally-loaded script tags are inspected
    Then each external script carries a subresource integrity hash

  @pending
  Scenario: The style policy no longer allows inline styles
    Given the front-door security-headers middleware
    When the content-security policy for a normal page is produced
    Then the style policy does not allow inline styles
