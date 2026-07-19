"""Unit tests for applicant.adapters.memory.vendor_backend — vendor-able memory backends (#307).

Parallel-safe: a module-level autouse fixture provides xdist isolation.
"""

from __future__ import annotations

import pytest

from applicant.adapters.memory.evaluation import LettaMemoryStore, Mem0MemoryStore
from applicant.adapters.memory.in_memory import InMemoryMemoryStore
from applicant.adapters.memory.vendor_backend import (
    VENDOR_BACKENDS,
    VendorMemoryBackend,
    build_vendor_backend,
)
from applicant.ports.driven.memory_store import MemoryEntry, MemorySnapshot


@pytest.fixture(autouse=True)
def _vendor_backend_isolation() -> None:
    """Module-level autouse: ensures parallel-safe xdist execution.

    VendorMemoryBackend has no module-level lru_cache or shared state,
    but the fixture convention prevents future regressions.
    """
    return


class TestVendorBackendsRegistry:
    """VENDOR_BACKENDS dict (#307)."""

    def test_has_expected_keys(self) -> None:
        assert set(VENDOR_BACKENDS) == {"mem0", "letta", "in_house"}

    def test_in_house_backend(self) -> None:
        assert VENDOR_BACKENDS["in_house"] is InMemoryMemoryStore

    def test_mem0_backend(self) -> None:
        assert VENDOR_BACKENDS["mem0"] is Mem0MemoryStore

    def test_letta_backend(self) -> None:
        assert VENDOR_BACKENDS["letta"] is LettaMemoryStore


class TestVendorMemoryBackendConstruction:
    """Construction of VendorMemoryBackend (#307)."""

    def test_default_vendor_is_in_house(self) -> None:
        backend = VendorMemoryBackend()
        assert backend.vendor == "in_house"
        # Default uses InMemoryMemoryStore — verify by using it
        entry = MemoryEntry(text="hello world")
        stored = backend.add(entry)
        assert stored is entry

    def test_explicit_in_house_vendor(self) -> None:
        backend = VendorMemoryBackend(vendor="in_house")
        entry = MemoryEntry(text="test")
        assert backend.add(entry) is entry

    def test_delegate_overrides_vendor_backend(self) -> None:
        """Explicit delegate is used regardless of the vendor string."""
        delegate = InMemoryMemoryStore()
        backend = VendorMemoryBackend(vendor="in_house", delegate=delegate)
        assert backend._store is delegate

    def test_unknown_vendor_falls_back_to_in_memory(self) -> None:
        """An unrecognized vendor string falls back to InMemoryMemoryStore."""
        backend = VendorMemoryBackend(vendor="nonexistent_vendor")
        assert backend.vendor == "nonexistent_vendor"
        assert isinstance(backend._store, InMemoryMemoryStore)


class TestBuildVendorBackendFactory:
    """`build_vendor_backend` factory function (#307)."""

    def test_factory_default(self) -> None:
        backend = build_vendor_backend()
        assert isinstance(backend, VendorMemoryBackend)
        assert backend.vendor == "in_house"

    def test_factory_with_delegate(self) -> None:
        delegate = InMemoryMemoryStore()
        backend = build_vendor_backend(delegate=delegate)
        assert backend._store is delegate

    def test_factory_with_vendor(self) -> None:
        backend = build_vendor_backend(vendor="in_house")
        assert backend.vendor == "in_house"
        entry = MemoryEntry(text="via factory")
        assert backend.add(entry) is entry


class TestVendorMemoryBackendAdd:
    """VendorMemoryBackend.add — delegates to self._store.add."""

    @pytest.fixture
    def backend(self) -> VendorMemoryBackend:
        return VendorMemoryBackend()

    def test_add_returns_entry(self, backend: VendorMemoryBackend) -> None:
        entry = MemoryEntry(text="alpha")
        assert backend.add(entry) is entry

    def test_add_multiple_routes_under_snapshot(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="one"))
        backend.add(MemoryEntry(text="two"))
        snap = backend.snapshot()
        texts = [e.text for e in snap.all()]
        assert "one" in texts
        assert "two" in texts


class TestVendorMemoryBackendReplace:
    """VendorMemoryBackend.replace — delegates to self._store.replace."""

    @pytest.fixture
    def backend(self) -> VendorMemoryBackend:
        backend = VendorMemoryBackend()
        backend.add(MemoryEntry(text="stay"))
        return backend

    def test_replace_match(self, backend: VendorMemoryBackend) -> None:
        new_entry = MemoryEntry(text="replaced")
        assert backend.replace("stay", new_entry) is True

    def test_replace_no_match(self, backend: VendorMemoryBackend) -> None:
        new_entry = MemoryEntry(text="replaced")
        assert backend.replace("nonexistent", new_entry) is False

    def test_replace_actually_changes_store(self, backend: VendorMemoryBackend) -> None:
        new_entry = MemoryEntry(text="replaced")
        backend.replace("stay", new_entry)
        snap = backend.snapshot()
        texts = [e.text for e in snap.all()]
        assert "stay" not in texts
        assert "replaced" in texts


class TestVendorMemoryBackendRemove:
    """VendorMemoryBackend.remove — delegates to self._store.remove."""

    @pytest.fixture
    def backend(self) -> VendorMemoryBackend:
        return VendorMemoryBackend()

    def test_remove_match(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="target"))
        assert backend.remove("target") == 1

    def test_remove_no_match(self, backend: VendorMemoryBackend) -> None:
        assert backend.remove("not_there") == 0

    def test_remove_multiple_match(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="delete me"))
        backend.add(MemoryEntry(text="delete me too"))
        assert backend.remove("delete") == 2

    def test_remove_actually_removes_from_store(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="foo"))
        backend.add(MemoryEntry(text="bar"))
        backend.remove("foo")
        snap = backend.snapshot()
        texts = [e.text for e in snap.all()]
        assert "foo" not in texts
        assert "bar" in texts


class TestVendorMemoryBackendSnapshot:
    """VendorMemoryBackend.snapshot — delegates to self._store.snapshot."""

    @pytest.fixture
    def backend(self) -> VendorMemoryBackend:
        return VendorMemoryBackend()

    def test_snapshot_empty(self, backend: VendorMemoryBackend) -> None:
        snap = backend.snapshot()
        assert isinstance(snap, MemorySnapshot)
        assert len(snap.all()) == 0
        assert snap.truncated is False

    def test_snapshot_with_entries(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="env entry", kind="environment"))
        backend.add(MemoryEntry(text="user entry", kind="user"))
        snap = backend.snapshot()
        texts = {e.text for e in snap.all()}
        assert "env entry" in texts
        assert "user entry" in texts

    def test_snapshot_kind_split(self, backend: VendorMemoryBackend) -> None:
        backend.add(MemoryEntry(text="in env", kind="environment"))
        backend.add(MemoryEntry(text="in user", kind="user"))
        snap = backend.snapshot()
        assert any(e.text == "in env" for e in snap.environment)
        assert any(e.text == "in user" for e in snap.user)

    def test_snapshot_kind_filters(self, backend: VendorMemoryBackend) -> None:
        """Non-user entries go to environment, user entries go to user."""
        backend.add(MemoryEntry(text="default kind"))
        snap = backend.snapshot()
        assert any(e.text == "default kind" for e in snap.environment)
        assert all(e.text != "default kind" for e in snap.user)


class TestVendorMemoryBackendWithExplicitDelegate:
    """Operations through an explicitly injected delegate."""

    def test_delegate_isolation(self) -> None:
        """Each delegate instance is independent."""
        d1 = InMemoryMemoryStore()
        d2 = InMemoryMemoryStore()
        b1 = VendorMemoryBackend(delegate=d1)
        b2 = VendorMemoryBackend(delegate=d2)
        b1.add(MemoryEntry(text="only in first"))
        texts_1 = {e.text for e in b1.snapshot().all()}
        texts_2 = {e.text for e in b2.snapshot().all()}
        assert "only in first" in texts_1
        assert "only in first" not in texts_2

    def test_delegate_receives_operation(self) -> None:
        """Operations write through to the injected delegate."""
        delegate = InMemoryMemoryStore()
        backend = VendorMemoryBackend(delegate=delegate)
        entry = MemoryEntry(text="via delegate")
        backend.add(entry)
        # The delegate instance itself should have the entry
        snap = delegate.snapshot()
        assert any(e.text == "via delegate" for e in snap.all())
