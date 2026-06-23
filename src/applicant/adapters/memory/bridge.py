"""Workspace-bridge agent-memory adapters (FR-MIND-1/2/3) — skeleton.

Per ``docs/spec/agent-intelligence.md`` §10 the **recommended** store placement is:
keep the Hermes-derived memory/skills substrate where it already lives (the
front-door ``workspace/services/memory/`` — it already has the extractors, the
ChromaDB vector store, and the routes) and have the **engine** reach it as a thin
client over the existing engine->workspace callback channel
(``APPLICANT_INTERNAL_TOKEN`` / ``WORKSPACE_URL``).

These adapters are that thin client. They DEGRADE to empty/in-memory behavior when
the channel is OFF (``WorkspacePort.available()`` is False) so the engine still
boots and the hermetic lane stays offline. The actual HTTP calls are kept lazy and
guarded; the concrete request bodies land when the workspace exposes the bridge
endpoints below.

**Bridge endpoints needed on the workspace side** (to wire later — report these):

* ``GET  /api/applicant/internal/memory/snapshot?scope=&campaign_id=``
    -> ``{"environment": [{text,kind,scope,campaign_id}], "user": [...], "truncated": bool}``
* ``POST /api/applicant/internal/memory/add``      body: ``{text,kind,scope,campaign_id}``
* ``POST /api/applicant/internal/memory/replace``  body: ``{find, entry:{...}}``
* ``POST /api/applicant/internal/memory/remove``   body: ``{find}`` -> ``{removed: int}``
* ``GET  /api/applicant/internal/skills?scope=&campaign_id=``  (L0 metadata list)
* ``GET  /api/applicant/internal/skills/{name}``               (L1 full body)
* ``POST /api/applicant/internal/skills``          (create) body: SKILL.md fields
* ``PATCH/api/applicant/internal/skills/{name}``   (patch)  body: changed fields
* ``PUT  /api/applicant/internal/skills/{name}``   (edit)   body: full SKILL.md fields
* ``DELETE /api/applicant/internal/skills/{name}``
* ``GET  /api/applicant/internal/recall?q=&limit=&scope=&campaign_id=``
    -> ``{"hits": [{run_id,text,score,campaign_id}]}``

The workspace already owns the ``memory_routes`` / ``skills_routes`` /
``applicant_memory_routes`` logic; these internal endpoints are thin token-gated
wrappers over that substrate (mirroring ``applicant_internal_routes.py``).

A thin client surface (``_BridgeClient``) is defined here rather than adding methods
to the existing ``WorkspacePort`` Protocol, so the existing workspace adapter keeps
satisfying its Protocol unchanged. We only depend on ``WorkspacePort.available()``.
"""

from __future__ import annotations

from typing import Any, Protocol

from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import MemoryEntry, MemorySnapshot
from applicant.ports.driven.recall_index import RecallHit
from applicant.ports.driven.skill_store import Skill, SkillMeta

log = get_logger(__name__)


class _WorkspaceGate(Protocol):
    """The only thing the bridge needs from the workspace port: a config gate."""

    def available(self) -> bool: ...


class _Bridgeable:
    """Shared availability gate for the bridge adapters."""

    def __init__(self, workspace: _WorkspaceGate | None) -> None:
        self._workspace = workspace

    def _available(self) -> bool:
        ws = self._workspace
        return bool(ws is not None and ws.available())


class WorkspaceBridgeMemoryStore(_Bridgeable):
    """``MemoryStore`` over the workspace bridge (FR-MIND-1).

    Until the bridge endpoints above are wired, every method degrades to an empty/
    no-op result when the channel is OFF, so the engine boots and stays hermetic.
    """

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        if not self._available():
            log.debug("memory_bridge_offline", op="add")
            return entry
        # TODO(bridge): POST /api/applicant/internal/memory/add
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        if not self._available():
            return False
        # TODO(bridge): POST /api/applicant/internal/memory/replace
        return False

    def remove(self, find: str) -> int:
        if not self._available():
            return 0
        # TODO(bridge): POST /api/applicant/internal/memory/remove
        return 0

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        if not self._available():
            return MemorySnapshot()
        # TODO(bridge): GET /api/applicant/internal/memory/snapshot
        return MemorySnapshot()


class WorkspaceBridgeSkillStore(_Bridgeable):
    """``SkillStore`` over the workspace bridge (FR-MIND-2)."""

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        if not self._available():
            return ()
        # TODO(bridge): GET /api/applicant/internal/skills
        return ()

    def load(self, name: str) -> Skill | None:
        if not self._available():
            return None
        # TODO(bridge): GET /api/applicant/internal/skills/{name}
        return None

    def create(self, skill: Skill) -> Skill:
        if not self._available():
            return skill
        # TODO(bridge): POST /api/applicant/internal/skills
        return skill

    def patch(self, name: str, **fields: Any) -> Skill | None:
        if not self._available():
            return None
        # TODO(bridge): PATCH /api/applicant/internal/skills/{name}
        return None

    def edit(self, name: str, skill: Skill) -> Skill | None:
        if not self._available():
            return None
        # TODO(bridge): PUT /api/applicant/internal/skills/{name}
        return None

    def delete(self, name: str) -> bool:
        if not self._available():
            return False
        # TODO(bridge): DELETE /api/applicant/internal/skills/{name}
        return False


class WorkspaceBridgeRecallIndex(_Bridgeable):
    """``RecallIndex`` over the workspace bridge (FR-MIND-3)."""

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        if not self._available():
            return
        # TODO(bridge): the workspace owns indexing of its own run history; the engine
        # mostly READS recall. A POST endpoint can be added if engine-side indexing is
        # required.
        return

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        if not self._available():
            return ()
        # TODO(bridge): GET /api/applicant/internal/recall
        return ()
