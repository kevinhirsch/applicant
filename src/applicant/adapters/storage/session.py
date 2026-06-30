"""Engine + sessionmaker factory (built from settings)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    SQLite (used in fast tests) needs ``check_same_thread=False``; Postgres
    (production) uses default pooling.

    ``pool_pre_ping=True`` so a dead pooled connection (e.g. after a transient
    Postgres blip / server restart) is detected on checkout and transparently
    replaced, rather than handed back broken (K2). This is the upstream half of
    the boot-Session recovery: the app-config store rolls back + retries a poisoned
    transaction, and pre-ping ensures that retry runs over a live connection.
    """
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured sessionmaker bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
