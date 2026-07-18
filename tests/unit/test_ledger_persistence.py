"""Unit tests for ConfigLedgerStore (DISC-2 durable snapshot adapter)."""

from __future__ import annotations

from typing import Any

import pytest

from applicant.adapters.storage.ledger_persistence import ConfigLedgerStore


class _MemoryStore:
    """Minimal in-memory test double matching the duck-typed store interface.

    Accepts ``.get(key) -> dict | None`` and ``.set(key, value)`` — the
    same shape ConfigLedgerStore expects from its ``memory_store`` kwarg.
    """

    def __init__(self) -> None:
        self._d: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        v = self._d.get(key)
        return dict(v) if v is not None else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._d[key] = dict(value)


class _BrokenStore:
    """Test double that raises on every operation — used for error-path tests."""

    def get(self, key: str) -> None:  # type: ignore[return]
        raise RuntimeError("simulated store error")

    def set(self, key: str, value: dict[str, Any]) -> None:
        raise RuntimeError("simulated store error")


@pytest.mark.unit
class TestConfigLedgerStore:
    """ConfigLedgerStore snapshot persistence (memory-store lane)."""

    @pytest.fixture(autouse=True)
    def _fresh_ledger(self) -> None:
        """xdist parallel safety: no shared state between workers.

        ConfigLedgerStore carries no module-level caches or global state,
        so the fixture is a structural marker. Each test creates its own
        ``_MemoryStore`` / ``_BrokenStore`` instances.
        """

    # --- load() ---

    def test_load_returns_none_when_no_snapshot(self) -> None:
        store = _MemoryStore()
        ledger = ConfigLedgerStore("test_key", memory_store=store)
        assert ledger.load() is None

    def test_load_returns_saved_dict_after_save(self) -> None:
        store = _MemoryStore()
        ledger = ConfigLedgerStore("test_key", memory_store=store)
        data = {"foo": "bar", "count": 42, "nested": {"flag": True}}
        ledger.save(data)
        assert ledger.load() == data

    def test_load_returns_none_on_error_gracefully(self) -> None:
        broken = _BrokenStore()
        ledger = ConfigLedgerStore("test_key", memory_store=broken)
        assert ledger.load() is None

    def test_load_returns_copy_not_fresh_reference(self) -> None:
        """Confirm the store returns a copy so mutations don't leak."""
        store = _MemoryStore()
        ledger = ConfigLedgerStore("test_key", memory_store=store)
        ledger.save({"v": 1})
        got = ledger.load()
        assert got is not None
        got["v"] = 999
        # A second load must still see the original value.
        assert ledger.load() == {"v": 1}

    # --- save() ---

    def test_save_does_not_raise_on_error(self) -> None:
        broken = _BrokenStore()
        ledger = ConfigLedgerStore("test_key", memory_store=broken)
        # Must not propagate the exception — it's swallowed per production code.
        ledger.save({"should": "not crash"})

    def test_save_overwrites_previous_value(self) -> None:
        store = _MemoryStore()
        ledger = ConfigLedgerStore("test_key", memory_store=store)
        ledger.save({"first": "value"})
        ledger.save({"second": "value"})
        assert ledger.load() == {"second": "value"}
