"""MemoryStore port (FR-MIND-1 — curated memory).

The agent maintains a **bounded, curated** memory of (a) environment facts &
lessons (the analogue of the Hermes Agent (MIT) ``MEMORY.md``) and (b) user
preferences & communication style (analogue of ``USER.md``). Operations are
**add / replace / remove** (substring match), with enforced size bounds; the
memory is a **frozen snapshot loaded at the start of each loop tick**.

Per the per-tick discipline (FR-MIND-10) the snapshot is *read* per tick; writes
go to the durable store + the curation queue, never to a loop-instance field.

This is the **driven (outbound) port**. Adapters: an in-memory default (hermetic
boot/tests) and a workspace-bridge adapter that reaches the front-door substrate
under ``workspace/services/memory/`` over the engine->workspace callback channel
(see ``docs/spec/agent-intelligence.md`` §10 — recommended placement).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: Memory ``kind`` discriminators (FR-MIND-1): environment facts/lessons vs. the
#: user's own preferences/communication style. Mirrors the upstream MEMORY.md /
#: USER.md split, white-labeled.
KIND_ENVIRONMENT = "environment"
KIND_USER = "user"
MEMORY_KINDS = (KIND_ENVIRONMENT, KIND_USER)

#: Memory ``scope`` discriminators (FR-MIND-1): some lessons are campaign-specific
#: (a tenant's account flow), some global (the user's communication style).
SCOPE_GLOBAL = "global"
SCOPE_CAMPAIGN = "campaign"
MEMORY_SCOPES = (SCOPE_GLOBAL, SCOPE_CAMPAIGN)


@dataclass(frozen=True)
class MemoryEntry:
    """One curated memory line (FR-MIND-1).

    ``text`` is human-readable and editable in the front-door memory surface.
    ``kind`` is one of :data:`MEMORY_KINDS`; ``scope`` one of :data:`MEMORY_SCOPES`.
    ``campaign_id`` is set only for campaign-scoped entries (``None`` for global).
    """

    text: str
    kind: str = KIND_ENVIRONMENT
    scope: str = SCOPE_GLOBAL
    campaign_id: str | None = None


@dataclass(frozen=True)
class MemorySnapshot:
    """A bounded, frozen read of curated memory for one loop tick (FR-MIND-1).

    Split by kind so the prompt-builder can place environment lessons and user
    preferences in their respective tiers (FR-MIND-5). ``truncated`` is True when
    the durable store held more than the bounds allow and the snapshot was clipped.
    """

    environment: tuple[MemoryEntry, ...] = ()
    user: tuple[MemoryEntry, ...] = ()
    truncated: bool = False

    def all(self) -> tuple[MemoryEntry, ...]:
        return tuple(self.environment) + tuple(self.user)


@runtime_checkable
class MemoryStore(Protocol):
    """Outbound port for the agent's curated memory (FR-MIND-1)."""

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Append a curated memory line. Returns the stored entry."""
        ...

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        """Replace the first entry whose text contains ``find`` (substring match).

        Returns True if a replacement was made, False if no match was found.
        """
        ...

    def remove(self, find: str) -> int:
        """Remove every entry whose text contains ``find`` (substring match).

        Returns the number of entries removed.
        """
        ...

    def snapshot(self, scope: str | None = None, campaign_id: str | None = None) -> MemorySnapshot:
        """Return the **bounded, frozen** curated memory for a loop tick.

        ``scope``/``campaign_id`` filter to global + the given campaign's entries;
        ``None`` returns the global view. The result is clipped to the configured
        bounds (FR-MIND-1) and never grows the prompt unboundedly (FR-MIND-13).
        """
        ...
