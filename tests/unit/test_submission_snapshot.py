"""Tests for the SubmissionSnapshot frozen dataclass."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from applicant.core.entities.submission_snapshot import (
    STAGE_REVIEWED,
    STAGE_SUBMITTED,
    SubmissionSnapshot,
)
from applicant.core.ids import ApplicationId, SubmissionSnapshotId


@pytest.fixture(autouse=True)
def _reset():
    """Reset any module-level state for xdist safety."""
    pass


@pytest.mark.unit
class TestSubmissionSnapshot:
    """Tests for the SubmissionSnapshot frozen dataclass."""

    def test_default_construction(self) -> None:
        """Minimal construction with only required fields."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(id=snapshot_id, application_id=app_id)

        assert snap.id == snapshot_id
        assert snap.application_id == app_id
        assert snap.answers == {}
        assert snap.materials == []
        assert snap.ats_metadata == {}
        assert snap.material_versions == {}
        assert snap.posting_url == ""
        assert isinstance(snap.captured_at, datetime)

    def test_all_fields_construction(self) -> None:
        """Construction with all fields explicitly provided."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        answers = {"q1": "yes", "q2": "no"}
        materials = [{"name": "resume.pdf"}]
        ats_metadata = {"version": "1.0"}
        material_versions = {"resume.pdf": 2}
        posting_url = "https://jobs.example.com/apply/123"
        captured_at = datetime.now(UTC)

        snap = SubmissionSnapshot(
            id=snapshot_id,
            application_id=app_id,
            answers=answers,
            materials=materials,
            ats_metadata=ats_metadata,
            material_versions=material_versions,
            posting_url=posting_url,
            captured_at=captured_at,
        )

        assert snap.id == snapshot_id
        assert snap.application_id == app_id
        assert snap.answers == answers
        assert snap.materials == materials
        assert snap.ats_metadata == ats_metadata
        assert snap.material_versions == material_versions
        assert snap.posting_url == posting_url
        assert snap.captured_at == captured_at

    def test_frozen_immutability(self) -> None:
        """Frozen dataclass raises FrozenInstanceError on attribute set."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(id=snapshot_id, application_id=app_id)

        with pytest.raises(FrozenInstanceError):
            snap.posting_url = "https://evil.com/"

    def test_timestamp_property(self) -> None:
        """timestamp property aliases captured_at."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(id=snapshot_id, application_id=app_id)

        assert snap.timestamp == snap.captured_at

    def test_stage_defaults_to_submitted(self) -> None:
        """stage defaults to STAGE_SUBMITTED when ats_metadata has no stage."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(id=snapshot_id, application_id=app_id)

        assert snap.stage == STAGE_SUBMITTED

    def test_stage_reviewed_from_ats_metadata(self) -> None:
        """stage is STAGE_REVIEWED when ats_metadata has stage='reviewed'."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(
            id=snapshot_id,
            application_id=app_id,
            ats_metadata={"stage": "reviewed"},
        )

        assert snap.stage == STAGE_REVIEWED

    def test_posting_url_round_trip(self) -> None:
        """posting_url round-trips through construction and access."""
        url = "https://boards.greenhouse.io/smartrecruiters/jobs/456"
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(
            id=snapshot_id,
            application_id=app_id,
            posting_url=url,
        )

        assert snap.posting_url == url

    def test_captured_at_is_utc_now(self) -> None:
        """Default captured_at is a UTC datetime near now."""
        before = datetime.now(UTC)
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        snap = SubmissionSnapshot(id=snapshot_id, application_id=app_id)
        after = datetime.now(UTC)

        assert before <= snap.captured_at <= after

    def test_equality_via_id(self) -> None:
        """Two snapshots with the same id are equal; different ids are not."""
        snapshot_id = SubmissionSnapshotId(uuid4().hex)
        app_id = ApplicationId(uuid4().hex)
        captured_at = datetime.now(UTC)
        snap1 = SubmissionSnapshot(
            id=snapshot_id, application_id=app_id, captured_at=captured_at
        )
        snap2 = SubmissionSnapshot(
            id=snapshot_id, application_id=app_id, captured_at=captured_at
        )

        assert snap1 == snap2

        other_id = SubmissionSnapshotId(uuid4().hex)
        snap3 = SubmissionSnapshot(
            id=other_id, application_id=app_id, captured_at=captured_at
        )

        assert snap1 != snap3
