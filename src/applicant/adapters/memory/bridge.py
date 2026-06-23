"""Workspace-bridge agent-memory adapters (FR-MIND-1/2/3).

Per ``docs/spec/agent-intelligence.md`` §10 the **recommended** store placement is:
keep the Hermes-derived memory/skills substrate where it already lives (the
front-door ``workspace/services/memory/`` — it already has the extractors, the
ChromaDB vector store, and the routes) and have the **engine** reach it as a thin
client over the existing engine->workspace callback channel
(``APPLICANT_INTERNAL_TOKEN`` / ``WORKSPACE_URL``).

These adapters are that thin client. They DEGRADE to empty/in-memory behavior when
the channel is OFF (``WorkspacePort.available()`` is False) so the engine still
boots and the hermetic lane stays offline. Every call is wrapped so a
``WorkspaceError`` (timeout / down workspace / non-2xx) never escapes — it degrades
to the same empty result as the OFF channel, so a flaky front-door never 500s the
engine loop.

**Bridge endpoints on the workspace side** (implemented in
``workspace/routes/applicant_internal_routes.py``, token-gated):

* ``GET  /api/applicant/internal/memory/snapshot?scope=&campaign_id=``
    -> ``{"environment": [{text,kind,scope,campaign_id}], "user": [...], "truncated": bool}``
* ``POST /api/applicant/internal/memory/add``      body: ``{text,kind,scope,campaign_id}``
* ``POST /api/applicant/internal/memory/replace``  body: ``{find, entry:{...}}`` -> ``{replaced: bool}``
* ``POST /api/applicant/internal/memory/remove``   body: ``{find}`` -> ``{removed: int}``
* ``GET  /api/applicant/internal/skills?scope=&campaign_id=``  (L0 metadata list)
* ``GET  /api/applicant/internal/skills/{name}``               (L1 full body)
* ``POST /api/applicant/internal/skills``          (create) body: SKILL.md fields
* ``PATCH/api/applicant/internal/skills/{name}``   (patch)  body: changed fields
* ``PUT  /api/applicant/internal/skills/{name}``   (edit)   body: full SKILL.md fields
* ``DELETE /api/applicant/internal/skills/{name}``
* ``GET  /api/applicant/internal/recall?q=&limit=&scope=&campaign_id=``
    -> ``{"hits": [{run_id,text,score,campaign_id}]}``

A thin client surface (``_BridgeClient``) is the only thing these adapters depend on
from the workspace port: ``available()`` plus the typed ``memory_*``/``skill*``/
``recall`` methods added to ``HttpWorkspaceClient``. The existing ``WorkspacePort``
Protocol stays unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import MemoryEntry, MemorySnapshot
from applicant.ports.driven.recall_index import RecallHit
from applicant.ports.driven.skill_store import Skill, SkillMeta

log = get_logger(__name__)


class _BridgeClient(Protocol):
    """The subset of the workspace client the bridge adapters use.

    ``HttpWorkspaceClient`` satisfies this; only ``available()`` gates whether the
    typed methods are attempted at all.
    """

    def available(self) -> bool: ...


def _try(call, default):
    """Run a bridge ``call`` (a no-arg lambda) and degrade on any WorkspaceError.

    A down/flaky front-door (timeout, refused, non-2xx, bad JSON) must never escape
    into the engine loop — it degrades to ``default`` exactly like the OFF channel.
    """
    # Local import keeps the ports layer free of the adapters' httpx dependency.
    from applicant.ports.driven.workspace import WorkspaceError

    try:
        return call()
    except WorkspaceError as exc:  # down/flaky workspace — degrade, never raise
        log.debug("memory_bridge_degraded", error=str(exc))
        return default


def _str_or_none(v: Any) -> str | None:
    return None if v in (None, "") else str(v)


class _Bridgeable:
    """Shared availability gate for the bridge adapters."""

    def __init__(self, workspace: _BridgeClient | None) -> None:
        self._workspace = workspace

    def _available(self) -> bool:
        ws = self._workspace
        return bool(ws is not None and ws.available())


class WorkspaceBridgeMemoryStore(_Bridgeable):
    """``MemoryStore`` over the workspace bridge (FR-MIND-1).

    Degrades to an empty/no-op result when the channel is OFF or the front-door is
    unreachable, so the engine boots and stays hermetic.
    """

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        if not self._available():
            log.debug("memory_bridge_offline", op="add")
            return entry
        body = {
            "text": entry.text,
            "kind": entry.kind,
            "scope": entry.scope,
            "campaign_id": entry.campaign_id,
        }
        _try(lambda: self._workspace.memory_add(body=body), None)
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        if not self._available():
            return False
        body = {
            "find": find,
            "entry": {
                "text": entry.text,
                "kind": entry.kind,
                "scope": entry.scope,
                "campaign_id": entry.campaign_id,
            },
        }
        res = _try(lambda: self._workspace.memory_replace(body=body), None)
        return bool(isinstance(res, dict) and res.get("replaced"))

    def remove(self, find: str) -> int:
        if not self._available():
            return 0
        res = _try(lambda: self._workspace.memory_remove(body={"find": find}), None)
        if isinstance(res, dict):
            try:
                return int(res.get("removed") or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        if not self._available():
            return MemorySnapshot()
        res = _try(
            lambda: self._workspace.memory_snapshot(scope=scope, campaign_id=campaign_id),
            None,
        )
        if not isinstance(res, dict):
            return MemorySnapshot()
        env = tuple(_to_entry(e) for e in (res.get("environment") or []) if isinstance(e, dict))
        usr = tuple(_to_entry(e) for e in (res.get("user") or []) if isinstance(e, dict))
        return MemorySnapshot(
            environment=env, user=usr, truncated=bool(res.get("truncated"))
        )


def _to_entry(d: dict) -> MemoryEntry:
    from applicant.ports.driven.memory_store import KIND_ENVIRONMENT, SCOPE_GLOBAL

    return MemoryEntry(
        text=str(d.get("text") or ""),
        kind=str(d.get("kind") or KIND_ENVIRONMENT),
        scope=str(d.get("scope") or SCOPE_GLOBAL),
        campaign_id=_str_or_none(d.get("campaign_id")),
    )


class WorkspaceBridgeSkillStore(_Bridgeable):
    """``SkillStore`` over the workspace bridge (FR-MIND-2)."""

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        if not self._available():
            return ()
        res = _try(
            lambda: self._workspace.skills_list(scope=scope, campaign_id=campaign_id),
            None,
        )
        rows = res.get("skills") if isinstance(res, dict) else None
        if not isinstance(rows, list):
            return ()
        return tuple(_to_meta(r) for r in rows if isinstance(r, dict))

    def load(self, name: str) -> Skill | None:
        if not self._available():
            return None
        res = _try(lambda: self._workspace.skill_load(name), None)
        if not isinstance(res, dict) or not res.get("name"):
            return None
        return _to_skill(res)

    def create(self, skill: Skill) -> Skill:
        if not self._available():
            return skill
        _try(lambda: self._workspace.skill_create(body=_from_skill(skill)), None)
        return skill

    def patch(self, name: str, **fields: Any) -> Skill | None:
        if not self._available():
            return None
        res = _try(lambda: self._workspace.skill_patch(name, body=dict(fields)), None)
        return _to_skill(res) if isinstance(res, dict) and res.get("name") else None

    def edit(self, name: str, skill: Skill) -> Skill | None:
        if not self._available():
            return None
        res = _try(lambda: self._workspace.skill_edit(name, body=_from_skill(skill)), None)
        return _to_skill(res) if isinstance(res, dict) and res.get("name") else None

    def delete(self, name: str) -> bool:
        if not self._available():
            return False
        res = _try(lambda: self._workspace.skill_delete(name), None)
        return bool(isinstance(res, dict) and res.get("deleted"))


def _to_meta(d: dict) -> SkillMeta:
    from applicant.ports.driven.skill_store import SKILL_SCOPE_GLOBAL

    return SkillMeta(
        name=str(d.get("name") or ""),
        description=str(d.get("description") or ""),
        when_to_use=str(d.get("when_to_use") or ""),
        version=str(d.get("version") or "1.0.0"),
        scope=str(d.get("scope") or SKILL_SCOPE_GLOBAL),
        campaign_id=_str_or_none(d.get("campaign_id")),
        source=str(d.get("source") or "learned"),
    )


def _to_skill(d: dict) -> Skill:
    from applicant.ports.driven.skill_store import SKILL_SCOPE_GLOBAL

    def _tup(key: str) -> tuple[str, ...]:
        v = d.get(key)
        return tuple(str(x) for x in v) if isinstance(v, list) else ()

    return Skill(
        name=str(d.get("name") or ""),
        description=str(d.get("description") or ""),
        version=str(d.get("version") or "1.0.0"),
        when_to_use=str(d.get("when_to_use") or ""),
        procedure=_tup("procedure"),
        pitfalls=_tup("pitfalls"),
        verification=_tup("verification"),
        scope=str(d.get("scope") or SKILL_SCOPE_GLOBAL),
        campaign_id=_str_or_none(d.get("campaign_id")),
        source=str(d.get("source") or "learned"),
        tags=_tup("tags"),
    )


def _from_skill(s: Skill) -> dict:
    return {
        "name": s.name,
        "description": s.description,
        "version": s.version,
        "when_to_use": s.when_to_use,
        "procedure": list(s.procedure),
        "pitfalls": list(s.pitfalls),
        "verification": list(s.verification),
        "scope": s.scope,
        "campaign_id": s.campaign_id,
        "source": s.source,
        "tags": list(s.tags),
    }


class WorkspaceBridgeRecallIndex(_Bridgeable):
    """``RecallIndex`` over the workspace bridge (FR-MIND-3)."""

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        # The workspace owns indexing of its own run history; the engine READS recall
        # over the bridge. No-op here (a POST index endpoint can be added later if
        # engine-side indexing is required).
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
        res = _try(
            lambda: self._workspace.recall(
                query=query, limit=limit, scope=scope, campaign_id=campaign_id
            ),
            None,
        )
        hits = res.get("hits") if isinstance(res, dict) else None
        if not isinstance(hits, list):
            return ()
        out: list[RecallHit] = []
        for h in hits:
            if not isinstance(h, dict):
                continue
            try:
                score = float(h.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            out.append(
                RecallHit(
                    run_id=str(h.get("run_id") or ""),
                    text=str(h.get("text") or ""),
                    score=score,
                    campaign_id=_str_or_none(h.get("campaign_id")),
                )
            )
        return tuple(out[:limit])
