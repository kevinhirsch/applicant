"""Engine + sessionmaker factory (built from settings)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

#: Perf lens 03 #31: SQLAlchemy's defaults (``pool_size=5`` + ``max_overflow=10`` =
#: 15 checkouts) are smaller than Starlette's request threadpool (AnyIO's default
#: worker-thread limiter caps at 40), and the same pool is also shared by the
#: scheduler tick session, the container-level boot session, and audit-log
#: emissions. Under load, checkouts queue behind the 15-connection ceiling before
#: any query runs. Size the pool to the threadpool instead of leaving it at the
#: library default. Postgres-only: SQLite's default pool classes (used by every
#: hermetic test) don't accept ``pool_size``/``max_overflow``/``pool_recycle``.
_PG_POOL_SIZE = 20
_PG_MAX_OVERFLOW = 20
_PG_POOL_RECYCLE_S = 1800


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    SQLite (used in fast tests) needs ``check_same_thread=False``; Postgres
    (production) gets an explicitly sized pool (see ``_PG_POOL_SIZE`` above)
    instead of SQLAlchemy's smaller-than-the-threadpool default.

    ``pool_pre_ping=True`` so a dead pooled connection (e.g. after a transient
    Postgres blip / server restart) is detected on checkout and transparently
    replaced, rather than handed back broken (K2). This is the upstream half of
    the boot-Session recovery: the app-config store rolls back + retries a poisoned
    transaction, and pre-ping ensures that retry runs over a live connection.
    """
    connect_args: dict = {}
    pool_kwargs: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        pool_kwargs["pool_size"] = _PG_POOL_SIZE
        pool_kwargs["max_overflow"] = _PG_MAX_OVERFLOW
        pool_kwargs["pool_recycle"] = _PG_POOL_RECYCLE_S
    return create_engine(
        database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
        **pool_kwargs,
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured sessionmaker bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
