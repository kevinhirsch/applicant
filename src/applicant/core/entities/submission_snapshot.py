from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import ApplicationId, SubmissionSnapshotId

#: H3 (full-fidelity review) stage markers, carried inside ``ats_metadata`` so no
#: schema change is needed. ``STAGE_REVIEWED`` = captured at the review
#: stop-boundary BEFORE any submit (the literal payload the owner reviews);
#: ``STAGE_SUBMITTED`` = the terminal record. A snapshot recorded before these
#: markers existed has no stage and reads as submitted (it was only ever written
#: at submission time).
STAGE_REVIEWED = "reviewed"
STAGE_SUBMITTED = "submitted"


@dataclass(frozen=True)
class SubmissionSnapshot:
    """An immutable per-application snapshot taken at the stop-boundary (#372).

    Frozen so that, once a submission is recorded, the exact answers, material
    versions, posting, and timestamp can never be mutated after the fact — the
    snapshot is the durable evidence of what was submitted.

    ``materials``/``ats_metadata`` are kept for backward-compatibility with the
    existing storage layer; ``material_versions`` and ``posting_url`` are the
    submission-snapshot fields (#372) and round-trip through ``ats_metadata`` in
    the DB repository so no schema change is required.
    """

    id: SubmissionSnapshotId
    application_id: ApplicationId
    answers: dict = field(default_factory=dict)
    materials: list[dict] = field(default_factory=list)
    ats_metadata: dict = field(default_factory=dict)
    material_versions: dict = field(default_factory=dict)
    posting_url: str = ""
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def timestamp(self) -> datetime:
        """When the submission was recorded (alias of ``captured_at``)."""
        return self.captured_at

    @property
    def stage(self) -> str:
        """H3: where in the lifecycle this snapshot was captured.

        ``"reviewed"`` — captured at the review stop-boundary, before any submit
        (what the owner sees in "Review exactly what will be sent");
        ``"submitted"`` — the terminal record. Legacy snapshots (no marker) were
        only ever written at submission time, so they read as submitted.
        """
        return (self.ats_metadata or {}).get("stage") or STAGE_SUBMITTED
