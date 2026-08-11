"""Contract: the in-memory adapters satisfy the FR-MIND driven Protocols.

Asserts the in-memory MemoryStore / SkillStore / RecallIndex adapters structurally
satisfy their ``@runtime_checkable`` ports, and that the factory wires the default
``in_memory`` backend (hermetic, import-safe).
"""

from __future__ import annotations

import pytest

from applicant.adapters.memory.factory import (
    MIND_BACKEND_BRIDGE,
    MIND_BACKEND_IN_MEMORY,
    MIND_BACKEND_SQL,
    build_agent_memory,
)
from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.adapters.memory.sql_backend import (
    SqlMemoryStore,
    SqlRecallIndex,
    SqlSkillStore,
)
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.ports.driven.memory_store import MemoryEntry, MemoryStore
from applicant.ports.driven.recall_index import RecallIndex
from applicant.ports.driven.skill_store import SkillStore


class _FakeSettings:
    def __init__(self, backend):
        self.mind_backend = backend
        self.memory_max_chars = 8000
        self.user_max_chars = 4000


class _FakeWorkspaceOff:
    def available(self) -> bool:
        return False


@pytest.mark.contract
class TestAgentMemoryContract:
    def test_in_memory_adapters_satisfy_ports(self):
        assert isinstance(InMemoryMemoryStore(), MemoryStore)
        assert isinstance(InMemorySkillStore(), SkillStore)
        assert isinstance(InMemoryRecallIndex(), RecallIndex)

    def test_factory_default_is_in_memory_and_satisfies_ports(self):
        bundle = build_agent_memory(_FakeSettings(MIND_BACKEND_IN_MEMORY))
        assert bundle.backend == MIND_BACKEND_IN_MEMORY
        assert isinstance(bundle.memory, MemoryStore)
        assert isinstance(bundle.skills, SkillStore)
        assert isinstance(bundle.recall, RecallIndex)

    def test_factory_bridge_backend_satisfies_ports_and_degrades_when_off(self):
        bundle = build_agent_memory(
            _FakeSettings(MIND_BACKEND_BRIDGE), _FakeWorkspaceOff()
        )
        assert bundle.backend == MIND_BACKEND_BRIDGE
        # Bridge adapters still satisfy the Protocols...
        assert isinstance(bundle.memory, MemoryStore)
        assert isinstance(bundle.skills, SkillStore)
        assert isinstance(bundle.recall, RecallIndex)
        # ...and degrade to empty behavior when the channel is OFF.
        assert bundle.memory.snapshot().all() == ()
        assert bundle.skills.list_skills() == ()
        assert bundle.recall.search("anything") == ()

    def test_unknown_backend_falls_back_to_in_memory(self):
        bundle = build_agent_memory(_FakeSettings("nonsense"))
        assert bundle.backend == MIND_BACKEND_IN_MEMORY


@pytest.fixture
def sql_session_factory(tmp_path):
    """Engine + session_factory over a temp-file SQLite DB with tables created."""
    engine = make_engine(f"sqlite:///{tmp_path / 'contract_memory.db'}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.mark.contract
class TestSqlAgentMemoryContract:
    """The DURABLE sql trio satisfies the same FR-MIND driven Protocols (#286)."""

    def test_sql_adapters_satisfy_ports(self, sql_session_factory):
        assert isinstance(SqlMemoryStore(sql_session_factory), MemoryStore)
        assert isinstance(SqlSkillStore(sql_session_factory), SkillStore)
        assert isinstance(SqlRecallIndex(sql_session_factory), RecallIndex)

    def test_factory_sql_backend_builds_durable_trio(self, sql_session_factory):
        bundle = build_agent_memory(
            _FakeSettings(MIND_BACKEND_SQL), session_factory=sql_session_factory
        )
        assert bundle.backend == MIND_BACKEND_SQL
        assert isinstance(bundle.memory, SqlMemoryStore)
        assert isinstance(bundle.skills, SqlSkillStore)
        assert isinstance(bundle.recall, SqlRecallIndex)
        # It actually persists (write is visible through the same factory).
        bundle.memory.add(MemoryEntry(text="a durable curated lesson worth keeping"))
        assert bundle.memory.snapshot().all()

    def test_factory_sql_without_session_factory_falls_back_to_in_memory(self):
        # Backward-compatible + boot-safe: sql requested but no DB wired ⇒ in_memory.
        bundle = build_agent_memory(_FakeSettings(MIND_BACKEND_SQL))
        assert bundle.backend == MIND_BACKEND_IN_MEMORY
        assert isinstance(bundle.memory, InMemoryMemoryStore)

    def test_default_signature_still_works_without_session_factory(self):
        # The extended signature stays backward-compatible for existing callers.
        bundle = build_agent_memory(_FakeSettings(MIND_BACKEND_IN_MEMORY))
        assert bundle.backend == MIND_BACKEND_IN_MEMORY
