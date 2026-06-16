"""AppConfigStore: in-memory + SQLAlchemy-backed key/value persistence."""

from __future__ import annotations

import tempfile

import pytest

from applicant.adapters.storage.app_config_store import (
    InMemoryAppConfigStore,
    SqlAlchemyAppConfigStore,
)


def test_in_memory_roundtrip():
    store = InMemoryAppConfigStore()
    assert store.get("k") is None
    store.set("k", {"a": 1})
    assert store.get("k") == {"a": 1}
    store.set("k", {"a": 2})
    assert store.get("k") == {"a": 2}


def test_in_memory_isolated_copies():
    store = InMemoryAppConfigStore()
    v = {"a": 1}
    store.set("k", v)
    v["a"] = 99
    assert store.get("k") == {"a": 1}  # stored a copy, not the reference


@pytest.fixture
def sa_store():
    from applicant.adapters.storage.models import Base
    from applicant.adapters.storage.session import make_engine, make_session_factory

    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    yield SqlAlchemyAppConfigStore(session)
    session.close()
    engine.dispose()


def test_sqlalchemy_roundtrip(sa_store):
    assert sa_store.get("llm.tier_ladder") is None
    sa_store.set("llm.tier_ladder", {"tiers": [{"model": "m"}]})
    assert sa_store.get("llm.tier_ladder") == {"tiers": [{"model": "m"}]}
    sa_store.set("llm.tier_ladder", {"tiers": []})
    assert sa_store.get("llm.tier_ladder") == {"tiers": []}
