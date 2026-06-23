"""In-memory agent-memory adapters (FR-MIND-1/2/3) — the hermetic default.

These implement the three driven ports with plain in-process state so the engine
boots and the test lane runs with no Postgres/chromadb/workspace. They are
thread-safe enough for the no-DB lane (a single lock per store).

Bounds and save-worthiness come from the pure core policy
(``core/rules/agent_memory``) so the adapter never drifts from the rule.
"""

from __future__ import annotations

import threading

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


class InMemoryMemoryStore:
    """``MemoryStore`` backed by an in-process list (FR-MIND-1)."""

    def __init__(
        self,
        *,
        memory_max_chars: int = DEFAULT_MEMORY_MAX_CHARS,
        user_max_chars: int = DEFAULT_USER_MAX_CHARS,
    ) -> None:
        self._entries: list[MemoryEntry] = []
        self._memory_max_chars = memory_max_chars
        self._user_max_chars = user_max_chars
        self._lock = threading.RLock()

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        with self._lock:
            self._entries.append(entry)
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        with self._lock:
            for i, e in enumerate(self._entries):
                if find in e.text:
                    self._entries[i] = entry
                    return True
        return False

    def remove(self, find: str) -> int:
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if find not in e.text]
            return before - len(self._entries)

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        with self._lock:
            visible = [
                e
                for e in self._entries
                if e.scope != SCOPE_CAMPAIGN or e.campaign_id == campaign_id
            ]
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


class InMemorySkillStore:
    """``SkillStore`` backed by an in-process dict (FR-MIND-2)."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._lock = threading.RLock()

    def list_skills(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> tuple[SkillMeta, ...]:
        with self._lock:
            metas = []
            for s in self._skills.values():
                if scope is not None and s.scope != scope:
                    continue
                if campaign_id is not None and s.campaign_id not in (None, campaign_id):
                    continue
                metas.append(s.meta())
            return tuple(metas)

    def load(self, name: str) -> Skill | None:
        with self._lock:
            return self._skills.get(name)

    def create(self, skill: Skill) -> Skill:
        with self._lock:
            self._skills[skill.name] = skill
        return skill

    def patch(self, name: str, **fields: object) -> Skill | None:
        with self._lock:
            cur = self._skills.get(name)
            if cur is None:
                return None
            import dataclasses

            updated = dataclasses.replace(cur, **fields)  # type: ignore[arg-type]
            self._skills[name] = updated
            return updated

    def edit(self, name: str, skill: Skill) -> Skill | None:
        with self._lock:
            if name not in self._skills:
                return None
            self._skills[name] = skill
            return skill

    def delete(self, name: str) -> bool:
        with self._lock:
            return self._skills.pop(name, None) is not None


class InMemoryRecallIndex:
    """``RecallIndex`` with a trivial keyword score (FR-MIND-3).

    A token-overlap ranking stands in for Postgres FTS + chromadb in the hermetic
    lane; it is deterministic and dependency-free.
    """

    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, str | None]] = {}  # run_id -> (text, campaign)
        self._lock = threading.RLock()

    def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
        with self._lock:
            self._rows[run_id] = (text, campaign_id)

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
        hits: list[RecallHit] = []
        with self._lock:
            rows = list(self._rows.items())
        for run_id, (text, camp) in rows:
            if campaign_id is not None and camp not in (None, campaign_id):
                continue
            t_tokens = _tokenize(text)
            if not t_tokens:
                continue
            overlap = q_tokens & t_tokens
            if not overlap:
                continue
            score = len(overlap) / len(q_tokens | t_tokens)
            hits.append(RecallHit(run_id=run_id, text=text, score=score, campaign_id=camp))
        hits.sort(key=lambda h: h.score, reverse=True)
        return tuple(hits[:limit])


def _tokenize(text: str) -> set[str]:
    return {w.strip(".,!?\";:'()[]").lower() for w in (text or "").split() if w.strip()}
