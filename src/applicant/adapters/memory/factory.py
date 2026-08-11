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

#: Backend identifiers for ``MIND_BACKEND`` (FR-MIND, §10, #307, #286).
MIND_BACKEND_IN_MEMORY = "in_memory"
MIND_BACKEND_BRIDGE = "bridge"
MIND_BACKEND_MEM0 = "mem0"
MIND_BACKEND_LETTA = "letta"
MIND_BACKEND_TEMPORAL = "temporal"
#: The DURABLE, production backend (#286): the curated trio persisted to the shared
#: SQLAlchemy storage stack so memory survives an engine restart. Reads stay local +
#: single-query (no network) — unlike the disabled ``bridge`` backend.
MIND_BACKEND_SQL = "sql"
MIND_BACKENDS = (
    MIND_BACKEND_IN_MEMORY,
    MIND_BACKEND_BRIDGE,
    MIND_BACKEND_MEM0,
    MIND_BACKEND_LETTA,
    MIND_BACKEND_TEMPORAL,
    MIND_BACKEND_SQL,
)


@dataclass(frozen=True)
class AgentMemory:
    """The agent-memory adapter trio (FR-MIND-1/2/3) + the selected backend name."""

    memory: MemoryStore
    skills: SkillStore
    recall: RecallIndex
    backend: str


def build_agent_memory(
    settings: Any,
    workspace_port: Any = None,
    *,
    session_factory: Any = None,
) -> AgentMemory:
    """Build the agent-memory trio for the configured ``MIND_BACKEND``.

    ``settings`` supplies ``mind_backend`` and the memory bounds; ``workspace_port``
    is the existing ``WorkspacePort`` (only its ``available()`` gate is used by the
    bridge adapters); ``session_factory`` is the shared SQLAlchemy sessionmaker the
    container already builds — threaded in so the DURABLE ``sql`` backend can persist
    (each op opens its own short-lived session). Falls back to ``in_memory`` for any
    unknown backend, and for ``sql`` when no ``session_factory`` is wired (no DB
    reachable), so boot + the hermetic test lane are always safe.

    The keyword-only ``session_factory`` keeps the signature backward-compatible:
    existing ``build_agent_memory(settings, workspace)`` callers are unchanged.
    """
    backend = getattr(settings, "mind_backend", MIND_BACKEND_IN_MEMORY)

    if backend == MIND_BACKEND_SQL and session_factory is not None:
        from applicant.adapters.memory.sql_backend import (
            SqlMemoryStore,
            SqlRecallIndex,
            SqlSkillStore,
        )

        return AgentMemory(
            memory=SqlMemoryStore(
                session_factory,
                memory_max_chars=getattr(settings, "memory_max_chars", 8000),
                user_max_chars=getattr(settings, "user_max_chars", 4000),
            ),
            skills=SqlSkillStore(session_factory),
            recall=SqlRecallIndex(session_factory),
            backend=MIND_BACKEND_SQL,
        )

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
