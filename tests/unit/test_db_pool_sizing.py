"""DB connection pool sizing (perf lens 03 #31).

``make_engine`` used to leave Postgres on SQLAlchemy's library defaults
(``pool_size=5`` + ``max_overflow=10`` = 15 checkouts), smaller than the
Starlette request threadpool (AnyIO's default worker-thread limiter caps at
40) that also shares this pool with the scheduler tick session, the
container-level boot session, and audit-log emissions. These tests pin the
new, explicitly sized Postgres pool and prove the SQLite path (used by every
hermetic test) is completely unaffected — SQLite's default pool classes don't
accept ``pool_size``/``max_overflow``/``pool_recycle`` at all, so passing them
unconditionally would break every test in the suite.
"""

from __future__ import annotations

import tempfile

from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory


def test_postgres_url_gets_a_pool_sized_to_the_request_threadpool():
    # No real Postgres reachable/required: engine construction is lazy (no
    # connection is attempted until first checkout), so an unreachable host is
    # fine for inspecting the configured pool.
    engine = make_engine("postgresql+psycopg://u:p@127.0.0.1:1/db")
    try:
        assert engine.pool.size() == 20
        assert engine.pool._max_overflow == 20
        assert engine.pool._recycle == 1800
    finally:
        engine.dispose()


def test_sqlite_url_is_unaffected_by_the_postgres_pool_sizing():
    """The hermetic test suite's SQLite engines must keep working exactly as
    before: no pool_size/max_overflow/pool_recycle kwargs (which SQLite's
    default pool classes reject), same connect_args, same usability."""
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    try:
        # No TypeError constructing the engine (would raise if pool_size/
        # max_overflow/pool_recycle were passed unconditionally), and a real
        # round-trip below proves it is fully usable, not just constructible.
        Base.metadata.create_all(engine)
        session = make_session_factory(engine)()
        # A real round-trip proves the engine is still fully usable (not just
        # constructible) after the change.
        from applicant.adapters.storage.app_config_store import SqlAlchemyAppConfigStore

        store = SqlAlchemyAppConfigStore(session)
        store.set("k", {"a": 1})
        assert store.get("k") == {"a": 1}
        session.close()
    finally:
        engine.dispose()


def test_sqlite_memory_url_still_constructs_without_pool_kwargs():
    engine = make_engine("sqlite:///:memory:")
    try:
        # Would raise TypeError if pool_size/max_overflow were passed for a
        # poolclass that doesn't accept them (the bug this test would catch).
        assert engine is not None
    finally:
        engine.dispose()
