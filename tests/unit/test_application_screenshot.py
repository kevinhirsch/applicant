"""Unit tests for ApplicationScreenshot entity (FR-LOG-2)."""

from __future__ import annotations

import pytest

from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.ids import ApplicationId, ScreenshotId


@pytest.fixture(autouse=True)
def _no_state_leak():
    """No module-level state to clear; present for parallel xdist safety."""
    pass


class TestApplicationScreenshotDefaults:
    """ApplicationScreenshot uses sensible defaults for all optional fields."""

    def test_minimal_construction(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-1"),
            application_id=ApplicationId("app-1"),
            page_ref="/screenshots/careers-page.png",
        )
        assert shot.id == "ss-1"
        assert shot.application_id == "app-1"
        assert shot.page_ref == "/screenshots/careers-page.png"
        assert shot.page_url == ""

    def test_full_construction(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-2"),
            application_id=ApplicationId("app-2"),
            page_ref="blob://screenshots/shot2.png",
            page_url="https://example.com/careers",
        )
        assert shot.id == "ss-2"
        assert shot.application_id == "app-2"
        assert shot.page_ref == "blob://screenshots/shot2.png"
        assert shot.page_url == "https://example.com/careers"


class TestApplicationScreenshotFrozen:
    """ApplicationScreenshot is a frozen dataclass."""

    def test_cannot_modify_id(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-3"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        with pytest.raises(AttributeError):
            shot.id = ScreenshotId("ss-other")  # type: ignore[misc]

    def test_cannot_modify_application_id(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-4"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        with pytest.raises(AttributeError):
            shot.application_id = ApplicationId("app-other")  # type: ignore[misc]

    def test_cannot_modify_page_ref(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-5"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        with pytest.raises(AttributeError):
            shot.page_ref = "ref2"  # type: ignore[misc]

    def test_cannot_modify_page_url(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-6"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        with pytest.raises(AttributeError):
            shot.page_url = "https://other.com"  # type: ignore[misc]


class TestApplicationScreenshotEquality:
    """ApplicationScreenshot supports equality by field values."""

    def test_equal_instances(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
            page_url="https://example.com",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
            page_url="https://example.com",
        )
        assert a == b

    def test_not_equal_different_id(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-11"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        assert a != b

    def test_not_equal_different_application_id(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-2"),
            page_ref="ref1",
        )
        assert a != b

    def test_not_equal_different_page_ref(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref2",
        )
        assert a != b

    def test_not_equal_different_page_url(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
            page_url="https://example.com/a",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-10"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
            page_url="https://example.com/b",
        )
        assert a != b


class TestApplicationScreenshotHashable:
    """Frozen dataclass with all-hashable fields is hashable."""

    def test_can_be_used_in_set(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-20"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        s = {shot}
        assert shot in s

    def test_hash_equals_equal_instance_hash(self):
        a = ApplicationScreenshot(
            id=ScreenshotId("ss-20"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        b = ApplicationScreenshot(
            id=ScreenshotId("ss-20"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        assert hash(a) == hash(b)

    def test_can_be_used_as_dict_key(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-30"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
        )
        d = {shot: "found"}
        assert d[shot] == "found"


class TestApplicationScreenshotRepr:
    """__repr__ is provided by frozen dataclass."""

    def test_repr_contains_fields(self):
        shot = ApplicationScreenshot(
            id=ScreenshotId("ss-40"),
            application_id=ApplicationId("app-1"),
            page_ref="ref1",
            page_url="https://example.com",
        )
        r = repr(shot)
        assert "ApplicationScreenshot" in r
        assert "ss-40" in r
        assert "app-1" in r
        assert "ref1" in r
        assert "example.com" in r
