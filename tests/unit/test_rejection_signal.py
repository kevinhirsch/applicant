import pytest
from dataclasses import FrozenInstanceError

from applicant.core.entities.rejection_signal import RejectionSignal, RejectionSource
from applicant.core.ids import ApplicationId, RejectionSignalId


@pytest.fixture(autouse=True)
def _no_state():
    """No-op fixture for xdist parallel safety."""
    pass


@pytest.mark.unit
class TestRejectionSource:
    """RejectionSource enum values and str behavior."""

    def test_enum_values(self):
        assert RejectionSource.EMAIL.value == "email"
        assert RejectionSource.ATS_STATUS.value == "ats_status"
        assert RejectionSource.MANUAL.value == "manual"

    def test_enum_is_str_enum(self):
        assert issubclass(RejectionSource, str)



@pytest.mark.unit
class TestRejectionSignalConstruction:
    """RejectionSignal minimal and full construction."""

    def test_minimal_construction(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-1"),
            application_id=ApplicationId("app-1"),
            source=RejectionSource.EMAIL,
        )
        assert signal.id == "sig-1"
        assert signal.application_id == "app-1"
        assert signal.source == RejectionSource.EMAIL
        assert signal.signal_text == ""
        assert signal.confidence == 1.0
        assert signal.detail == {}
        assert signal.detected_at is not None

    def test_full_construction(self):
        from datetime import UTC, datetime

        dt = datetime.now(UTC)
        signal = RejectionSignal(
            id=RejectionSignalId("sig-2"),
            application_id=ApplicationId("app-2"),
            source=RejectionSource.ATS_STATUS,
            signal_text="Status changed to rejected",
            confidence=0.85,
            detail={"reason": "overqualified"},
            detected_at=dt,
        )
        assert signal.id == "sig-2"
        assert signal.application_id == "app-2"
        assert signal.source == RejectionSource.ATS_STATUS
        assert signal.signal_text == "Status changed to rejected"
        assert signal.confidence == 0.85
        assert signal.detail == {"reason": "overqualified"}
        assert signal.detected_at == dt

    def test_non_default_signal_text(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-3"),
            application_id=ApplicationId("app-3"),
            source=RejectionSource.MANUAL,
            signal_text="Manual rejection entry",
        )
        assert signal.signal_text == "Manual rejection entry"

    def test_non_default_confidence(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-4"),
            application_id=ApplicationId("app-4"),
            source=RejectionSource.EMAIL,
            confidence=0.5,
        )
        assert signal.confidence == 0.5

    def test_non_default_detail(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-5"),
            application_id=ApplicationId("app-5"),
            source=RejectionSource.ATS_STATUS,
            detail={"source_url": "https://example.com"},
        )
        assert signal.detail == {"source_url": "https://example.com"}


@pytest.mark.unit
class TestRejectionSignalImmutability:
    """Frozen dataclass rejects attribute assignment."""

    def test_cannot_set_id(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-6"),
            application_id=ApplicationId("app-6"),
            source=RejectionSource.MANUAL,
        )
        with pytest.raises(FrozenInstanceError):
            signal.id = RejectionSignalId("other")  # type: ignore[misc]

    def test_cannot_set_signal_text(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-7"),
            application_id=ApplicationId("app-7"),
            source=RejectionSource.EMAIL,
        )
        with pytest.raises(FrozenInstanceError):
            signal.signal_text = "changed"  # type: ignore[misc]

    def test_cannot_set_confidence(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-8"),
            application_id=ApplicationId("app-8"),
            source=RejectionSource.ATS_STATUS,
        )
        with pytest.raises(FrozenInstanceError):
            signal.confidence = 0.0  # type: ignore[misc]

    def test_cannot_set_detail(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-9"),
            application_id=ApplicationId("app-9"),
            source=RejectionSource.MANUAL,
        )
        with pytest.raises(FrozenInstanceError):
            signal.detail = {"new": "value"}  # type: ignore[misc]

    def test_cannot_set_detected_at(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-10"),
            application_id=ApplicationId("app-10"),
            source=RejectionSource.EMAIL,
        )
        with pytest.raises(FrozenInstanceError):
            signal.detected_at = None  # type: ignore[misc]


@pytest.mark.unit
class TestRejectionSignalEquality:
    """Equal field values produce equal instances."""

    def test_equal_instances(self):
        from datetime import UTC, datetime

        dt = datetime.now(UTC)
        a = RejectionSignal(
            id=RejectionSignalId("sig-13"),
            application_id=ApplicationId("app-13"),
            source=RejectionSource.MANUAL,
            detected_at=dt,
        )
        b = RejectionSignal(
            id=RejectionSignalId("sig-13"),
            application_id=ApplicationId("app-13"),
            source=RejectionSource.MANUAL,
            detected_at=dt,
        )
        assert a == b

    def test_unequal_instances(self):
        from datetime import UTC, datetime

        dt = datetime.now(UTC)
        a = RejectionSignal(
            id=RejectionSignalId("sig-14"),
            application_id=ApplicationId("app-14"),
            source=RejectionSource.EMAIL,
            detected_at=dt,
        )
        b = RejectionSignal(
            id=RejectionSignalId("sig-15"),
            application_id=ApplicationId("app-15"),
            source=RejectionSource.EMAIL,
            detected_at=dt,
        )
        assert a != b


@pytest.mark.unit
class TestRejectionSignalDetectedAt:
    """detected_at defaults to current UTC time."""

    def test_default_is_datetime(self):
        signal = RejectionSignal(
            id=RejectionSignalId("sig-16"),
            application_id=ApplicationId("app-16"),
            source=RejectionSource.EMAIL,
        )
        assert hasattr(signal.detected_at, "tzinfo")

    def test_default_is_utc(self):
        from datetime import timezone

        signal = RejectionSignal(
            id=RejectionSignalId("sig-17"),
            application_id=ApplicationId("app-17"),
            source=RejectionSource.ATS_STATUS,
        )
        assert signal.detected_at.tzinfo == timezone.utc or str(signal.detected_at.tzinfo) == "UTC"
