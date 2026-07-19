"""Unit tests for the field-match-rate / probable-wrong-ATS rule (FR-PREFILL-2/6).

Covers field_match_rate (clamped filled/detected fraction) and
is_probable_wrong_ats (floor comparison).
"""

from __future__ import annotations

import pytest

from applicant.core.rules.ats_match_rate import (
    DEFAULT_MATCH_RATE_FLOOR,
    field_match_rate,
    is_probable_wrong_ats,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel-execution safety: no module-level cache currently, but the
    fixture is mandatory for xdist compatibility."""
    pass


class TestFieldMatchRate:
    """field_match_rate returns the clamped filled/detected fraction [0.0, 1.0]."""

    @pytest.mark.parametrize(
        ("filled", "detected", "expected"),
        [
            # -- normal cases -------------------------------------------------------
            (5, 10, 0.5),
            (3, 10, 0.3),
            (10, 10, 1.0),
            (1, 4, 0.25),
            # -- overflow / clamping ------------------------------------------------
            (10, 5, 1.0),  # 2.0 clamped to 1.0
            # -- zero detected ------------------------------------------------------
            (5, 0, 1.0),   # no detected fields -> perfect rate
            (5, -1, 1.0),  # negative detected also treated as "nothing to fill"
            # -- zero / negative filled ---------------------------------------------
            (0, 10, 0.0),
            (-1, 10, 0.0),
            # -- both zero / negative -----------------------------------------------
            (0, 0, 1.0),   # detected is checked first: 0 -> 1.0
            (-1, -1, 1.0),
        ],
    )
    def test_field_match_rate(self, filled: int, detected: int, expected: float) -> None:
        assert field_match_rate(filled, detected) == expected


class TestIsProbableWrongAts:
    """is_probable_wrong_ats flags runs with a match rate below the floor."""

    def test_default_floor_is_0_2(self) -> None:
        assert DEFAULT_MATCH_RATE_FLOOR == 0.2

    @pytest.mark.parametrize(
        ("filled", "detected", "floor", "expected"),
        [
            # -- above floor (3/10 = 0.3 >= 0.2) -----------------------------------
            (3, 10, 0.2, False),
            # -- at floor (2/10 = 0.2 is NOT < 0.2) --------------------------------
            (2, 10, 0.2, False),
            # -- below floor (1/10 = 0.1 < 0.2) ------------------------------------
            (1, 10, 0.2, True),
            # -- zero filled (0/10 = 0.0 < 0.2) ------------------------------------
            (0, 10, 0.2, True),
            # -- custom floor 0.5 ---------------------------------------------------
            (4, 10, 0.5, True),   # 4/10=0.4 < 0.5
            (6, 10, 0.5, False),  # 6/10=0.6 >= 0.5
            # -- no detected fields -------------------------------------------------
            (0, 0, 0.2, False),   # detected <= 0 -> False
            (5, 0, 0.2, False),
            (5, -1, 0.2, False),
            # -- negative filled, detected > 0 --------------------------------------
            (-1, 10, 0.2, True),  # rate=0.0 < 0.2
        ],
    )
    def test_is_probable_wrong_ats(
        self, filled: int, detected: int, floor: float, expected: bool
    ) -> None:
        assert is_probable_wrong_ats(filled, detected, floor=floor) is expected

    def test_is_probable_wrong_ats_uses_default_floor(self) -> None:
        """Omitting floor uses DEFAULT_MATCH_RATE_FLOOR (0.2)."""
        assert is_probable_wrong_ats(1, 10) is True    # 0.1 < 0.2
        assert is_probable_wrong_ats(3, 10) is False   # 0.3 >= 0.2
