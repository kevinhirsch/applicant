# Issue #216 — profile concurrency / adapters/browser/stealth.py:ProfileStore.for_tenant
# profile.visit_count += 1 is an unlocked read-modify-write on a shared dict. Under the
# default sandbox concurrency of 3, two for_tenant() calls for the same tenant can race and
# under-count. GREEN: sequential visits increment correctly and flip is_returning. @pending:
# concurrent visits increment exactly once each (no lost update).

Feature: Per-tenant profile visit counting is correct under concurrency

  Scenario: Sequential visits increment the profile and mark it returning
    Given a fresh profile store
    When the same tenant is visited twice in sequence
    Then the second visit marks the tenant as returning

  @pending
  Scenario: Concurrent visits do not lose a profile increment
    Given a fresh profile store
    When the same tenant is visited from many threads at once
    Then the visit count equals the number of visits with no lost updates
