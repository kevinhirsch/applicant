# Issue #241 — adapters/storage/in_memory.py (commit / rollback)
# commit() finalizes pending changes; rollback() discards uncommitted writes.
# Writes are applied immediately (backward-compatible) but each mutation records
# an undo action in the undo log. commit() discards the undo log (finalizes).
# rollback() replays undos in reverse order (discards uncommitted changes).

  Feature: In-memory storage models transactional commit / rollback

  Scenario: A committed write is readable
    Given a fresh in-memory storage
    When a campaign is added and the unit of work is committed
    Then the campaign is readable

  Scenario: commit and rollback are callable on the storage port
    Given a fresh in-memory storage
    Then commit and rollback can be invoked without error

  Scenario: Rolling back an uncommitted write discards it
    Given a fresh in-memory storage
    When a campaign is added and then the unit of work is rolled back
    Then the campaign is no longer present
