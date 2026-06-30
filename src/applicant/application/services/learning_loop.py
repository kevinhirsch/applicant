"""Two-way learning loop — engine reads from and writes to curated memory.

Issue #294: The agent-memory bridge (MIND_BACKEND=bridge) reaches the front-door
workspace memory/skills substrate. This service implements the closed-loop learning
cycle:
  1. READ: before each tick, retrieve relevant memory snapshot + skills
  2. ACT: the engine runs its normal pipeline
  3. WRITE: after each tick, write learnings/outcomes back to memory
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    SCOPE_CAMPAIGN,
    MemoryEntry,
)

log = get_logger(__name__)


class LearningLoopService:
    """Closed-loop learning: read memory before acting, write lessons after.

    Wraps the ``AgentMemory`` trio (``memory``, ``skills``, ``recall``) with
    per-tick read/write orchestration. Gracefully degrades when the backend is
    offline — all operations are best-effort and never raise.
    """

    def __init__(self, agent_memory: Any) -> None:
        self._memory = agent_memory
        self._last_write_ts: datetime | None = None

    def read_context(self, campaign_id: str) -> dict[str, Any]:
        out: dict[str, Any] = {"snapshot": None, "skills": [], "recall": []}
        try:
            out["snapshot"] = self._memory.memory.snapshot(campaign_id=campaign_id)
        except Exception as exc:
            log.debug("learning_read_memory_failed", campaign=campaign_id, error=str(exc))
        try:
            skills = self._memory.skills.list_skills(campaign_id=campaign_id)
            out["skills"] = list(skills)
        except Exception as exc:
            log.debug("learning_read_skills_failed", campaign=campaign_id, error=str(exc))
        try:
            recall = self._memory.recall.list(campaign_id=campaign_id)
            out["recall"] = list(recall)
        except Exception as exc:
            log.debug("learning_read_recall_failed", campaign=campaign_id, error=str(exc))
        return out

    def write_lesson(
        self,
        campaign_id: str,
        *,
        text: str,
        kind: str = KIND_ENVIRONMENT,
        scope: str = SCOPE_CAMPAIGN,
    ) -> bool:
        try:
            entry = MemoryEntry(text=text, kind=kind, scope=scope, campaign_id=campaign_id)
            self._memory.memory.add(entry)
            self._last_write_ts = datetime.now(UTC)
            log.info("learning_lesson_written", campaign=campaign_id, kind=kind)
            return True
        except Exception as exc:
            log.debug("learning_write_failed", campaign=campaign_id, error=str(exc))
            return False

    def health(self) -> dict[str, Any]:
        memory_ok = hasattr(self._memory, "memory") and self._memory.memory is not None
        skills_ok = hasattr(self._memory, "skills") and self._memory.skills is not None
        recall_ok = hasattr(self._memory, "recall") and self._memory.recall is not None
        return {
            "memory_available": memory_ok,
            "skills_available": skills_ok,
            "recall_available": recall_ok,
            "backend": getattr(self._memory, "backend", "unknown"),
            "last_write": self._last_write_ts.isoformat() if self._last_write_ts else None,
        }
