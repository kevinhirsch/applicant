import pytest

from applicant.core.errors import ConfirmationRequired
from applicant.core.rules.confirmation_gate import (
    ensure_change_allowed,
    requires_confirmation,
)


@pytest.fixture(autouse=True)
def _no_cache():
    """Parallel-safe isolation fixture (xdist)."""
    pass


class TestRequiresConfirmation:
    @pytest.mark.unit
    def test_integral_true(self):
        assert requires_confirmation(True) is True

    @pytest.mark.unit
    def test_integral_false(self):
        assert requires_confirmation(False) is False

    @pytest.mark.unit
    def test_truthy_value(self):
        assert requires_confirmation(1) is True

    @pytest.mark.unit
    def test_falsy_value(self):
        assert requires_confirmation(0) is False


class TestEnsureChangeAllowed:
    @pytest.mark.unit
    def test_integral_confirmed(self):
        ensure_change_allowed(is_integral=True, user_confirmed=True)

    @pytest.mark.unit
    def test_integral_not_confirmed(self):
        with pytest.raises(ConfirmationRequired):
            ensure_change_allowed(is_integral=True, user_confirmed=False)

    @pytest.mark.unit
    def test_non_integral_no_confirm(self):
        ensure_change_allowed(is_integral=False, user_confirmed=False)

    @pytest.mark.unit
    def test_error_message(self):
        with pytest.raises(ConfirmationRequired) as exc_info:
            ensure_change_allowed(is_integral=True, user_confirmed=False)
        assert "Integral change requires explicit user confirmation before commit" in str(exc_info.value)
