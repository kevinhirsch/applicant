"""Unit tests for prefill_boundary rule (FR-PREFILL-4)."""

import pytest

from applicant.core.errors import PrefillBoundaryViolation
from applicant.core.rules.prefill_boundary import (
    StepKind,
    is_irreducible_human_step,
    ensure_action_allowed,
)


@pytest.fixture(autouse=True)
def _xdist_isolation() -> None:
    """No shared module state, but required for parallel xdist safety."""
    yield


class TestStepKind:
    """StepKind enumeration values."""

    def test_members_and_values(self) -> None:
        assert StepKind.FILL_FIELD.value == "fill_field"
        assert StepKind.UPLOAD_DOCUMENT.value == "upload_document"
        assert StepKind.NAVIGATE.value == "navigate"
        assert StepKind.SCREENSHOT.value == "screenshot"
        assert StepKind.ACCOUNT_CREATE_SUBMIT.value == "account_create_submit"
        assert StepKind.CAPTCHA.value == "captcha"
        assert StepKind.EMAIL_VERIFY.value == "email_verify"
        assert StepKind.SMS_VERIFY.value == "sms_verify"
        assert StepKind.FINAL_SUBMIT.value == "final_submit"

    def test_is_str_enum(self) -> None:
        assert issubclass(StepKind, str)


class TestIsIrreducibleHumanStep:
    """is_irreducible_human_step identifies unconditionally irreducible steps."""

    @pytest.mark.parametrize(
        "step",
        [
            StepKind.CAPTCHA,
            StepKind.EMAIL_VERIFY,
            StepKind.SMS_VERIFY,
        ],
    )
    def test_irreducible_steps(self, step: StepKind) -> None:
        assert is_irreducible_human_step(step) is True

    @pytest.mark.parametrize(
        "step",
        [
            StepKind.FILL_FIELD,
            StepKind.UPLOAD_DOCUMENT,
            StepKind.NAVIGATE,
            StepKind.SCREENSHOT,
            StepKind.ACCOUNT_CREATE_SUBMIT,
            StepKind.FINAL_SUBMIT,
        ],
    )
    def test_non_irreducible_steps(self, step: StepKind) -> None:
        assert is_irreducible_human_step(step) is False


class TestEnsureActionAllowed:
    """ensure_action_allowed raises PrefillBoundaryViolation for disallowed steps."""

    def test_irreducible_step_always_raises(self) -> None:
        with pytest.raises(PrefillBoundaryViolation) as exc:
            ensure_action_allowed(StepKind.CAPTCHA)
        assert "irreducible human step" in str(exc.value).lower()

    def test_irreducible_step_raises_even_with_flags(self) -> None:
        with pytest.raises(PrefillBoundaryViolation):
            ensure_action_allowed(
                StepKind.EMAIL_VERIFY,
                engine_submit_authorized=True,
                automated_accounts_enabled=True,
            )

    def test_account_create_submit_raises_when_not_enabled(self) -> None:
        with pytest.raises(PrefillBoundaryViolation) as exc:
            ensure_action_allowed(StepKind.ACCOUNT_CREATE_SUBMIT)
        assert "account creation is not enabled" in str(exc.value).lower()

    def test_account_create_submit_allowed_when_enabled(self) -> None:
        ensure_action_allowed(
            StepKind.ACCOUNT_CREATE_SUBMIT,
            automated_accounts_enabled=True,
        )

    def test_final_submit_raises_without_authorization(self) -> None:
        with pytest.raises(PrefillBoundaryViolation) as exc:
            ensure_action_allowed(StepKind.FINAL_SUBMIT)
        assert "final submit requires" in str(exc.value).lower()

    def test_final_submit_allowed_when_authorized(self) -> None:
        ensure_action_allowed(
            StepKind.FINAL_SUBMIT,
            engine_submit_authorized=True,
        )

    def test_fill_field_allowed_by_default(self) -> None:
        ensure_action_allowed(StepKind.FILL_FIELD)

    def test_upload_document_allowed_by_default(self) -> None:
        ensure_action_allowed(StepKind.UPLOAD_DOCUMENT)

    def test_navigate_allowed_by_default(self) -> None:
        ensure_action_allowed(StepKind.NAVIGATE)

    def test_screenshot_allowed_by_default(self) -> None:
        ensure_action_allowed(StepKind.SCREENSHOT)
