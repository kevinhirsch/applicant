"""Migration test for the agent-memory durable tables (0015_agent_memory, #286).

Hermetic (temp-file SQLite, no Postgres/Docker): asserts ``alembic upgrade head``
creates the ``memory_entries`` / ``skills`` / ``recall_entries`` tables + their
indexes, that rows written into them survive, and that ``downgrade`` cleanly drops
them. Uses the same ``-x db_url`` guard as ``tests/migrations/data_integrity.py`` so
neither ``DATABASE_URL`` nor settings can redirect to a real server.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.unit

_PROJECT = Path(__file__).resolve().parents[2]
_NEW_TABLES = ("memory_entries", "skills", "recall_entries")
_PRIOR_REVISION = "0014_discovery_boards"
_REVISION = "0015_agent_memory"


def _cfg(db_url: str) -> Config:
    cmd_opts = argparse.Namespace(x=[f"db_url={db_url}"])
    cfg = Config(str(_PROJECT / "alembic.ini"), cmd_opts=cmd_opts)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option(
        "script_location", str(_PROJECT / "src/applicant/adapters/storage/alembic")
    )
    return cfg


def test_upgrade_creates_tables_and_indexes_then_downgrade_drops_them():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    try:
        db_url = f"sqlite:///{db_path}"
        cfg = _cfg(db_url)
        engine = create_engine(db_url)

        # 1. Stand up at the PRIOR revision — the new tables must NOT exist yet.
        command.upgrade(cfg, _PRIOR_REVISION)
        tables_before = set(inspect(engine).get_table_names())
        assert not (set(_NEW_TABLES) & tables_before)

        # 2. Upgrade to head → the three tables + indexes exist.
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        tables_after = set(insp.get_table_names())
        for tbl in _NEW_TABLES:
            assert tbl in tables_after, f"{tbl} missing after upgrade"

        mem_indexes = {ix["name"] for ix in insp.get_indexes("memory_entries")}
        assert "ix_memory_entries_scope_campaign_kind" in mem_indexes
        skill_indexes = {ix["name"] for ix in insp.get_indexes("skills")}
        assert "ix_skills_scope_campaign" in skill_indexes

        # 3. Rows written into the new tables persist across a query.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO memory_entries (campaign_id, kind, scope, text, "
                    "created_at, updated_at) VALUES (NULL, 'user', 'global', "
                    "'remember me', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
                )
            )
            got = conn.execute(text("SELECT text FROM memory_entries")).scalar()
            assert got == "remember me"

        # 4. Downgrade one step → the three tables are cleanly dropped again.
        command.downgrade(cfg, _PRIOR_REVISION)
        tables_down = set(inspect(engine).get_table_names())
        assert not (set(_NEW_TABLES) & tables_down), "downgrade must drop the tables"

        # 5. Re-upgrade is clean (idempotent round-trip).
        command.upgrade(cfg, "head")
        assert set(_NEW_TABLES) <= set(inspect(engine).get_table_names())

        engine.dispose()
    finally:
        os.unlink(db_path)
