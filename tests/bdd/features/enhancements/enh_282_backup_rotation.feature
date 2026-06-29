Feature: Database backups are pruned so the disk cannot fill indefinitely
  # Issue #282 — scripts/update.sh (backup creation)
  # Every update writes a timestamped backup into .backups/ but nothing ever prunes them, so
  # with frequent updates the disk fills. The script needs configurable retention — a max
  # backup count, a max age, or size-based pruning — applied after each successful backup.
  # A configurable BACKUP_KEEP_COUNT (default 7) now prunes older dumps after each backup
  # via prune_backups → hard regression gate.

  Scenario: Old backups are pruned by a configurable retention policy
    Given the updater script
    When its backup handling is inspected
    Then it prunes old backups by a configurable count or age rather than keeping them forever
