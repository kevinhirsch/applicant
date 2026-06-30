# Issue #244 — adapters/storage/alembic/versions/0001_initial.py vs models.JSONType
# The models declare JSONType = JSON().with_variant(JSONB(), "postgresql"), and the
# later migration 0006 mirrors that variant for `provenance` — GREEN. But 0001_initial
# uses bare sa.JSON() for every JSON column, so an alembic-built DB gets `json` while a
# create_all-built DB gets `jsonb`; jsonb operators/indexes can't be used on the
# earlier columns → @pending.

  Feature: JSON columns are jsonb on Postgres across both build paths

  Scenario: The ORM JSON type maps to JSONB on Postgres
    Given the storage models module
    Then the ORM JSON column type uses the postgresql JSONB variant

  Scenario: The provenance migration mirrors the JSONB variant
    Given the material-provenance migration
    Then the provenance migration JSON column type uses the postgresql JSONB variant

  Scenario: The initial migration declares JSONB-variant columns
    Given the initial schema migration source
    Then it uses the JSONB-variant type rather than a bare JSON type
