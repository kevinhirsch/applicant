"""Tests for applicant.core.errors — all domain exception classes."""

from __future__ import annotations

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


class TestDomainError:
    """Tests for the base DomainError class."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        """Clean-state fixture for safe parallel xdist execution."""
        pass

    @pytest.mark.unit
    def test_is_exception(self) -> None:
        err = DomainError()
        assert isinstance(err, Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        err = DomainError()
        assert str(err) == ""

    @pytest.mark.unit
    def test_custom_message(self) -> None:
        err = DomainError("custom")
        assert str(err) == "custom"


class TestIllegalStateTransition:
    """Tests for IllegalStateTransition — has custom __init__(self, frm, to)."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        err = IllegalStateTransition("draft", "submitted")
        assert isinstance(err, DomainError)
        assert isinstance(err, Exception)

    @pytest.mark.unit
    def test_attributes(self) -> None:
        err = IllegalStateTransition("draft", "submitted")
        assert err.frm == "draft"
        assert err.to == "submitted"

    @pytest.mark.unit
    def test_string_representation(self) -> None:
        err = IllegalStateTransition("draft", "submitted")
        assert "draft" in str(err)
        assert "submitted" in str(err)
        assert "->" in str(err)

    @pytest.mark.unit
    def test_non_string_args(self) -> None:
        err = IllegalStateTransition(None, 42)
        assert err.frm is None
        assert err.to == 42


class TestTruthfulnessViolation:
    """Tests for TruthfulnessViolation — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        err = TruthfulnessViolation()
        assert isinstance(err, DomainError)
        assert isinstance(err, Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        err = TruthfulnessViolation()
        assert str(err) == ""

    @pytest.mark.unit
    def test_custom_message(self) -> None:
        err = TruthfulnessViolation("fabrication detected")
        assert str(err) == "fabrication detected"


class TestSensitiveFieldViolation:
    """Tests for SensitiveFieldViolation — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(SensitiveFieldViolation(), DomainError)
        assert isinstance(SensitiveFieldViolation(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(SensitiveFieldViolation()) == ""


class TestConfirmationRequired:
    """Tests for ConfirmationRequired — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(ConfirmationRequired(), DomainError)
        assert isinstance(ConfirmationRequired(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(ConfirmationRequired()) == ""


class TestReviewRequired:
    """Tests for ReviewRequired — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(ReviewRequired(), DomainError)
        assert isinstance(ReviewRequired(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(ReviewRequired()) == ""


class TestPrefillBoundaryViolation:
    """Tests for PrefillBoundaryViolation — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(PrefillBoundaryViolation(), DomainError)
        assert isinstance(PrefillBoundaryViolation(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(PrefillBoundaryViolation()) == ""


class TestNativeFilePickerRequired:
    """Tests for NativeFilePickerRequired — has custom __init__(self, message, *, file_path)."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        err = NativeFilePickerRequired()
        assert isinstance(err, DomainError)
        assert isinstance(err, Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        err = NativeFilePickerRequired()
        assert "native OS" in str(err).lower() or "native" in str(err).lower()

    @pytest.mark.unit
    def test_custom_message(self) -> None:
        err = NativeFilePickerRequired("custom picker msg")
        assert str(err) == "custom picker msg"

    @pytest.mark.unit
    def test_file_path_attribute(self) -> None:
        err = NativeFilePickerRequired(file_path="/tmp/resume.pdf")
        assert err.file_path == "/tmp/resume.pdf"

    @pytest.mark.unit
    def test_file_path_default_none(self) -> None:
        err = NativeFilePickerRequired()
        assert err.file_path is None

    @pytest.mark.unit
    def test_message_and_file_path(self) -> None:
        err = NativeFilePickerRequired("msg", file_path="/a/b")
        assert str(err) == "msg"
        assert err.file_path == "/a/b"


class TestComputerUseBlocked:
    """Tests for ComputerUseBlocked — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(ComputerUseBlocked(), DomainError)
        assert isinstance(ComputerUseBlocked(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(ComputerUseBlocked()) == ""


class TestMemoryPolicyViolation:
    """Tests for MemoryPolicyViolation — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(MemoryPolicyViolation(), DomainError)
        assert isinstance(MemoryPolicyViolation(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(MemoryPolicyViolation()) == ""


class TestOnboardingIncomplete:
    """Tests for OnboardingIncomplete — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(OnboardingIncomplete(), DomainError)
        assert isinstance(OnboardingIncomplete(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(OnboardingIncomplete()) == ""


class TestLLMNotConfigured:
    """Tests for LLMNotConfigured — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(LLMNotConfigured(), DomainError)
        assert isinstance(LLMNotConfigured(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(LLMNotConfigured()) == ""


class TestNotFound:
    """Tests for NotFound — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(NotFound(), DomainError)
        assert isinstance(NotFound(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(NotFound()) == ""

    @pytest.mark.unit
    def test_with_message(self) -> None:
        err = NotFound("campaign not found")
        assert str(err) == "campaign not found"


class TestInvalidInput:
    """Tests for InvalidInput — no custom __init__."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        assert isinstance(InvalidInput(), DomainError)
        assert isinstance(InvalidInput(), Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        assert str(InvalidInput()) == ""

    @pytest.mark.unit
    def test_with_message(self) -> None:
        err = InvalidInput("bad kind value")
        assert str(err) == "bad kind value"


class TestCredentialDecryptError:
    """Tests for CredentialDecryptError — has custom __init__(self, message, *, campaign_id, tenant_key)."""

    @pytest.fixture(autouse=True)
    def _passthrough(self) -> None:
        pass

    @pytest.mark.unit
    def test_inheritance(self) -> None:
        err = CredentialDecryptError()
        assert isinstance(err, DomainError)
        assert isinstance(err, ValueError)
        assert isinstance(err, Exception)

    @pytest.mark.unit
    def test_default_message(self) -> None:
        err = CredentialDecryptError()
        assert "decrypt" in str(err).lower()

    @pytest.mark.unit
    def test_custom_message(self) -> None:
        err = CredentialDecryptError("key mismatch")
        assert str(err) == "key mismatch"

    @pytest.mark.unit
    def test_campaign_id_attribute(self) -> None:
        err = CredentialDecryptError(campaign_id="camp-123")
        assert err.campaign_id == "camp-123"

    @pytest.mark.unit
    def test_tenant_key_attribute(self) -> None:
        err = CredentialDecryptError(tenant_key="tenant-prod")
        assert err.tenant_key == "tenant-prod"

    @pytest.mark.unit
    def test_both_metadata(self) -> None:
        err = CredentialDecryptError(
            "msg", campaign_id="camp-42", tenant_key="tenant-staging"
        )
        assert str(err) == "msg"
        assert err.campaign_id == "camp-42"
        assert err.tenant_key == "tenant-staging"

    @pytest.mark.unit
    def test_default_none(self) -> None:
        err = CredentialDecryptError()
        assert err.campaign_id is None
        assert err.tenant_key is None
