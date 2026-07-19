import pytest

from applicant.core.errors import (
    ComputerUseBlocked,
    ConfirmationRequired,
    CredentialDecryptError,
    DomainError,
    IllegalStateTransition,
    InvalidInput,
    LLMNotConfigured,
    MemoryPolicyViolation,
    NativeFilePickerRequired,
    NotFound,
    OnboardingIncomplete,
    PrefillBoundaryViolation,
    ReviewRequired,
    SensitiveFieldViolation,
    TruthfulnessViolation,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """No lru_cache in this module; fixture is a no-op for xdist safety."""


DOMAIN_ERROR_CLASSES = [
    ComputerUseBlocked,
    ConfirmationRequired,
    CredentialDecryptError,
    IllegalStateTransition,
    InvalidInput,
    LLMNotConfigured,
    MemoryPolicyViolation,
    NativeFilePickerRequired,
    NotFound,
    OnboardingIncomplete,
    PrefillBoundaryViolation,
    ReviewRequired,
    SensitiveFieldViolation,
    TruthfulnessViolation,
]


class TestDomainError:
    """Unit tests for pure-core domain errors (AZ0-77)."""

    @pytest.mark.parametrize("cls", DOMAIN_ERROR_CLASSES)
    def test_all_are_domain_error_subclasses(self, cls: type) -> None:
        """Every domain error inherits DomainError."""
        assert issubclass(cls, DomainError)
        assert issubclass(cls, Exception)

    def test_domain_error_base_itself(self) -> None:
        """DomainError is an Exception."""
        assert issubclass(DomainError, Exception)

    # --- classes without custom __init__ ---

    @pytest.mark.parametrize(
        "cls",
        [
            TruthfulnessViolation,
            SensitiveFieldViolation,
            ConfirmationRequired,
            ReviewRequired,
            PrefillBoundaryViolation,
            ComputerUseBlocked,
            MemoryPolicyViolation,
            OnboardingIncomplete,
            LLMNotConfigured,
            NotFound,
            InvalidInput,
        ],
    )
    def test_no_arg_classes_can_be_instantiated(self, cls: type) -> None:
        """Classes without custom __init__ accept no args."""
        err = cls()
        assert isinstance(err, cls)
        assert isinstance(err, DomainError)

    # --- IllegalStateTransition ---

    def test_illegal_state_transition_stores_frm_to(self) -> None:
        err = IllegalStateTransition("draft", "submitted")
        assert err.frm == "draft"
        assert err.to == "submitted"

    def test_illegal_state_transition_message(self) -> None:
        err = IllegalStateTransition("draft", "submitted")
        assert str(err) == "Illegal application state transition: draft -> submitted"

    # --- NativeFilePickerRequired ---

    def test_native_file_picker_required_default_message(self) -> None:
        err = NativeFilePickerRequired()
        assert str(err) == "A native OS file-picker requires desktop assist."

    def test_native_file_picker_required_custom_message(self) -> None:
        err = NativeFilePickerRequired("custom message")
        assert str(err) == "custom message"

    def test_native_file_picker_required_stores_file_path(self) -> None:
        err = NativeFilePickerRequired(file_path="/tmp/resume.pdf")
        assert err.file_path == "/tmp/resume.pdf"

    def test_native_file_picker_required_file_path_defaults_to_none(self) -> None:
        err = NativeFilePickerRequired()
        assert err.file_path is None

    # --- CredentialDecryptError ---

    def test_credential_decrypt_error_is_also_value_error(self) -> None:
        assert issubclass(CredentialDecryptError, ValueError)

    def test_credential_decrypt_error_default_message(self) -> None:
        err = CredentialDecryptError()
        assert str(err) == "A stored credential could not be decrypted (wrong master key)."

    def test_credential_decrypt_error_custom_message(self) -> None:
        err = CredentialDecryptError("bad key")
        assert str(err) == "bad key"

    def test_credential_decrypt_error_stores_campaign_tenant(self) -> None:
        err = CredentialDecryptError(campaign_id="camp-42", tenant_key="acme")
        assert err.campaign_id == "camp-42"
        assert err.tenant_key == "acme"

    def test_credential_decrypt_error_defaults_to_none(self) -> None:
        err = CredentialDecryptError()
        assert err.campaign_id is None
        assert err.tenant_key is None

