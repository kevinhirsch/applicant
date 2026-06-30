"""Agent-memory backend factory (FR-MIND-1/2/3 + §10 store placement).

Selects the ``MemoryStore`` / ``SkillStore`` / ``RecallIndex`` trio by the
``MIND_BACKEND`` setting:

* ``in_memory`` (DEFAULT) — the hermetic in-process adapters; import-safe, no deps.
* ``bridge`` — the workspace-bridge skeleton adapters (recommended placement, §10);
  they degrade to empty behavior when the engine->workspace channel is OFF.
* ``mem0`` — evaluation adapter for mem0 (https://github.com/mem0ai/mem0, #307).
* ``letta`` — evaluation adapter for Letta (https://letta.com, #307).

The default keeps boot + the test lane hermetic. The factory returns a small
``AgentMemory`` bundle the container injects into the curation service / loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from applicant.adapters.memory.bridge import (
    WorkspaceBridgeMemoryStore,
    WorkspaceBridgeRecallIndex,
    WorkspaceBridgeSkillStore,
)
from applicant.adapters.memory.evaluation import (
    LettaMemoryStore,
    LettaRecallIndex,
    LettaSkillStore,
    Mem0MemoryStore,
    Mem0RecallIndex,
    Mem0SkillStore,
)
from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.ports.driven.memory_store import MemoryStore
from applicant.ports.driven.recall_index import RecallIndex
from applicant.ports.driven.skill_store import SkillStore

#: Backend identifiers for ``MIND_BACKEND`` (FR-MIND, §10, #307).
MIND_BACKEND_IN_MEMORY = "in_memory"
MIND_BACKEND_BRIDGE = "bridge"
MIND_BACKEND_MEM0 = "mem0"
MIND_BACKEND_LETTA = "letta"
MIND_BACKEND_TEMPORAL = "temporal"
MIND_BACKENDS = (
    MIND_BACKEND_IN_MEMORY,
    MIND_BACKEND_BRIDGE,
    MIND_BACKEND_MEM0,
    MIND_BACKEND_LETTA,
    MIND_BACKEND_TEMPORAL,
)


@dataclass(frozen=True)
class AgentMemory:
    """The agent-memory adapter trio (FR-MIND-1/2/3) + the selected backend name."""

    memory: MemoryStore
    skills: SkillStore
    recall: RecallIndex
    backend: str


def build_agent_memory(settings: Any, workspace_port: Any = None) -> AgentMemory:
    """Build the agent-memory trio for the configured ``MIND_BACKEND``.

    ``settings`` supplies ``mind_backend`` and the memory bounds; ``workspace_port``
    is the existing ``WorkspacePort`` (only its ``available()`` gate is used by the
    bridge adapters). Falls back to ``in_memory`` for any unknown backend so boot is
    always safe.
    """
    backend = getattr(settings, "mind_backend", MIND_BACKEND_IN_MEMORY)

    if backend == MIND_BACKEND_BRIDGE:
        return AgentMemory(
            memory=WorkspaceBridgeMemoryStore(workspace_port),
            skills=WorkspaceBridgeSkillStore(workspace_port),
            recall=WorkspaceBridgeRecallIndex(workspace_port),
            backend=MIND_BACKEND_BRIDGE,
        )

    if backend == MIND_BACKEND_MEM0:
        return AgentMemory(
            memory=Mem0MemoryStore(),
            skills=Mem0SkillStore(),
            recall=Mem0RecallIndex(),
            backend=MIND_BACKEND_MEM0,
        )

    if backend == MIND_BACKEND_LETTA:
        return AgentMemory(
            memory=LettaMemoryStore(),
            skills=LettaSkillStore(),
            recall=LettaRecallIndex(),
            backend=MIND_BACKEND_LETTA,
        )

    if backend == MIND_BACKEND_TEMPORAL:
        from applicant.adapters.memory.temporal_backend import TemporalMemoryStore

        return AgentMemory(
            memory=TemporalMemoryStore(),
            skills=InMemorySkillStore(),
            recall=InMemoryRecallIndex(),
            backend=MIND_BACKEND_TEMPORAL,
        )

    # Default / unknown -> hermetic in-memory.
    return AgentMemory(
        memory=InMemoryMemoryStore(
            memory_max_chars=getattr(settings, "memory_max_chars", 8000),
            user_max_chars=getattr(settings, "user_max_chars", 4000),
        ),
        skills=InMemorySkillStore(),
        recall=InMemoryRecallIndex(),
        backend=MIND_BACKEND_IN_MEMORY,
    )
