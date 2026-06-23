"""Agent-memory adapters (FR-MIND-1/2/3).

Implements the ``MemoryStore`` / ``SkillStore`` / ``RecallIndex`` driven ports.

* ``in_memory`` — the DEFAULT hermetic adapters (no external deps; import-safe).
* ``bridge`` — skeleton adapters that reach the front-door substrate under
  ``workspace/services/memory/`` over the engine->workspace callback channel, per
  ``docs/spec/agent-intelligence.md`` §10 (recommended placement).
* ``build_agent_memory`` — factory selecting the backend by ``MIND_BACKEND``.
"""

from __future__ import annotations

from applicant.adapters.memory.factory import AgentMemory, build_agent_memory

__all__ = ["AgentMemory", "build_agent_memory"]
