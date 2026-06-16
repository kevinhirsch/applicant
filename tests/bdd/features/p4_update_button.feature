Feature: In-UI update with backup, migration and rollback
  # master spec §10 — FR-OOBE-4, FR-INSTALL-2, NFR-ZEROCLI-1

  Scenario: The update script backs up before migrating, in the safe order
    Given the update script
    Then it backs up the database before running migrations
    And a failure leaves the backup intact for rollback

  Scenario: The update script supports an explicit rollback
    Given the update script
    Then it restores the most recent backup on rollback

  Scenario: The in-UI update trigger is safe by default
    Given the update trigger with no override set
    When the update is triggered
    Then it does not start a destructive update and explains why
