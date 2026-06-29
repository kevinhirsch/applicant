Feature: Forward migration on a populated database preserves data and matches the models
  # Issue #365 — tests/unit/test_migration_revision_ids.py (exists); no populate→upgrade→verify
  # Requirement: A test MUST stand up a database at a prior revision with representative rows,
  # run `alembic upgrade head`, and assert (a) every seeded row survives with correct values
  # and (b) the upgraded schema matches the SQLAlchemy models (no drift).
  #
  # Today the migration tests check only revision-id length and json-vs-jsonb operator safety
  # — nothing populates an old revision and upgrades it. The first scenario is GREEN
  # regression coverage for the revision-id guard; the data-integrity upgrade is @pending.

  Scenario: Every migration revision id fits the alembic_version column
    Given the Alembic revision set on disk
    When each revision id length is checked
    Then no revision id exceeds the alembic_version column width

  @pending
  Scenario: Upgrading a populated prior-revision database keeps data intact and schema in sync
    Given a database stamped at a prior revision and seeded with representative rows
    When the database is upgraded to head
    Then every seeded row survives with correct values and the schema matches the models
