"""P3-6 — versioned workspace SQLite schema migrations.

Proves the mechanism the workspace lacked (the engine has Alembic): a numbered
migration registry keyed off ``PRAGMA user_version`` that upgrades an existing
DB cleanly, records history, is a no-op on re-run, and halts safely on failure.

Stdlib-only (``sqlite3`` + the migration module) so it runs in the front-door
``test_applicant_*`` CI gate without the vendored app's heavy deps.
"""

import os
import sqlite3
import tempfile

# Importing anything under ``core`` runs core/__init__ → core.database, whose
# module body calls init_db() against DATABASE_URL. Point it at an in-memory DB
# (as the other core-touching front-door tests do) so import doesn't try to open
# ./data/app.db from the repo-root CWD — then RESTORE the prior value, so this
# sqlite URL doesn't leak into other suites that build the engine app from the
# same process (e.g. the gzip-middleware test).
_prior_db_url = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest  # noqa: E402

from core.schema_migrations import (  # noqa: E402
    MIGRATIONS,
    Migration,
    head_version,
    run_migrations,
    run_migrations_for_url,
    validate_registry,
)

# core.database is now imported + init_db() has run; undo our env change so it
# doesn't perturb engine-app imports elsewhere in the suite.
if _prior_db_url is None:
    os.environ.pop("DATABASE_URL", None)
else:
    os.environ["DATABASE_URL"] = _prior_db_url


def _fresh_db() -> str:
    """A throwaway SQLite file with the baseline scheduled_tasks table at
    user_version 0 (simulating a pre-versioning, post-create_all install)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE scheduled_tasks ("
        " id VARCHAR PRIMARY KEY, owner VARCHAR, name VARCHAR NOT NULL,"
        " task_type VARCHAR DEFAULT 'llm', status VARCHAR)"
    )
    conn.commit()
    conn.close()
    return path


def _indexes(path: str) -> set:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    finally:
        conn.close()


def _user_version(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def test_registry_is_contiguous_from_one():
    """The shipped registry must be well-formed (guards against a dup/gap when a
    future dev appends a migration)."""
    validate_registry(MIGRATIONS)
    assert head_version(MIGRATIONS) == len(MIGRATIONS)


def test_first_schema_change_upgrades_old_db_cleanly():
    """The DoD case: an existing (v0) DB advances to head, gaining the v1 index,
    with its data intact."""
    path = _fresh_db()
    try:
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO scheduled_tasks(id, owner, name) VALUES ('t1','ann','Nightly')")
        conn.commit()
        conn.close()
        assert "ix_scheduled_tasks_owner_type" not in _indexes(path)

        result = run_migrations(path)

        assert result == head_version() == 1
        assert _user_version(path) == 1
        assert "ix_scheduled_tasks_owner_type" in _indexes(path)
        # Data survived the upgrade.
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT owner FROM scheduled_tasks").fetchall()
        conn.close()
        assert rows == [("ann",)]
    finally:
        os.unlink(path)


def test_history_table_records_applied_migrations():
    path = _fresh_db()
    try:
        run_migrations(path)
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        conn.close()
        assert [r[0] for r in rows] == [m.version for m in MIGRATIONS]
        assert rows[0][1]  # name recorded
        assert rows[0][2]  # applied_at timestamp recorded
    finally:
        os.unlink(path)


def test_rerun_is_a_noop():
    path = _fresh_db()
    try:
        assert run_migrations(path) == 1
        # Second call applies nothing and does not error or churn history.
        assert run_migrations(path) == 1
        conn = sqlite3.connect(path)
        count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        conn.close()
        assert count == len(MIGRATIONS)
    finally:
        os.unlink(path)


def test_failure_halts_and_rolls_back_without_advancing():
    """A migration that raises rolls back, halts the run, and leaves
    user_version at the last good version — later migrations don't apply."""
    path = _fresh_db()
    try:
        def good(conn):
            conn.execute("CREATE INDEX IF NOT EXISTS ix_probe_ok ON scheduled_tasks(owner)")

        def boom(conn):
            conn.execute("CREATE INDEX ix_probe_boom ON scheduled_tasks(status)")
            raise RuntimeError("simulated failure mid-migration")

        def never(conn):
            conn.execute("CREATE INDEX ix_probe_never ON scheduled_tasks(name)")

        custom = [Migration(1, "good", good),
                  Migration(2, "boom", boom),
                  Migration(3, "never", never)]

        result = run_migrations(path, custom)

        assert result == 1
        assert _user_version(path) == 1
        idx = _indexes(path)
        assert "ix_probe_ok" in idx          # v1 committed
        assert "ix_probe_boom" not in idx    # v2 rolled back
        assert "ix_probe_never" not in idx   # v3 never reached
    finally:
        os.unlink(path)


def test_bad_registry_is_rejected():
    with pytest.raises(ValueError):
        validate_registry([Migration(1, "a", lambda c: None),
                            Migration(3, "gap", lambda c: None)])
    with pytest.raises(ValueError):
        validate_registry([Migration(2, "starts-late", lambda c: None)])


def test_url_with_real_sqlite_path_upgrades():
    """Happy path for run_migrations_for_url: a real sqlite:/// URL parses to a
    path and drives the same upgrade as run_migrations(path)."""
    path = _fresh_db()
    try:
        result = run_migrations_for_url(f"sqlite:///{path}")
        assert result == head_version() == 1
        assert _user_version(path) == 1
        assert "ix_scheduled_tasks_owner_type" in _indexes(path)
    finally:
        os.unlink(path)


def test_non_sqlite_url_is_noop():
    assert run_migrations_for_url("postgresql://x/y") == 0
    assert run_migrations_for_url("") == 0


def test_missing_file_is_noop():
    assert run_migrations("/nonexistent/path/to/app.db") == 0
