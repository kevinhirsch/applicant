import pytest

from applicant.core.rules.discovery_gate import (
    DiscoveryNotReady,
    has_any_criterion,
    require_criteria_before_discovery,
)


# ---------------------------------------------------------------------------
# autouse fixture for xdist parallel safety (module is stateless)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    yield


# ---------------------------------------------------------------------------
# has_any_criterion
# ---------------------------------------------------------------------------

class TestHasAnyCriterion:
    """has_any_criterion returns True only when criteria carries at least one
    concrete search signal."""

    def test_none(self) -> None:
        assert has_any_criterion(None) is False

    def test_empty_object_no_attrs(self) -> None:
        """An object with none of the expected attributes is treated as empty."""
        assert has_any_criterion(object()) is False

    def test_empty_object_all_empty_attrs(self) -> None:
        class EmptyCriteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        assert has_any_criterion(EmptyCriteria()) is False

    def test_human_readable_with_text(self) -> None:
        class Criteria:
            human_readable = "looking for a senior role"
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None

        assert has_any_criterion(Criteria()) is True

    def test_human_readable_with_whitespace_only(self) -> None:
        """Whitespace-only human_readable should not count as a signal."""
        class Criteria:
            human_readable = "   "
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None

        assert has_any_criterion(Criteria()) is False

    def test_human_readable_empty_string(self) -> None:
        class Criteria:
            human_readable = ""
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None

        assert has_any_criterion(Criteria()) is False

    @pytest.mark.parametrize("attr", ["titles", "locations", "work_modes", "keywords"])
    def test_with_one_non_empty_list_attr(self, attr: str) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        setattr(Criteria, attr, ["some-value"])
        assert has_any_criterion(Criteria()) is True

    @pytest.mark.parametrize("attr", ["titles", "locations", "work_modes", "keywords"])
    def test_empty_tuple_attr(self, attr: str) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        setattr(Criteria, attr, ())
        assert has_any_criterion(Criteria()) is False

    @pytest.mark.parametrize("attr", ["titles", "locations", "work_modes", "keywords"])
    def test_empty_list_attr(self, attr: str) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        setattr(Criteria, attr, [])
        assert has_any_criterion(Criteria()) is False

    def test_salary_floor_not_none(self) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = 50000
            human_readable = ""

        assert has_any_criterion(Criteria()) is True

    def test_salary_floor_zero(self) -> None:
        """0 is not None, so it counts as a concrete signal."""
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = 0
            human_readable = ""

        assert has_any_criterion(Criteria()) is True

    def test_salary_floor_none(self) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        assert has_any_criterion(Criteria()) is False

    def test_attribute_missing(self) -> None:
        """An object missing the expected attributes defaults to empty via getattr."""
        class PartialCriteria:
            pass

        assert has_any_criterion(PartialCriteria()) is False


# ---------------------------------------------------------------------------
# require_criteria_before_discovery
# ---------------------------------------------------------------------------

class TestRequireCriteriaBeforeDiscovery:
    def test_raises_for_none(self) -> None:
        with pytest.raises(DiscoveryNotReady) as excinfo:
            require_criteria_before_discovery(None)
        assert "at least one search criterion" in str(excinfo.value)

    def test_raises_for_empty_criteria(self) -> None:
        class EmptyCriteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        with pytest.raises(DiscoveryNotReady) as excinfo:
            require_criteria_before_discovery(EmptyCriteria())
        assert "at least one search criterion" in str(excinfo.value)

    def test_passes_with_titles(self) -> None:
        class Criteria:
            titles = ["Engineer"]
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = ""

        require_criteria_before_discovery(Criteria())

    def test_passes_with_human_readable(self) -> None:
        class Criteria:
            titles = ()
            locations = ()
            work_modes = ()
            keywords = ()
            salary_floor = None
            human_readable = "senior dev"

        require_criteria_before_discovery(Criteria())


# ---------------------------------------------------------------------------
# DiscoveryNotReady exception
# ---------------------------------------------------------------------------

class TestDiscoveryNotReady:
    def test_is_runtime_error(self) -> None:
        assert issubclass(DiscoveryNotReady, RuntimeError)

    def test_default_message(self) -> None:
        err = DiscoveryNotReady()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        msg = "Discovery needs criteria first."
        err = DiscoveryNotReady(msg)
        assert str(err) == msg
