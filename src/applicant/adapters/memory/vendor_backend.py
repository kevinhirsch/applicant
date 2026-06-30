"""Vendor-able agent-memory backend behind the memory port (Issue #307).

Build-vs-buy for the memory substrate: a permissive, vendor-able backend
selectable behind the ``MemoryStore`` port, with the in-house store as the
default. The concrete vendor adapters (mem0, Letta — both Apache-2.0) live in
:mod:`applicant.adapters.memory.evaluation`; this module is the **named seam**
the factory/config select, and a thin :class:`VendorMemoryBackend` that satisfies
the same ``MemoryStore`` contract as the in-house store so swapping the backend
does not change the port contract.

The whole point of #307 is *substitutability*: any backend wired here writes and
reads through the identical ``add`` / ``replace`` / ``remove`` / ``snapshot``
operations, so the engine code above the port is unchanged.
"""

from __future__ import annotations

from applicant.adapters.memory.evaluation import (
    LettaMemoryStore,
    Mem0MemoryStore,
)
from applicant.adapters.memory.in_memory import InMemoryMemoryStore
from applicant.ports.driven.memory_store import MemoryEntry, MemorySnapshot

#: The vendor-able backends selectable behind the memory port (#307). The
#: in-house store remains the default; vendors are opt-in.
VENDOR_BACKENDS: dict[str, type] = {
    "mem0": Mem0MemoryStore,
    "letta": LettaMemoryStore,
    "in_house": InMemoryMemoryStore,
}


class VendorMemoryBackend:
    """A ``MemoryStore`` that delegates to a configured vendor implementation (#307).

    Satisfies the memory port identically to the in-house store: every operation
    is forwarded to the wrapped vendor store, so the engine writes and reads
    memory through the same port contract unchanged regardless of the backend.
    Falls back to the in-house in-memory store for an unknown vendor so boot is
    always safe.
    """

    def __init__(self, vendor: str = "in_house", *, delegate=None) -> None:
        self.vendor = vendor
        if delegate is not None:
            self._store = delegate
        else:
            backend_cls = VENDOR_BACKENDS.get(vendor, InMemoryMemoryStore)
            self._store = backend_cls()

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        return self._store.add(entry)

    def replace(self, find: str, entry: MemoryEntry) -> bool:
        return self._store.replace(find, entry)

    def remove(self, find: str) -> int:
        return self._store.remove(find)

    def snapshot(
        self, scope: str | None = None, campaign_id: str | None = None
    ) -> MemorySnapshot:
        return self._store.snapshot(scope=scope, campaign_id=campaign_id)


def build_vendor_backend(vendor: str = "in_house", *, delegate=None) -> VendorMemoryBackend:
    """Build a vendor-able memory backend behind the memory port (#307)."""
    return VendorMemoryBackend(vendor, delegate=delegate)
