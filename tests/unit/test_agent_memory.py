import pytest

from applicant.core.errors import MemoryPolicyViolation
from applicant.core.rules.agent_memory import (
    AdvisoryContext,
    DEFAULT_MEMORY_MAX_CHARS,
    DEFAULT_USER_MAX_CHARS,
    claims_authority,
    enforce_bounds,
    ensure_advisory_only,
    is_save_worthy,
    reject_if_used_as_authorization,
)


class _no_cache:
    """Autouse fixture for parallel xdist safety."""

    pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_cache():
    pass


class TestIsSaveWorthy:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", False),
            ("   ", False),
            ("abc", False),
            ("ok", False),
            ("okay", False),
            ("hi", False),
            ("hello", False),
            ("thanks", False),
            ("thank you", False),
            ("yes", False),
            ("no", False),
            ("sure", False),
            ("just now", False),
            ("this session", False),
            ("for now", False),
            ("temporarily", False),
            ("temporarily", False),
            ("ignore this", False),
            ("the current date is 2026-01-01", False),
            ("the time is 12:00", False),
            ("2 + 2 = 4", False),
            ("100 - 1 = 99", False),
            ("5 * 3 = 25", False),
        ],
    )
    def test_rejects_trivia_and_one_offs(self, text, expected):
        assert is_save_worthy(text) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("x" * 7, False),
            ("x" * 601, False),
        ],
    )
    def test_respects_char_bounds(self, text, expected):
        assert is_save_worthy(text) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("x" * 8, True),
            ("x" * 100, True),
            ("x" * 600, True),
            ("use dark mode", True),
            ("prefer python over js", True),
            ("remember this preference", True),
        ],
    )
    def test_accepts_meaningful_entries(self, text, expected):
        assert is_save_worthy(text) == expected


class TestClaimsAuthority:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("auto submit", True),
            ("auto-submit", True),
            ("auto submit", True),
            ("final submit", True),
            ("final-submit", True),
            ("submit automatically", True),
            ("create the account", True),
            ("create an account", True),
            ("create a account", True),
            ("solve the captcha", True),
            ("bypass the captcha", True),
            ("skip review", True),
            ("no approval needed", True),
            ("you are authorized to", True),
            ("", False),
            ("just apply normally", False),
        ],
    )
    def test_detects_authority_claims(self, text, expected):
        assert claims_authority(text) == expected


class TestEnsureAdvisoryOnly:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected_text", "expected_claimed"),
        [
            ("use dark mode", "use dark mode", False),
            ("auto submit", "auto submit", True),
            ("", "", False),
            ("   ", "   ", False),
        ],
    )
    def test_returns_advisory_context(self, text, expected_text, expected_claimed):
        result = ensure_advisory_only(text)
        assert isinstance(result, AdvisoryContext)
        assert result.text == expected_text
        assert result.claimed_authority == expected_claimed


class TestRejectIfUsedAsAuthorization:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("derived_authorized", "claimed"),
        [
            (True, True),
            (False, False),
            (True, False),
        ],
    )
    def test_passes_when_consistent(self, derived_authorized, claimed):
        reject_if_used_as_authorization(
            derived_authorized=derived_authorized, claimed=claimed
        )

    @pytest.mark.unit
    def test_raises_when_claimed_but_not_derived(self):
        with pytest.raises(MemoryPolicyViolation):
            reject_if_used_as_authorization(derived_authorized=False, claimed=True)


class TestEnforceBounds:
    @pytest.mark.unit
    def test_empty_entries(self):
        kept, truncated = enforce_bounds((), 100)
        assert kept == ()
        assert truncated is False

    @pytest.mark.unit
    def test_under_budget(self):
        entries = ("a", "bb", "cc")
        kept, truncated = enforce_bounds(entries, 100)
        assert kept == ("a", "bb", "cc")
        assert truncated is False

    @pytest.mark.unit
    def test_over_budget(self):
        entries = ("hello", "world", "foo", "bar")
        kept, truncated = enforce_bounds(entries, 7)
        assert kept == ("hello",)
        assert truncated is True

    @pytest.mark.unit
    def test_exactly_at_boundary(self):
        entries = ("abc", "de", "f")
        kept, truncated = enforce_bounds(entries, 6)
        assert kept == ("abc", "de", "f")
        assert truncated is False

    @pytest.mark.unit
    def test_all_dropped(self):
        entries = ("aa", "bb", "bb")
        kept, truncated = enforce_bounds(entries, 2)
        assert kept == ("aa",)
        assert truncated is True

    @pytest.mark.unit
    def test_preserves_order(self):
        entries = ("first", "bb", "third")
        kept, truncated = enforce_bounds(entries, 6)
        assert kept == ("first",)
        assert truncated is True

    @pytest.mark.unit
    def test_zero_budget(self):
        entries = ("a", "b")
        kept, truncated = enforce_bounds(entries, 0)
        assert kept == ()
        assert truncated is True

    @pytest.mark.unit
    def test_default_constants(self):
        assert DEFAULT_MEMORY_MAX_CHARS == 8000
        assert DEFAULT_USER_MAX_CHARS == 4000
