Feature: Automated account creation is off by default and could allow per-tenant credentials
  # Issue #175 — app/config.py + prefill_service.py: ALLOW_AUTOMATED_ACCOUNTS default false
# The account-create submit is a deliberate hand-off (ADR-0004) until the operator opts
# in globally. GREEN: the default is off and the gate honours it. PENDING: there is no
# per-tenant allowance that lets account creation proceed when a stored credential
# already exists for that ATS, so returning users still get a manual hand-off.

  Scenario: Account creation stays a hand-off until the operator opts in
    Given default engine settings
    Then automated account creation is off by default

  @pending
  Scenario: Account creation is allowed for a tenant that already has banked credentials
    Given the global automated-account opt-in is off
    And a stored credential already exists for an ATS tenant
    When the engine reaches that tenant's account-create gate
    Then a per-tenant stored-credential allowance lets it proceed without a manual hand-off
