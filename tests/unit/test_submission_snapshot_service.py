import pytest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

from applicant.application.services.submission_snapshot_service import (
    SubmissionSnapshotService,
)
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import ApplicationId, SubmissionSnapshotId


@pytest.fixture(autouse=True)
def _no_cache():
    """xdist parallel-safety: no global caches to clear."""
    pass


class TestSnapshotServiceFallbackMode:
    """record/get round-trip through the in-process fallback dict."""

    def test_record_returns_snapshot(self):
        svc = SubmissionSnapshotService()
        snapshot = svc.record(application_id="app-1", answers={"q1": "yes"})
        assert isinstance(snapshot, SubmissionSnapshot)
        assert isinstance(snapshot.id, str)
        assert snapshot.application_id == "app-1"

    def test_get_returns_recorded_snapshot(self):
        svc = SubmissionSnapshotService()
        recorded = svc.record(application_id="app-42")
        retrieved = svc.get("app-42")
        assert retrieved is not None
        assert retrieved.id == recorded.id
        assert retrieved.application_id == "app-42"

    def test_get_missing_returns_none(self):
        svc = SubmissionSnapshotService()
        assert svc.get("nonexistent") is None

    def test_round_trip_fields_preserved(self):
        svc = SubmissionSnapshotService()
        recorded = svc.record(
            application_id="app-7",
            answers={"q1": "a", "q2": "b"},
            material_versions={"resume": "v3", "cover": "v1"},
            posting_url="https://example.com/jobs/123",
        )
        retrieved = svc.get("app-7")
        assert retrieved.answers == {"q1": "a", "q2": "b"}
        assert retrieved.material_versions == {"resume": "v3", "cover": "v1"}
        assert retrieved.posting_url == "https://example.com/jobs/123"
        assert isinstance(retrieved.captured_at, datetime)
        assert retrieved.captured_at.tzinfo == UTC

    def test_empty_fields_default_to_expected(self):
        svc = SubmissionSnapshotService()
        snapshot = svc.record(application_id="app-0")
        assert snapshot.answers == {}
        assert snapshot.material_versions == {}
        assert snapshot.posting_url == ""


class TestSnapshotServiceWithStorage:
    """record/get through an explicit storage object."""

    def test_record_and_get_via_storage(self):
        snapshots: dict[str, SubmissionSnapshot] = {}

        class FakeRepo:
            def add(self, snapshot: SubmissionSnapshot) -> None:
                snapshots[str(snapshot.application_id)] = snapshot

            def get_for_application(self, application_id: ApplicationId) -> SubmissionSnapshot | None:
                return snapshots.get(str(application_id))

        class FakeStorage:
            submission_snapshots = FakeRepo()

        svc = SubmissionSnapshotService(storage=FakeStorage())
        recorded = svc.record(
            application_id="app-s1",
            answers={"city": "Berlin"},
            material_versions={"cv": "final"},
            posting_url="https://example.com/job/456",
        )
        retrieved = svc.get("app-s1")
        assert retrieved is not None
        assert retrieved.id == recorded.id
        assert retrieved.application_id == "app-s1"
        assert retrieved.answers == {"city": "Berlin"}
        assert retrieved.material_versions == {"cv": "final"}
        assert retrieved.posting_url == "https://example.com/job/456"

    def test_storage_mode_get_missing_returns_none(self):
        class FakeRepo:
            def add(self, snapshot: SubmissionSnapshot) -> None:
                pass

            def get_for_application(self, application_id: ApplicationId) -> SubmissionSnapshot | None:
                return None

        svc = SubmissionSnapshotService(storage=type("S", (), {"submission_snapshots": FakeRepo()})())
        assert svc.get("ghost") is None

    def test_storage_and_fallback_are_independent(self):
        """record in storage mode does not write to the fallback dict."""
        stored: dict[str, SubmissionSnapshot] = {}

        class FakeRepo:
            def add(self, snapshot: SubmissionSnapshot) -> None:
                stored[str(snapshot.application_id)] = snapshot

            def get_for_application(self, application_id: ApplicationId) -> SubmissionSnapshot | None:
                return stored.get(str(application_id))

        svc = SubmissionSnapshotService(storage=type("S", (), {"submission_snapshots": FakeRepo()})())
        svc.record(application_id="app-indep")
        assert svc.get("app-indep") is not None  # goes to storage
        # fallback is empty for this id
        assert svc._fallback.get("app-indep") is None


class TestSnapshotFrozen:
    """SubmissionSnapshot is a frozen dataclass."""

    def test_mutation_raises_frozen_error(self):
        svc = SubmissionSnapshotService()
        snapshot = svc.record(application_id="app-freeze", answers={"k": "v"})
        with pytest.raises(FrozenInstanceError):
            snapshot.answers = {"new": "value"}

    def test_timestamp_property(self):
        svc = SubmissionSnapshotService()
        snapshot = svc.record(application_id="app-ts")
        assert snapshot.timestamp == snapshot.captured_at
        assert isinstance(snapshot.timestamp, datetime)

    def test_stage_defaults_to_submitted(self):
        svc = SubmissionSnapshotService()
        snapshot = svc.record(application_id="app-stage")
        assert snapshot.stage == "submitted"


class TestIdsAreHashable:
    """NewType(str) ids are hashable for set membership."""

    def test_application_id_is_hashable(self):
        ids = {ApplicationId("a1"), ApplicationId("a2")}
        assert ApplicationId("a1") in ids

    def test_submission_snapshot_id_is_hashable(self):
        ids = {SubmissionSnapshotId("s1"), SubmissionSnapshotId("s2")}
        assert SubmissionSnapshotId("s1") in ids


class TestSnapshotServiceMultiApp:
    """Multiple apps are independent."""

    def test_concurrent_apps_dont_interfere(self):
        svc = SubmissionSnapshotService()
        snap1 = svc.record(application_id="app-alpha", answers={"q": "a"})
        snap2 = svc.record(application_id="app-beta", answers={"q": "b"})
        assert svc.get("app-alpha").id == snap1.id
        assert svc.get("app-beta").id == snap2.id
        assert svc.get("app-alpha").answers == {"q": "a"}
        assert svc.get("app-beta").answers == {"q": "b"}

    def test_record_overwrites_same_app(self):
        """Fallback mode: recording twice for the same app overwrites."""
        svc = SubmissionSnapshotService()
        svc.record(application_id="app-dup", answers={"q": "first"})
        svc.record(application_id="app-dup", answers={"q": "second"})
        assert svc.get("app-dup").answers == {"q": "second"}
