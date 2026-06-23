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
    build_agent_memory,
)
from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.ports.driven.memory_store import MemoryStore
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
