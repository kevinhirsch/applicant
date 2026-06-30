"""Curated playbook with delta updates — the ACE curation loop (Issue #306).

ACE (Agent Cognitive Evolution) keeps an *evolving playbook* of curated
strategies per ATS. A generation→reflection pass produces new insights, and the
playbook is updated with **structured incremental deltas** (add / revise / retire
individual strategy bullets) rather than wholesale rewrites — so a single bad
generation can never blow away the accumulated playbook, and each change is
auditable.

Pure application service: the playbook is an immutable value object; every
mutation returns a new playbook, and the deltas applied are returned alongside so
the caller can persist an audit trail. No I/O of its own — the caller wires
persistence (campaign ``learning_state`` / curated memory) around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime


@dataclass(frozen=True)
class PlaybookEntry:
    """One curated strategy bullet in an ATS playbook."""

    key: str
    text: str
    confidence: float = 0.5
    revision: int = 1


@dataclass(frozen=True)
class PlaybookDelta:
    """A single structured incremental change to the playbook (add/revise/retire)."""

    op: str  # "add" | "revise" | "retire"
    key: str
    text: str = ""


@dataclass(frozen=True)
class Playbook:
    """An immutable, curated set of strategies for one ATS / context."""

    ats: str
    entries: tuple[PlaybookEntry, ...] = ()
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get(self, key: str) -> PlaybookEntry | None:
        return next((e for e in self.entries if e.key == key), None)


class PlaybookService:
    """Apply structured incremental deltas to a curated playbook (#306).

    The curation loop calls :meth:`apply_deltas` with the deltas produced by a
    generation+reflection pass. Each delta touches a single entry; the rest of
    the playbook is preserved verbatim — never a wholesale rewrite.
    """

    def empty(self, ats: str) -> Playbook:
        return Playbook(ats=ats)

    def apply_deltas(
        self, playbook: Playbook, deltas: list[PlaybookDelta]
    ) -> tuple[Playbook, list[PlaybookDelta]]:
        """Apply ``deltas`` to ``playbook``, returning (new_playbook, applied).

        ``add`` inserts a new entry (no-op if the key already exists), ``revise``
        replaces an existing entry's text and bumps its revision (no-op if
        absent), ``retire`` removes an entry. Unrecognized ops are ignored.
        """
        entries = {e.key: e for e in playbook.entries}
        applied: list[PlaybookDelta] = []

        for delta in deltas:
            if delta.op == "add":
                if delta.key not in entries:
                    entries[delta.key] = PlaybookEntry(key=delta.key, text=delta.text)
                    applied.append(delta)
            elif delta.op == "revise":
                existing = entries.get(delta.key)
                if existing is not None and existing.text != delta.text:
                    entries[delta.key] = replace(
                        existing, text=delta.text, revision=existing.revision + 1
                    )
                    applied.append(delta)
            elif delta.op == "retire":
                if entries.pop(delta.key, None) is not None:
                    applied.append(delta)

        new_playbook = replace(
            playbook,
            entries=tuple(entries.values()),
            updated_at=datetime.now(UTC),
        )
        return new_playbook, applied
