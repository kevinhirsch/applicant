"""Durable SQL agent-memory adapters (FR-MIND-1/2/3, #286).

The DURABLE counterpart to ``in_memory.py``: the same ``MemoryStore`` /
``SkillStore`` / ``RecallIndex`` behavior, but persisted to the shared SQLAlchemy
storage stack so the curated-memory trio SURVIVES an engine restart/rebuild. This
is the fix for the ephemeral ``in_memory`` default that wiped a "remembers you"
product's memory on every restart.

Design rules (why this is safe under 24/7 + DBOS queues):

* **Short-lived session per operation.** Every op opens a FRESH session from the
  injected ``session_factory`` and closes it — it never holds the per-tick / per-
  request isolated Session the container hands its other stacks. A fresh session
  per op is what makes concurrent writes (multiple worker threads, DBOS queues)
  safe from lost-updates and cross-op transaction bleed.
* **Local + fast read path — NO network.** ``snapshot`` is a SINGLE indexed query
  (the guard against re-introducing the disabled ``bridge`` backend's ~45s hot-
  path stall); ``recall.search`` is a bounded, dependency-free keyword rank over
  persisted rows with the same tokenizer as the in-memory reference.
* **Behavioral parity.** ``snapshot`` enforces the SAME char bounds as
  ``InMemoryMemoryStore`` via the pure ``enforce_bounds`` policy, and scope/kind
  filtering matches the in-memory adapter exactly.
* **Bounded growth.** ``add`` prunes the oldest rows beyond a per-(scope,campaign)
  cap so the table (and therefore the snapshot query) stays bounded over a 24/7
  lifetime — the same "cap it so a rewritten blob can't grow unbounded" philosophy
  as ``learning_service.cap_feature_stats``.

Safety semantics are UNCHANGED: the write-approval gate (MEMORY_WRITE_APPROVAL)
and the advisory-only ``claims_authority`` filtering live ABOVE this store (in
curation / chat / scoring). This adapter only persists; it grants nothing.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import OperationalError

from applicant.adapters.memory.in_memory import _tokenize
from applicant.adapters.storage.models import (
    MemoryEntryModel,
    RecallEntryModel,
    SkillModel,
)
from applicant.core.rules.agent_memory import (
    DEFAULT_MEMORY_MAX_CHARS,
    DEFAULT_USER_MAX_CHARS,
    enforce_bounds,
)
from applicant.ports.driven.memory_store import (
    KIND_USER,
    SCOPE_CAMPAIGN,
    MemoryEntry,
    MemorySnapshot,
)
from applicant.ports.driven.recall_index import RecallHit
from applicant.ports.driven.skill_store import Skill, SkillMeta

#: Retained rows per (scope, campaign_id) bucket before ``add`` prunes the oldest.
#: Bounds the table + the snapshot query over a 24/7 lifetime (mirrors the
#: ``learning_service._FEATURE_STATS_CAP`` cap-so-it-can't-grow-unbounded rule).
DEFAULT_MAX_ROWS_PER_SCOPE = 500
#: Candidate rows the recall search scans before ranking (bounded read, FR-MIND-13).
_RECALL_SCAN_LIMIT = 1000
#: Bounded retry for transient write serialization (Postgres) / "database is
#: locked" (SQLite under concurrent short-lived writers). Postgres never needs it
#: for independent inserts; SQLite waits on its busy_timeout first, this is a
#: last-resort backstop so a concurrent burst never surfaces as a hard error.
_WRITE_RETRIES = 5


def _run_write(session_factory: Callable[[], Any], fn: Callable[[Any], Any]) -> Any:
    """Run ``fn(session)`` in a FRESH short-lived session, committing on success.

    Retries a transient serialization/lock error a bounded number of times; any
    other error rolls back and propagates. The session is always closed.
    """
    last: Exception | None = None
    for attempt in range(_WRITE_RETRIES):
        session = session_factory()
        try:
            result = fn(session)
            session.commit()
            return result
        except OperationalError as exc:  # pragma: no cover - timing dependent
            session.rollback()
            last = exc
            msg = str(exc).lower()
            if "locked" not in msg and "deadlock" not in msg and "serial" not in msg:
                raise
            time.sleep(min(0.02 * (attempt + 1), 0.2))
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    raise last  # type: ignore[misc]


def _run_read(session_factory: Callable[[], Any], fn: Callable[[Any], Any]) -> Any:
    """Run ``fn(session)`` in a FRESH short-lived read session, always closed."""
    session = session_factory()
    try:
        return fn(session)
    finally:
        session.close()


class SqlMemoryStore:
    """Durable ``MemoryStore`` (FR-MIND-1) — behaviorally identical to in-memory."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        memory_max_chars: int = DEFAULT_MEMORY_MAX_CHARS,
        user_max_chars: int = DEFAULT_USER_MAX_CHARS,
        max_rows_per_scope: int = DEFAULT_MAX_ROWS_PER_SCOPE,
    ) -> None:
        self._sf = session_factory
        self._memory_max_chars = memory_max_chars
        self._user_max_chars = user_max_chars
        self._max_rows_per_scope = max_rows_per_scope

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        def _op(session: Any) -> None:
            session.add(
                MemoryEntryModel(
                    campaign_id=entry.campaign_id,
                    kind=entry.kind,
                    scope=entry.scope,
                    text=entry.text,
                )
            )
            session.flush()
            self._prune(session, entry.scope, entry.campaign_id)

        _run_write(self._sf, _op)
        return entry

    def _prune(self, session: Any, scope: str, campaign_id: str | None) -> None:
        """Delete the oldest rows in this (scope, campaign) bucket beyond the cap."""
        cap = self._max_rows_per_scope
        if cap <= 0:
            return
        bucket = (MemoryEntryModel.scope == scope) & (
            MemoryEntryModel.campaign_id == campaign_id
        )
        total = session.execute(
            select(func.count()).select_from(MemoryEntryModel).where(bucket)
        ).scalar_one()
        if total <= cap:
            return
        surplus_ids = session.execute(
            select(MemoryEntryModel.id)
            .where(bucket)
            .order_by(MemoryEntryModel.id.asc())
            .limit(total - cap)
        ).scalars().all()
        if surplus_ids:
            session.execute(
                delete(MemoryEntryModel).where(MemoryEntryModel.id.in_(surplus_ids))
            )

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        def _op(session: Any) -> bool:
            rows = session.execute(
                select(MemoryEntryModel).order_by(MemoryEntryModel.id.asc())
            ).scalars().all()
            for row in rows:
                if find in (row.text or ""):
                    row.text = entry.text
                    row.kind = entry.kind
                    row.scope = entry.scope
                    row.campaign_id = entry.campaign_id
                    return True
            return False

        return _run_write(self._sf, _op)

    def remove(self, find: str) -> int:
        def _op(session: Any) -> int:
            rows = session.execute(
                select(MemoryEntryModel.id, MemoryEntryModel.text)
            ).all()
            matched = [rid for rid, text in rows if find in (text or "")]
            if matched:
                session.execute(
                    delete(MemoryEntryModel).where(MemoryEntryModel.id.in_(matched))
                )
            return len(matched)

        return _run_write(self._sf, _op)

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        def _op(session: Any) -> list[MemoryEntry]:
            # SINGLE indexed query (ix_memory_entries_scope_campaign_kind): global
            # entries plus this campaign's. ``== campaign_id`` renders IS NULL for a
            # None campaign, matching the in-memory visibility rule exactly.
            stmt = (
                select(MemoryEntryModel)
                .where(
                    or_(
                        MemoryEntryModel.scope != SCOPE_CAMPAIGN,
                        MemoryEntryModel.campaign_id == campaign_id,
                    )
                )
                .order_by(MemoryEntryModel.id.asc())
            )
            rows = session.execute(stmt).scalars().all()
            return [
                MemoryEntry(
                    text=r.text,
                    kind=r.kind,
                    scope=r.scope,
                    campaign_id=r.campaign_id,
                )
                for r in rows
            ]

        visible = _run_read(self._sf, _op)
        env = [e for e in visible if e.kind != KIND_USER]
        usr = [e for e in visible if e.kind == KIND_USER]
        env_texts, env_trunc = enforce_bounds(
            tuple(e.text for e in env), self._memory_max_chars
        )
        usr_texts, usr_trunc = enforce_bounds(
            tuple(e.text for e in usr), self._user_max_chars
        )
        env_kept = tuple(e for e in env if e.text in set(env_texts))
        usr_kept = tuple(e for e in usr if e.text in set(usr_texts))
        return MemorySnapshot(
            environment=env_kept,
            user=usr_kept,
            truncated=env_trunc or usr_trunc,
        )


class SqlSkillStore:
    """Durable ``SkillStore`` (FR-MIND-2) — keyed by ``name`` like the in-memory dict."""

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._sf = session_factory

    @staticmethod
    def _to_skill(row: SkillModel) -> Skill:
        return Skill(
            name=row.name,
            description=row.description or "",
            version=row.version or "1.0.0",
            when_to_use=row.when_to_use or "",
            procedure=tuple(row.procedure or ()),
            pitfalls=tuple(row.pitfalls or ()),
            verification=tuple(row.verification or ()),
            scope=row.scope or "global",
            campaign_id=row.campaign_id,
            source=row.source or "learned",
            tags=tuple(row.tags or ()),
        )

    @staticmethod
    def _apply(row: SkillModel, skill: Skill) -> None:
        row.description = skill.description
        row.version = skill.version
        row.when_to_use = skill.when_to_use
        row.procedure = list(skill.procedure)
        row.pitfalls = list(skill.pitfalls)
        row.verification = list(skill.verification)
        row.scope = skill.scope
        row.campaign_id = skill.campaign_id
        row.source = skill.source
        row.tags = list(skill.tags)

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        def _op(session: Any) -> tuple[SkillMeta, ...]:
            stmt = select(SkillModel)
            if scope is not None:
                stmt = stmt.where(SkillModel.scope == scope)
            if campaign_id is not None:
                # Keep global (NULL) skills + those matching the campaign.
                stmt = stmt.where(
                    or_(
                        SkillModel.campaign_id.is_(None),
                        SkillModel.campaign_id == campaign_id,
                    )
                )
            rows = session.execute(stmt).scalars().all()
            return tuple(self._to_skill(r).meta() for r in rows)

        return _run_read(self._sf, _op)

    def load(self, name: str) -> Skill | None:
        def _op(session: Any) -> Skill | None:
            row = session.get(SkillModel, name)
            return self._to_skill(row) if row is not None else None

        return _run_read(self._sf, _op)

    def create(self, skill: Skill) -> Skill:
        def _op(session: Any) -> None:
            row = session.get(SkillModel, skill.name)
            if row is None:
                row = SkillModel(name=skill.name)
                self._apply(row, skill)
                session.add(row)
            else:
                # Parity with the in-memory dict: create overwrites an existing name.
                self._apply(row, skill)

        _run_write(self._sf, _op)
        return skill

    def patch(self, name: str, **fields: object) -> Skill | None:
        def _op(session: Any) -> Skill | None:
            row = session.get(SkillModel, name)
            if row is None:
                return None
            updated = dataclasses.replace(self._to_skill(row), **fields)  # type: ignore[arg-type]
            self._apply(row, updated)
            return updated

        return _run_write(self._sf, _op)

    def edit(self, name: str, skill: Skill) -> Skill | None:
        def _op(session: Any) -> Skill | None:
            row = session.get(SkillModel, name)
            if row is None:
                return None
            self._apply(row, skill)
            row.name = skill.name
            return skill

        return _run_write(self._sf, _op)

    def delete(self, name: str) -> bool:
        def _op(session: Any) -> bool:
            row = session.get(SkillModel, name)
            if row is None:
                return False
            session.delete(row)
            return True

        return _run_write(self._sf, _op)


class SqlRecallIndex:
    """Durable ``RecallIndex`` (FR-MIND-3) — bounded, local keyword recall.

    Ranking reuses ``in_memory._tokenize`` so the SQL and in-memory adapters score
    identically. The read path is local + bounded (``LIMIT``) — never a network
    call — so recall can never re-introduce a hot-path stall.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._sf = session_factory

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        def _op(session: Any) -> None:
            row = session.get(RecallEntryModel, run_id)
            if row is None:
                session.add(
                    RecallEntryModel(
                        run_id=run_id, text=text, campaign_id=campaign_id
                    )
                )
            else:
                row.text = text
                row.campaign_id = campaign_id

        _run_write(self._sf, _op)

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        scope: str | None = None,
        campaign_id: str | None = None,
    ) -> tuple[RecallHit, ...]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return ()

        def _op(session: Any) -> list[tuple[str, str, str | None]]:
            stmt = select(
                RecallEntryModel.run_id,
                RecallEntryModel.text,
                RecallEntryModel.campaign_id,
            )
            if campaign_id is not None:
                stmt = stmt.where(
                    or_(
                        RecallEntryModel.campaign_id.is_(None),
                        RecallEntryModel.campaign_id == campaign_id,
                    )
                )
            stmt = stmt.limit(_RECALL_SCAN_LIMIT)
            return [(rid, text, camp) for rid, text, camp in session.execute(stmt)]

        rows = _run_read(self._sf, _op)
        hits: list[RecallHit] = []
        for run_id, text, camp in rows:
            t_tokens = _tokenize(text)
            if not t_tokens:
                continue
            overlap = q_tokens & t_tokens
            if not overlap:
                continue
            score = len(overlap) / len(q_tokens | t_tokens)
            hits.append(
                RecallHit(run_id=run_id, text=text, score=score, campaign_id=camp)
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return tuple(hits[:limit])
