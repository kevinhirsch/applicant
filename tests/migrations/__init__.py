"""Migration data-integrity harnesses (#365).

Hermetic Alembic forward-migration checks: stand up a database at a prior
revision, seed representative rows, run ``alembic upgrade head``, and verify every
seeded row survives with correct values and the upgraded schema matches the ORM
models. These run against a temp-file SQLite database (no Postgres, no Docker), so
they are importable from the default hermetic test lane.
"""
