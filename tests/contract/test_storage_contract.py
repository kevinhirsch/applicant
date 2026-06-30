"""Storage contract run against both the in-memory and SQLite SQLAlchemy adapters."""

from __future__ import annotations

import pytest

from applicant.adapters.storage.in_memory import InMemoryStorage
from tests.contract.base import StoragePortContract


@pytest.mark.contract
class TestInMemoryStorageContract(StoragePortContract):
    @pytest.fixture
    def adapter(self):
        return InMemoryStorage()


@pytest.mark.contract
class TestSqlAlchemyStorageContract(StoragePortContract):
    @pytest.fixture
    def adapter(self):
        from applicant.adapters.storage.models import Base
        from applicant.adapters.storage.repositories import SqlAlchemyStorage
        from applicant.adapters.storage.session import make_engine, make_session_factory

        # Use an in-memory SQLite DB instead of a temp file: schema creation is
        # ~8 ms (pure memory) vs ~300 ms (file I/O), with identical behaviour —
        # the fixture has always been ephemeral and per-test.
        engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = make_session_factory(engine)()
        yield SqlAlchemyStorage(session)
        session.close()
        engine.dispose()
