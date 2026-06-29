# Issue #241 — adapters/storage/in_memory.py (commit / rollback)
# InMemoryStorage.commit() and rollback() are no-ops; every write is immediately
# durable. The no-op commit IS the current contract (a service that writes then
# commits reads back its write) — GREEN. But because rollback() does nothing, a
# write followed by rollback STILL leaves the data, so tests cannot catch a service
# that forgot to commit or that should have rolled back a partial write → @pending.

  Feature: In-memory storage models transactional commit / rollback

  Scenario: A committed write is readable
    Given a fresh in-memory storage
    When a campaign is added and the unit of work is committed
    Then the campaign is readable

  Scenario: commit and rollback are callable on the storage port
    Given a fresh in-memory storage
    Then commit and rollback can be invoked without error

  @pending
  Scenario: Rolling back an uncommitted write discards it
    Given a fresh in-memory storage
    When a campaign is added and then the unit of work is rolled back
    Then the campaign is no longer present
