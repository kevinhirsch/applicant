from __future__ import annotations
from dataclasses import dataclass, field
from datetime import UTC, datetime
from applicant.core.ids import ApplicationId, SubmissionSnapshotId

@dataclass(frozen=True)
class SubmissionSnapshot:
    id: SubmissionSnapshotId
    application_id: ApplicationId
    answers: dict = field(default_factory=dict)
    materials: list[dict] = field(default_factory=list)
    ats_metadata: dict = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
