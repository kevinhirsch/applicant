Feature: Engine warns when it falls back to in-memory storage at boot
  # Issue #312 — src/applicant/app/container.py _build_storage
  # On a DB connect/healthcheck failure the engine returns InMemoryStorage so it
  # always boots. Today that fallback is SILENT — a transient Postgres outage brings
  # the engine up on an ephemeral store with zero signal. The boot-resilience
  # behavior is GREEN regression coverage; the operator warning is @pending.

  Scenario: An unreachable database falls back to in-memory so the engine still boots
    Given a database URL that cannot be reached
    When the storage layer is built
    Then an in-memory storage is returned so the app can boot

  @pending
  Scenario: Falling back on a configured database emits an operator warning
    Given a configured (non-default) database URL that cannot be reached
    When the storage layer falls back to in-memory
    Then a warning is logged naming the DSN host but never the credentials
