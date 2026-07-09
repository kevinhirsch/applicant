"""Versioned SQLite schema migrations for the workspace DB.

The engine has Alembic; the workspace historically had nothing — its SQLite
schema evolved through a pile of idempotent, ``PRAGMA``-guarded ``_migrate_*``
functions in :mod:`core.database`, each hand-appended to ``init_db()`` and each
re-scanning the table on every boot. That works, but it has no version marker,
no ordering guarantee, no record of what ran, and no way to say "this change is
already applied, skip it" except by re-probing the schema.

This module is the workspace's answer to Alembic, with **zero extra
dependencies**: a numbered migration registry keyed off SQLite's native
``PRAGMA user_version`` counter.

Contract
--------
* ``user_version == 0`` is the **baseline** — the schema a DB has after
  ``Base.metadata.create_all`` plus the legacy ``_migrate_*`` sweeps. Those
  sweeps stay where they are; this framework governs everything *forward* of
  them.
* Each :class:`Migration` bumps ``user_version`` to its ``version`` once its
  ``up`` body has run.
* Migrations run in ascending ``version`` order, **each in its own
  transaction**. A failure rolls that one migration back and *halts the run* —
  later migrations are never applied to a half-migrated DB.
* Only migrations with ``version > current user_version`` run, so a second call
  is a no-op. Safe to call on every boot.
* Every applied migration is also recorded in a ``schema_migrations`` table
  (``version, name, applied_at``) for human-readable history, independent of the
  ``user_version`` integer.

Adding a schema change
----------------------
Append a :class:`Migration` to :data:`MIGRATIONS` with the next integer
``version`` (contiguous from 1) and a body that takes a raw ``sqlite3``
connection. Prefer ``... IF NOT EXISTS`` / column-existence guards inside the
body so a partially-upgraded DB (e.g. a column already added by a legacy
``_migrate_*`` in an overlapping release) still converges. **Never edit or
renumber a migration that has shipped** — released databases have already
recorded that version and will skip it forever.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """One forward-only schema change.

    ``up`` receives an open ``sqlite3.Connection`` already inside a transaction;
    it must not commit or close it (the runner owns the transaction lifecycle).
    """

    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def _columns(conn: sqlite3.Connection, table: str) -> set:
    """Column names of ``table`` (empty set if the table doesn't exist)."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# --------------------------------------------------------------------------- #
# Migration bodies. Keep each small, guarded, and forward-only.
# --------------------------------------------------------------------------- #

def _m001_scheduled_tasks_owner_type_index(conn: sqlite3.Connection) -> None:
    """Composite index for the per-owner housekeeping/action sweeps.

    ``task_scheduler`` runs several ``ScheduledTask.owner == owner AND
    task_type == ...`` queries on every scheduler pass (housekeeping reconcile,
    retired-action purge, builtin-task lookup). Only ``owner`` alone and
    ``(status, next_run)`` were indexed; this covers the owner+type hot path.
    Table-only guard is unnecessary — ``scheduled_tasks`` always exists by the
    time versioned migrations run (created in the baseline)."""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_owner_type "
        "ON scheduled_tasks(owner, task_type)"
    )


# The ordered registry. The *only* thing to edit when adding a schema change.
MIGRATIONS: List[Migration] = [
    Migration(1, "scheduled_tasks owner+task_type index",
              _m001_scheduled_tasks_owner_type_index),
]


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def _get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA doesn't accept bound params; version is our own int, not user input.
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _ensure_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  applied_at TEXT NOT NULL"
        ")"
    )
    conn.commit()


def head_version(migrations: List[Migration] = MIGRATIONS) -> int:
    """Highest registered version (0 when the registry is empty)."""
    return max((m.version for m in migrations), default=0)


def validate_registry(migrations: List[Migration] = MIGRATIONS) -> None:
    """Guard against a mis-authored registry: versions must be unique and form a
    contiguous ``1..N`` sequence in list order. Raises ``ValueError`` otherwise —
    called at boot so a bad migration list fails loudly, not silently mid-upgrade."""
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError(
            f"schema migrations must be numbered contiguously from 1 in order; got {versions}"
        )


def run_migrations(db_path: str, migrations: List[Migration] = MIGRATIONS) -> int:
    """Apply pending versioned migrations to the SQLite file at ``db_path``.

    Returns the resulting ``user_version``. A missing/empty path (e.g. a
    non-SQLite backend) is a no-op returning 0. Never raises for a migration
    body failure — it logs, rolls that migration back, and halts, leaving the DB
    at the last cleanly-applied version.
    """
    if not db_path or not os.path.exists(db_path):
        return 0

    validate_registry(migrations)
    ordered = sorted(migrations, key=lambda m: m.version)

    conn = sqlite3.connect(db_path)
    try:
        _ensure_history_table(conn)
        current = _get_user_version(conn)
        applied = current
        for m in ordered:
            if m.version <= current:
                continue
            try:
                conn.execute("BEGIN")
                m.up(conn)
                _set_user_version(conn, m.version)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (m.version, m.name, datetime.utcnow().isoformat()),
                )
                conn.commit()
                applied = m.version
                logger.info("Applied schema migration v%d: %s", m.version, m.name)
            except Exception:
                conn.rollback()
                logger.exception(
                    "Schema migration v%d (%s) failed; halting at v%d",
                    m.version, m.name, applied,
                )
                break
        return applied
    finally:
        conn.close()


def run_migrations_for_url(database_url: str,
                           migrations: List[Migration] = MIGRATIONS) -> int:
    """Convenience wrapper: run migrations for a ``sqlite:///`` DATABASE_URL.

    No-op (returns 0) for non-SQLite URLs — the workspace only ships SQLite, and
    a Postgres/other backend would manage its own schema."""
    if not database_url or "sqlite" not in database_url:
        return 0
    return run_migrations(database_url.replace("sqlite:///", ""), migrations)
