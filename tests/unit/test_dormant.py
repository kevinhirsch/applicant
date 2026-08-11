"""Unit tests for the dormant-surface registry (FR-UI-2)."""

from __future__ import annotations

import dataclasses

import pytest
from dataclasses import FrozenInstanceError

from applicant.dormant import (
    DORMANT_SURFACES,
    DormantSurface,
    STATUS_DORMANT,
    STATUS_LIVE,
    seed_dormant_surfaces,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel-safety fixture (module has no lru_cache to clear)."""
    return


class TestDormantSurfaceConstants:
    """STATUS_LIVE and STATUS_DORMANT constants (FR-UI-2)."""

    @pytest.mark.unit
    def test_status_live_value(self) -> None:
        assert STATUS_LIVE == "live"

    @pytest.mark.unit
    def test_status_dormant_value(self) -> None:
        assert STATUS_DORMANT == "dormant"


class TestDormantSurfaceDataclass:
    """DormantSurface frozen dataclass fields, defaults, and immutability."""

    @pytest.mark.unit
    def test_all_six_fields_exist(self) -> None:
        fields = {f.name for f in dataclasses.fields(DormantSurface)}
        expected = {"key", "surface_name", "requirement_ids", "wiring_notes", "live_phase", "status"}
        assert fields == expected

    @pytest.mark.unit
    def test_default_status_is_dormant(self) -> None:
        """status defaults to STATUS_DORMANT when omitted."""
        s = DormantSurface(
            key="test_key",
            surface_name="Test surface",
            requirement_ids=("FR-TEST-1",),
            wiring_notes="Test wiring.",
            live_phase=0,
        )
        assert s.status == STATUS_DORMANT

    @pytest.mark.unit
    def test_custom_status_accepted(self) -> None:
        s = DormantSurface(
            key="live_test",
            surface_name="Live test",
            requirement_ids=(),
            wiring_notes="",
            live_phase=1,
            status=STATUS_LIVE,
        )
        assert s.status == STATUS_LIVE

    @pytest.mark.unit
    def test_immutable_raises_frozen_error(self) -> None:
        s = DormantSurface(
            key="frozen_test",
            surface_name="Frozen test",
            requirement_ids=(),
            wiring_notes="",
            live_phase=0,
        )
        with pytest.raises(FrozenInstanceError):
            s.key = "changed"

    @pytest.mark.unit
    def test_repr_includes_fields(self) -> None:
        s = DormantSurface(
            key="repr_test",
            surface_name="Repr surface",
            requirement_ids=("FR-R-1", "FR-R-2"),
            wiring_notes="check repr",
            live_phase=3,
        )
        r = repr(s)
        assert "repr_test" in r
        assert "Repr surface" in r
        assert "live_phase=3" in r
        assert "status='dormant'" in r

    @pytest.mark.unit
    def test_equality(self) -> None:
        a = DormantSurface("k", "n", ("r",), "w", 1, status=STATUS_LIVE)
        b = DormantSurface("k", "n", ("r",), "w", 1, status=STATUS_LIVE)
        assert a == b

    @pytest.mark.unit
    def test_inequality(self) -> None:
        a = DormantSurface("k1", "n", (), "", 0)
        b = DormantSurface("k2", "n", (), "", 0)
        assert a != b

    @pytest.mark.unit
    def test_hashable(self) -> None:
        """Frozen dataclass with only immutable fields is hashable."""
        s = DormantSurface("h", "n", ("r",), "w", 2)
        assert isinstance(hash(s), int)
        # can be added to a set
        _ = {s}


class TestDormantSurfacesTuple:
    """DORMANT_SURFACES tuple structure and count."""

    @pytest.mark.unit
    def test_is_tuple(self) -> None:
        assert isinstance(DORMANT_SURFACES, tuple)

    @pytest.mark.unit
    def test_all_are_dormant_surface_instances(self) -> None:
        for s in DORMANT_SURFACES:
            assert isinstance(s, DormantSurface)

    @pytest.mark.unit
    def test_count(self) -> None:
        assert len(DORMANT_SURFACES) == 15

    @pytest.mark.unit
    def test_each_has_valid_field_types(self) -> None:
        for s in DORMANT_SURFACES:
            assert isinstance(s.key, str) and len(s.key) > 0
            assert isinstance(s.surface_name, str) and len(s.surface_name) > 0
            assert isinstance(s.requirement_ids, tuple)
            assert len(s.requirement_ids) >= 1
            assert isinstance(s.wiring_notes, str) and len(s.wiring_notes) > 0
            assert isinstance(s.live_phase, int)
            assert s.status in (STATUS_LIVE, STATUS_DORMANT)

    @pytest.mark.unit
    def test_all_currently_live_in_source(self) -> None:
        """Per the actual source, all registered surfaces have status=STATUS_LIVE."""
        for s in DORMANT_SURFACES:
            assert s.status == STATUS_LIVE, f"Surface '{s.key}' is not live"

    @pytest.mark.unit
    def test_requirement_ids_immutable_type(self) -> None:
        for s in DORMANT_SURFACES:
            assert isinstance(s.requirement_ids, tuple)


class TestSeedDormantSurfaces:
    """seed_dormant_surfaces behavior with None storage session."""

    @pytest.mark.unit
    def test_returns_len_of_dormant_surfaces(self) -> None:
        result = seed_dormant_surfaces(None)
        assert result == len(DORMANT_SURFACES)

    @pytest.mark.unit
    def test_returns_integer(self) -> None:
        result = seed_dormant_surfaces(None)
        assert isinstance(result, int)

    @pytest.mark.unit
    def test_idempotent(self) -> None:
        """Calling twice with None returns the same value."""
        a = seed_dormant_surfaces(None)
        b = seed_dormant_surfaces(None)
        assert a == b == len(DORMANT_SURFACES)
