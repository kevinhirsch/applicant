"""Temporal knowledge-graph agent-memory backend (Issue #307).

A vendor-able memory backend (Graphiti-style, Apache-2.0) selectable behind the
``MemoryStore`` port that keeps **bi-temporal** facts: when a fact is superseded
by a newer one, the older fact is NOT overwritten — it is retained with a
**closed validity window** (``valid_from`` … ``valid_to``), while the new fact
opens a fresh open-ended window. This preserves the history of what was believed
true and when, which a plain overwrite-on-replace store loses.

Implements the same ``add`` / ``replace`` / ``remove`` / ``snapshot`` operations
as every other backend so it is substitutable behind the port unchanged (#307).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from applicant.ports.driven.memory_store import (
    KIND_USER,
    SCOPE_CAMPAIGN,
    MemoryEntry,
    MemorySnapshot,
)


@dataclass(frozen=True)
class TemporalFact:
    """A fact with a validity window (#307).

    ``valid_to is None`` means the fact is currently believed true (an open
    window); a non-None ``valid_to`` means the fact was superseded at that time
    (a closed window) and is retained for history rather than deleted.
    """

    entry: MemoryEntry
    valid_from: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None

    @property
    def is_current(self) -> bool:
        return self.valid_to is None


class TemporalMemoryStore:
    """``MemoryStore`` backed by a bi-temporal fact log (#307).

    ``replace`` closes the prior matching fact's validity window and appends the
    new one, so the older fact is retained (with a closed window) rather than
    overwritten. ``snapshot`` returns only the currently-valid (open-window)
    facts so the loop sees one coherent present, while history stays queryable
    via :meth:`history`.
    """

    def __init__(self) -> None:
        self._facts: list[TemporalFact] = []
        self._lock = threading.RLock()

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        with self._lock:
            self._facts.append(TemporalFact(entry=entry))
        return entry

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        """Supersede the matching current fact, retaining it with a closed window."""
        now = datetime.now(UTC)
        with self._lock:
            replaced = False
            for i, fact in enumerate(self._facts):
                if fact.is_current and find in fact.entry.text:
                    # Close the old fact's window — keep it, do not delete it.
                    self._facts[i] = replace(fact, valid_to=now)
                    replaced = True
            if replaced:
                self._facts.append(TemporalFact(entry=entry, valid_from=now))
            return replaced

    def remove(self, find: str) -> int:
        """Close the validity window of matching current facts (history retained)."""
        now = datetime.now(UTC)
        with self._lock:
            removed = 0
            for i, fact in enumerate(self._facts):
                if fact.is_current and find in fact.entry.text:
                    self._facts[i] = replace(fact, valid_to=now)
                    removed += 1
            return removed

    def history(self, find: str | None = None) -> list[TemporalFact]:
        """Return all facts (current + superseded), optionally filtered by text."""
        with self._lock:
            return [
                f
                for f in self._facts
                if find is None or find in f.entry.text
            ]

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        with self._lock:
            current = [f.entry for f in self._facts if f.is_current]
        visible = [
            e
            for e in current
            if e.scope != SCOPE_CAMPAIGN or e.campaign_id == campaign_id
        ]
        env = tuple(e for e in visible if e.kind != KIND_USER)
        usr = tuple(e for e in visible if e.kind == KIND_USER)
        return MemorySnapshot(environment=env, user=usr)
