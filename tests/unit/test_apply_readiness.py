from __future__ import annotations

import pytest

from applicant.core.rules.apply_readiness import (
    LABEL_KEY_SKILLS,
    LABEL_LOCATIONS,
    LABEL_RESUME,
    LABEL_SALARY_FLOOR,
    LABEL_TARGET_ROLES,
    LABEL_WORK_MODE,
    ApplyReadiness,
    evaluate_apply_readiness,
)


# --- parallel-safety fixture (no caches in this module, but convention requires one for xdist) ---
@pytest.fixture(autouse=True)
def _no_cache() -> None:
    yield


class TestApplyReadinessDataclass:
    """ApplyReadiness is a frozen dataclass."""

    @pytest.mark.unit
    def test_ready_true(self) -> None:
        r = ApplyReadiness(ready=True, missing=(), reason="all good")
        assert r.ready is True
        assert r.missing == ()
        assert r.reason == "all good"

    @pytest.mark.unit
    def test_ready_false_with_missing(self) -> None:
        r = ApplyReadiness(ready=False, missing=("x",), reason="need x")
        assert r.ready is False
        assert r.missing == ("x",)

    @pytest.mark.unit
    def test_frozen(self) -> None:
        r = ApplyReadiness(ready=True, missing=(), reason="")
        with pytest.raises((AttributeError, TypeError, Exception)):
            r.ready = False  # type: ignore[misc]


class TestEvaluateApplyReadiness:
    """evaluate_apply_readiness returns correct readiness for each combination."""

    @pytest.mark.unit
    def test_all_present(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=True,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.ready is True
        assert result.missing == ()
        assert result.reason == "Ready to start applying — every essential is in place."

    # --- each single missing field ---

    @pytest.mark.unit
    def test_missing_titles(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=False,
            has_work_modes=True,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.ready is False
        assert result.missing == (LABEL_TARGET_ROLES,)
        assert LABEL_TARGET_ROLES in result.reason

    @pytest.mark.unit
    def test_missing_work_modes(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=False,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.ready is False
        assert result.missing == (LABEL_WORK_MODE,)
        assert LABEL_WORK_MODE in result.reason

    @pytest.mark.unit
    def test_missing_locations(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=True,
            has_locations=False,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.ready is False
        assert result.missing == (LABEL_LOCATIONS,)
        assert LABEL_LOCATIONS in result.reason

    @pytest.mark.unit
    def test_missing_salary_floor(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=True,
            has_locations=True,
            has_salary_floor=False,
            has_keywords=True,
            has_resume=True,
        )
        assert result.ready is False
        assert result.missing == (LABEL_SALARY_FLOOR,)
        assert LABEL_SALARY_FLOOR in result.reason

    @pytest.mark.unit
    def test_missing_keywords(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=True,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=False,
            has_resume=True,
        )
        assert result.ready is False
        assert result.missing == (LABEL_KEY_SKILLS,)
        assert LABEL_KEY_SKILLS in result.reason

    @pytest.mark.unit
    def test_missing_resume(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=True,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=False,
        )
        assert result.ready is False
        assert result.missing == (LABEL_RESUME,)
        assert LABEL_RESUME in result.reason

    # --- multiple missing fields ---

    @pytest.mark.unit
    def test_multiple_missing(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=False,
            has_work_modes=True,
            has_locations=False,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=False,
        )
        assert result.ready is False
        assert result.missing == (LABEL_TARGET_ROLES, LABEL_LOCATIONS, LABEL_RESUME)
        assert LABEL_TARGET_ROLES in result.reason
        assert LABEL_LOCATIONS in result.reason
        assert LABEL_RESUME in result.reason

    @pytest.mark.unit
    def test_all_missing(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=False,
            has_work_modes=False,
            has_locations=False,
            has_salary_floor=False,
            has_keywords=False,
            has_resume=False,
        )
        assert result.ready is False
        assert result.missing == (
            LABEL_TARGET_ROLES,
            LABEL_WORK_MODE,
            LABEL_LOCATIONS,
            LABEL_SALARY_FLOOR,
            LABEL_KEY_SKILLS,
            LABEL_RESUME,
        )
        assert LABEL_RESUME in result.reason

    # --- edge: missing is ordered by definition order ---

    @pytest.mark.unit
    def test_missing_order_preserved(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=False,
            has_work_modes=False,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.missing == (LABEL_TARGET_ROLES, LABEL_WORK_MODE)
    
    @pytest.mark.unit
    def test_first_false_is_first_in_missing(self) -> None:
        result = evaluate_apply_readiness(
            has_titles=True,
            has_work_modes=False,
            has_locations=True,
            has_salary_floor=True,
            has_keywords=True,
            has_resume=True,
        )
        assert result.missing[0] == LABEL_WORK_MODE
