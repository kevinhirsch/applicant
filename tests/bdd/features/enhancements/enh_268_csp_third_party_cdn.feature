Feature: The content-security policy does not trust a third-party CDN for scripts
  # Issue #268 — workspace/core/middleware.py:82 CSP script-src includes https://cdn.jsdelivr.net
  # KaTeX and Mermaid load from jsDelivr, so script-src trusts a third-party CDN — a supply-chain
  # surface for a privacy-first self-hosted product. Self-hosting these assets (removing the CDN
  # from script-src) is not done yet → @pending probe on the emitted CSP header.

  @pending
  Scenario: No third-party CDN is allowed in the script-src directive
    Given the security-headers middleware
    When the content-security policy for a normal page is produced
    Then the script-src directive does not allow a third-party CDN
