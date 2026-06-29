# Issue #202 — prefill credential lookup / application/services/prefill_service.py:_lookup_credential
# A broken browser that raises from tenant_of() is swallowed: lookup returns None and
# the application strands with no error, no pending action, no notification. The first
# scenario is GREEN regression coverage for the graceful-degradation contract (a broken
# tenant lookup never crashes the loop); the diagnostic-surfacing behaviour is @pending.

Feature: A broken credential-tenant lookup never crashes but is still surfaced

  Scenario: A failing tenant lookup degrades gracefully instead of crashing
    Given a credential lookup whose tenant resolver crashes mid-call
    When the engine looks up a stored credential
    Then no credential is returned and the loop does not crash

  @pending
  Scenario: A failing tenant lookup is distinguished from a genuinely absent tenant
    Given a credential lookup whose tenant resolver crashes mid-call
    When the engine looks up a stored credential
    Then a diagnostic event records that the tenant lookup failed
