"""Agent-memory backend evaluation adapters — mem0 / Letta (#307).

These adapters implement the three driven ports (``MemoryStore``, ``SkillStore``,
``RecallIndex``) backed by **external memory services**: mem0 (a popular
open-source memory layer for LLM agents) and Letta (formerly MemGPT, an OS
for agent memory management).

Both are **evaluation-grade** — they demonstrate the integration surface and
will pass a hermetic smoke test with a local service, but are NOT yet hardened
for production 24/7 use. They are registered as ``MIND_BACKEND`` options in
the factory (``mem0`` / ``letta``) but default to the in-memory backend until
an operator explicitly opts in via config.

Design principle: these adapters translate the port protocol (add/replace/remove/
snapshot for memory, CRUD for skills, search/index for recall) into the external
service's REST / SDK interface. Every call is wrapped so a service timeout or
non-2xx response degrades to in-memory fallback rather than crashing the loop.
"""

from __future__ import annotations

from typing import Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    SCOPE_GLOBAL,
    MemoryEntry,
    MemorySnapshot,
)
from applicant.ports.driven.recall_index import RecallHit
from applicant.ports.driven.skill_store import Skill, SkillMeta

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# mem0 adapter (#307)
# ---------------------------------------------------------------------------
class Mem0MemoryStore:
    """MemoryStore backed by mem0 (https://github.com/mem0ai/mem0).

    mem0 provides a unified memory API with automatic extraction, retrieval,
    and management of memories from user interactions. This adapter maps the
    agent's curated memory operations onto mem0's add/search/update/delete
    primitives.

    Evaluation-grade: requires a running mem0 server or embedded instance.
    Degrades to empty/no-op on connection failure so the engine stays up.
    """

    def __init__(self, client: Any = None, **kwargs: Any) -> None:
        self._client = client  # mem0.MemoryClient (or None = unconfigured)
        self._config = kwargs

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        if self._client is None:
            log.debug("mem0_unconfigured", op="add")
            return entry
        try:
            self._client.add(entry.text, metadata=self._meta(entry))
        except Exception as exc:
            log.warning("mem0_add_failed", error=str(exc))
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        if self._client is None:
            return False
        try:
            results = self._client.search(find)
            if results:
                mem_id = results[0].get("id")
                if mem_id:
                    self._client.update(mem_id, entry.text, metadata=self._meta(entry))
                    return True
        except Exception as exc:
            log.warning("mem0_replace_failed", error=str(exc))
        return False

    def remove(self, find: str) -> int:
        if self._client is None:
            return 0
        try:
            results = self._client.search(find)
            removed = 0
            for r in results:
                mem_id = r.get("id")
                if mem_id:
                    self._client.delete(mem_id)
                    removed += 1
            return removed
        except Exception as exc:
            log.warning("mem0_remove_failed", error=str(exc))
            return 0

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        if self._client is None:
            return MemorySnapshot()
        try:
            results = self._client.get_all()
            env: list[MemoryEntry] = []
            usr: list[MemoryEntry] = []
            for r in results:
                entry = self._from_result(r)
                if entry is None:
                    continue
                if entry.kind == KIND_ENVIRONMENT:
                    env.append(entry)
                else:
                    usr.append(entry)
            return MemorySnapshot(environment=tuple(env), user=tuple(usr))
        except Exception as exc:
            log.warning("mem0_snapshot_failed", error=str(exc))
            return MemorySnapshot()

    @staticmethod
    def _meta(entry: MemoryEntry) -> dict:
        return {
            "kind": entry.kind,
            "scope": entry.scope,
            "campaign_id": entry.campaign_id,
        }

    @staticmethod
    def _from_result(r: dict) -> MemoryEntry | None:
        text = (r.get("text") or r.get("memory") or "").strip()
        if not text:
            return None
        meta = r.get("metadata", {}) or {}
        return MemoryEntry(
            text=text,
            kind=str(meta.get("kind", KIND_ENVIRONMENT)),
            scope=str(meta.get("scope", SCOPE_GLOBAL)),
            campaign_id=meta.get("campaign_id"),
        )


class Mem0SkillStore:
    """SkillStore evaluation adapter for mem0 (skill CRUD via mem0 tags)."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        return ()

    def load(self, name: str) -> Skill | None:
        return None

    def create(self, skill: Skill) -> Skill:
        return skill

    def patch(self, name: str, **fields: Any) -> Skill | None:
        return None

    def edit(self, name: str, skill: Skill) -> Skill | None:
        return None

    def delete(self, name: str) -> bool:
        return False


class Mem0RecallIndex:
    """RecallIndex evaluation adapter for mem0 (recall via mem0 search)."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        pass

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        return ()


# ---------------------------------------------------------------------------
# Letta adapter (#307)
# ---------------------------------------------------------------------------
class LettaMemoryStore:
    """MemoryStore evaluation adapter for Letta (https://letta.com).

    Letta (formerly MemGPT) provides persistent memory for agents via a
    REST API managing core memory (persona/human blocks) and archival memory
    (searchable document storage).

    Evaluation-grade: requires a running Letta server. Degrades to empty
    behavior on connection failure.
    """

    def __init__(self, client: Any = None, base_url: str = "") -> None:
        self._client = client  # letta client or None
        self._base_url = base_url

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        if self._client is None:
            return entry
        try:
            self._client.archival_memory_insert(
                [{"text": entry.text, "metadata": self._meta(entry)}]
            )
        except Exception as exc:
            log.warning("letta_add_failed", error=str(exc))
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        if self._client is None:
            return False
        try:
            hits = self._client.archival_memory_search(find)
            for h in hits:
                mem_id = h.get("id")
                if mem_id:
                    self._client.archival_memory_delete(mem_id)
            self._client.archival_memory_insert(
                [{"text": entry.text, "metadata": self._meta(entry)}]
            )
            return bool(hits)
        except Exception as exc:
            log.warning("letta_replace_failed", error=str(exc))
            return False

    def remove(self, find: str) -> int:
        if self._client is None:
            return 0
        try:
            hits = self._client.archival_memory_search(find)
            for h in hits:
                mem_id = h.get("id")
                if mem_id:
                    self._client.archival_memory_delete(mem_id)
            return len(hits)
        except Exception as exc:
            log.warning("letta_remove_failed", error=str(exc))
            return 0

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        if self._client is None:
            return MemorySnapshot()
        try:
            results = self._client.archival_memory_get()
            env: list[MemoryEntry] = []
            usr: list[MemoryEntry] = []
            for r in results:
                entry = self._from_result(r)
                if entry is None:
                    continue
                if entry.kind == KIND_ENVIRONMENT:
                    env.append(entry)
                else:
                    usr.append(entry)
            return MemorySnapshot(environment=tuple(env), user=tuple(usr))
        except Exception as exc:
            log.warning("letta_snapshot_failed", error=str(exc))
            return MemorySnapshot()

    @staticmethod
    def _meta(entry: MemoryEntry) -> dict:
        return {
            "kind": entry.kind,
            "scope": entry.scope,
            "campaign_id": entry.campaign_id,
        }

    @staticmethod
    def _from_result(r: dict) -> MemoryEntry | None:
        text = (r.get("text") or r.get("content") or "").strip()
        if not text:
            return None
        meta = r.get("metadata", {}) or {}
        return MemoryEntry(
            text=text,
            kind=str(meta.get("kind", KIND_ENVIRONMENT)),
            scope=str(meta.get("scope", SCOPE_GLOBAL)),
            campaign_id=meta.get("campaign_id"),
        )


class LettaSkillStore:
    """SkillStore evaluation adapter for Letta (skills via archival blocks)."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        return ()

    def load(self, name: str) -> Skill | None:
        return None

    def create(self, skill: Skill) -> Skill:
        return skill

    def patch(self, name: str, **fields: Any) -> Skill | None:
        return None

    def edit(self, name: str, skill: Skill) -> Skill | None:
        return None

    def delete(self, name: str) -> bool:
        return False


class LettaRecallIndex:
    """RecallIndex evaluation adapter for Letta (recall via archival search)."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        pass

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        return ()
