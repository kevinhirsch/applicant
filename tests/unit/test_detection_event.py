import pytest
from datetime import UTC, datetime

from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId, DetectionEventId


class TestDetectionEventDefaults:
    """DetectionEvent uses sensible defaults for all optional fields."""

    def test_minimal_construction(self):
        ev = DetectionEvent(
            id=DetectionEventId("det-1"),
            application_id=ApplicationId("app-1"),
            signal_type="captcha",
        )
        assert ev.id == "det-1"
        assert ev.application_id == "app-1"
        assert ev.signal_type == "captcha"
        assert ev.detail == {}

    def test_timestamp_defaults_to_now(self):
        before = datetime.now(UTC)
        ev = DetectionEvent(
            id=DetectionEventId("det-2"),
            application_id=ApplicationId("app-2"),
            signal_type="turnstile",
        )
        after = datetime.now(UTC)
        assert before <= ev.timestamp <= after

    def test_detail_is_independent_per_instance(self):
        ev1 = DetectionEvent(
            id=DetectionEventId("det-3"),
            application_id=ApplicationId("app-3"),
            signal_type="cloudflare",
        )
        ev2 = DetectionEvent(
            id=DetectionEventId("det-4"),
            application_id=ApplicationId("app-4"),
            signal_type="cloudflare",
        )
        assert ev1.detail is not ev2.detail


class TestDetectionEventCustomValues:
    """All fields accept custom values."""

    def test_full_construction(self):
        ev = DetectionEvent(
            id=DetectionEventId("det-5"),
            application_id=ApplicationId("app-5"),
            signal_type="429",
            detail={"url": "https://example.com", "status_code": 429},
            timestamp=datetime(2025, 6, 1, 8, 30, tzinfo=UTC),
        )
        assert ev.id == "det-5"
        assert ev.application_id == "app-5"
        assert ev.signal_type == "429"
        assert ev.detail == {"url": "https://example.com", "status_code": 429}
        assert ev.timestamp == datetime(2025, 6, 1, 8, 30, tzinfo=UTC)


class TestDetectionEventFrozen:
    """DetectionEvent is a frozen dataclass."""

    def test_cannot_modify_id(self):
        ev = DetectionEvent(
            id=DetectionEventId("det-6"),
            application_id=ApplicationId("app-6"),
            signal_type="captcha",
        )
        with pytest.raises(AttributeError):
            ev.id = DetectionEventId("det-7")

    def test_cannot_modify_signal_type(self):
        ev = DetectionEvent(
            id=DetectionEventId("det-7"),
            application_id=ApplicationId("app-7"),
            signal_type="captcha",
        )
        with pytest.raises(AttributeError):
            ev.signal_type = "turnstile"

    def test_cannot_modify_detail(self):
        ev = DetectionEvent(
            id=DetectionEventId("det-8"),
            application_id=ApplicationId("app-8"),
            signal_type="captcha",
        )
        with pytest.raises(AttributeError):
            ev.detail = {"url": "https://evil.com"}


class TestDetectionEventEquality:
    """DetectionEvent supports equality and inequality."""

    def test_equal_instances(self):
        ev1 = DetectionEvent(
            id=DetectionEventId("det-9"),
            application_id=ApplicationId("app-9"),
            signal_type="403",
            detail={"ip": "1.2.3.4"},
            timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        )
        ev2 = DetectionEvent(
            id=DetectionEventId("det-9"),
            application_id=ApplicationId("app-9"),
            signal_type="403",
            detail={"ip": "1.2.3.4"},
            timestamp=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        )
        assert ev1 == ev2

    def test_different_ids_are_not_equal(self):
        ev1 = DetectionEvent(
            id=DetectionEventId("det-10"),
            application_id=ApplicationId("app-10"),
            signal_type="captcha",
        )
        ev2 = DetectionEvent(
            id=DetectionEventId("det-11"),
            application_id=ApplicationId("app-10"),
            signal_type="captcha",
        )
        assert ev1 != ev2
