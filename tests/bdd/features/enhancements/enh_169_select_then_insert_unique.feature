# Issue #169 — adapters/storage/app_config_store.py + adapters/tools/tool_settings_sink.py
# Three key/value stores read-then-add() against a UNIQUE column instead of an
# upsert, so two concurrent first-writes of the same key both see "absent" and the
# second commit raises UniqueViolation on real Postgres. The sequential repeat-write
# IS correct today (overwrite-on-existing), so that is GREEN. The concurrency-safe
# upsert primitive (ON CONFLICT / rollback-and-retry) is not built yet → @pending.

  Feature: First-write key/value stores survive a same-key write race

  Scenario: Re-writing the same app-config key overwrites rather than duplicates
    Given an in-memory app-config store
    When the same setup key is written twice with different values
    Then the latest value is read back and there is exactly one entry

  Scenario: Re-saving the same tool toggle overwrites rather than duplicates
    Given an in-memory tool-settings sink
    When the same tool toggle is saved twice
    Then the latest toggle state is read back

  Scenario: A same-key write race resolves with a conflict-safe upsert
    Given the SQL app-config store write path
    When two writers race the first write of the same key
    Then the store resolves the conflict with an upsert instead of raising
