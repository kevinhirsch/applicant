Feature: SSRF guard covers the entry URL and every redirect / subresource hop
  # Issue #310 (references #168) — core rule: core/rules/url_safety.py
  # PR #168 added assert_navigable_url on the ENTRY url in PageSource.open. The
  # residual gap: a public host that 3xx-redirects to an internal/metadata host, and
  # subresource requests, are not re-validated. The first two scenarios are GREEN
  # regression coverage for the shipped entry-URL guard; the redirect/subresource
  # scenarios are @pending until route interception lands.

  Scenario: A non-HTTP(S) scheme is refused before navigation
    Given the URL-safety core rule
    When a "file:///etc/passwd" URL is checked
    Then the scheme is rejected as not navigable

  Scenario: A loopback / metadata / private host is blocked
    Given the URL-safety core rule
    When the resolved IP of a candidate host is on a blocked range
    Then navigation to that host is refused
    And an ordinary public IP is allowed

  @pending
  Scenario: A redirect to an internal host is aborted mid-navigation
    Given a scraped posting URL on a public host that 3xx-redirects to a metadata host
    When the harness follows the navigation
    Then the redirect hop to the blocked host is aborted and no body is captured

  @pending
  Scenario: A subresource request to a blocked host is aborted
    Given a page that issues a subresource request to a private-range host
    When the page loads
    Then the subresource request to the blocked host is aborted by route interception
